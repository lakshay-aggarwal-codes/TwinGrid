"""
Physics-Informed Neural Network (PINN) for the data centre digital twin.

PATENT CORE: Combines data-driven prediction with physics constraints:
  - L_physics_1: Energy balance — outlet_temp = inlet + Q/(m_dot*cp)
  - L_physics_2: PUE = total_power / it_power
  - L_physics_3: WUE = water_L / it_kWh

Total loss = L_data + 0.1 * L_physics (physics as soft constraint).
Integrates with DigitalTwin and the joint optimizer (J = α·W + β·E + γ·C).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import tensorflow as tf

from src.digital_twin import (
    AIR_DENSITY_KG_M3,
    INLET_TEMP_MAX,
    INLET_TEMP_MIN,
    INTERVAL_MINUTES,
    SPECIFIC_HEAT_AIR_J_KG_K,
    CoolingMode,
    DigitalTwin,
)

from .logging_config import log_error, log_function_entry, log_function_exit, log_training_progress

logger = logging.getLogger(__name__)

# Align with digital_twin and optimizer
MAX_IT_POWER_KW = 500.0
IDLE_FRAC = 0.4
AIRFLOW_M3_S = 8.0
COP = {
    CoolingMode.FREE_AIR: 8.0,
    CoolingMode.CLOSED_LOOP: 4.5,
    CoolingMode.EVAPORATIVE: 3.5,
    CoolingMode.HYBRID: 4.0,
}
COOLING_MODES_ORDER = [
    CoolingMode.FREE_AIR,
    CoolingMode.CLOSED_LOOP,
    CoolingMode.EVAPORATIVE,
    CoolingMode.HYBRID,
]


def _it_power_from_utilisation(utilisation: tf.Tensor) -> tf.Tensor:
    idle = IDLE_FRAC * MAX_IT_POWER_KW
    return idle + (1.0 - IDLE_FRAC) * tf.clip_by_value(utilisation, 0.0, 1.0) * MAX_IT_POWER_KW


def _inlet_from_chilled_and_outside(chilled_water_C: tf.Tensor, outside_C: tf.Tensor) -> tf.Tensor:
    target = chilled_water_C + 3.0
    blended = 0.6 * target + 0.4 * (outside_C - 3.0)
    return tf.clip_by_value(blended, INLET_TEMP_MIN, INLET_TEMP_MAX)


def _outlet_physics(inlet_C: tf.Tensor, it_power_kw: tf.Tensor) -> tf.Tensor:
    heat_w = it_power_kw * 1000.0
    m_dot = AIR_DENSITY_KG_M3 * AIRFLOW_M3_S
    denom = m_dot * SPECIFIC_HEAT_AIR_J_KG_K
    delta_t = heat_w / tf.maximum(denom, 1e-6)
    return inlet_C + delta_t


def _cooling_power_physics(it_power_kw: tf.Tensor, mode_idx: tf.Tensor, outside_C: tf.Tensor) -> tf.Tensor:
    # mode_idx (batch, 4) one-hot -> COP per sample
    cop_vals = tf.constant([[COP[m] for m in COOLING_MODES_ORDER]], dtype=tf.float32)
    cop_per_sample = tf.reduce_sum(mode_idx * cop_vals, axis=-1, keepdims=True)
    use_hybrid = tf.cast(outside_C >= 12.0, tf.float32)
    cop_hybrid = COP[CoolingMode.HYBRID]
    cop_eff = (1.0 - use_hybrid) * cop_per_sample + use_hybrid * cop_hybrid
    return it_power_kw / tf.maximum(cop_eff, 1e-6)


def encode_cooling_mode(mode: CoolingMode | str) -> np.ndarray:
    """One-hot encode cooling mode: [free_air, closed_loop, evaporative, hybrid]."""
    if isinstance(mode, str):
        mode = CoolingMode(mode)
    idx = COOLING_MODES_ORDER.index(mode)
    one_hot = np.zeros(4, dtype=np.float32)
    one_hot[idx] = 1.0
    return one_hot


def build_pinn_model(
    hidden: tuple[int, ...] = (64, 64, 32),
    input_dim: int = 7,
    output_dim: int = 3,
) -> tf.keras.Model:
    """
    Build PINN: inputs (utilisation, outside_temp, cooling_mode_4, chilled_water_temp), outputs (outlet_temp, water_consumed_L, pue).
    """
    inputs = tf.keras.layers.Input(shape=(input_dim,), name="inputs")
    x = inputs
    for i, units in enumerate(hidden):
        x = tf.keras.layers.Dense(units, activation="relu", name=f"dense_{i}")(x)
    outputs = tf.keras.layers.Dense(output_dim, activation=None, name="outputs")(x)
    # Reasonable output ranges: outlet 20–50°C, water 0–500 L, pue 1–3
    outlet = tf.keras.layers.Lambda(lambda t: 20.0 + 30.0 * tf.nn.sigmoid(t[..., 0:1]), name="outlet_temp")(outputs)
    water = tf.keras.layers.Lambda(lambda t: 500.0 * tf.nn.softplus(t[..., 1:2]) / tf.math.log(2.0 + 1.0), name="water_consumed")(outputs)
    pue = tf.keras.layers.Lambda(lambda t: 1.0 + 2.0 * tf.nn.sigmoid(t[..., 2:3]), name="pue")(outputs)
    out_concat = tf.keras.layers.Concatenate(axis=-1, name="prediction")([outlet, water, pue])
    model = tf.keras.Model(inputs=inputs, outputs=out_concat)
    return model


class PhysicsInformedNN:
    """
    Physics-Informed Neural Network for data centre state prediction.

    PATENT: Soft physics constraints (energy balance, PUE, WUE) combined with
    data loss. Used with the joint optimizer for surrogate prediction.
    """

    def __init__(
        self,
        *,
        physics_weight: float = 0.1,
        hidden: tuple[int, ...] = (64, 64, 32),
    ) -> None:
        self.physics_weight = physics_weight
        self.hidden = hidden
        self._model = build_pinn_model(hidden=hidden)
        self._optimizer = tf.keras.optimizers.Adam(learning_rate=1e-3)

    @property
    def model(self) -> tf.keras.Model:
        return self._model

    def _assemble_inputs(
        self,
        utilisation: tf.Tensor,
        outside_temp: tf.Tensor,
        cooling_mode_encoded: tf.Tensor,
        chilled_water_temp: tf.Tensor,
    ) -> tf.Tensor:
        return tf.concat([
            tf.reshape(utilisation, (-1, 1)),
            tf.reshape(outside_temp, (-1, 1)),
            tf.reshape(cooling_mode_encoded, (-1, 4)),
            tf.reshape(chilled_water_temp, (-1, 1)),
        ], axis=-1)

    def _physics_losses(
        self,
        inputs: tf.Tensor,
        pred: tf.Tensor,
    ) -> tuple[tf.Tensor, tf.Tensor, tf.Tensor]:
        utilisation = inputs[:, 0:1]
        outside_temp = inputs[:, 1:2]
        cooling_mode_encoded = inputs[:, 2:6]
        chilled_water_temp = inputs[:, 6:7]

        outlet_pred = pred[:, 0:1]
        water_pred = pred[:, 1:2]
        pue_pred = pred[:, 2:3]

        it_power = _it_power_from_utilisation(utilisation)
        inlet = _inlet_from_chilled_and_outside(chilled_water_temp, outside_temp)
        outlet_physics = _outlet_physics(inlet, it_power)
        L_physics_1 = tf.reduce_mean(tf.square(outlet_pred - outlet_physics))

        cooling_power = _cooling_power_physics(it_power, cooling_mode_encoded, outside_temp)
        total_power = it_power + cooling_power
        pue_physics = total_power / tf.maximum(it_power, 1e-6)
        L_physics_2 = tf.reduce_mean(tf.square(pue_pred - pue_physics))

        it_kwh = it_power * (INTERVAL_MINUTES / 60.0)
        wue_implied = water_pred / tf.maximum(it_kwh, 1e-6)
        wue_violation_lo = tf.maximum(0.0, -wue_implied)
        wue_violation_hi = tf.maximum(0.0, wue_implied - 20.0)
        L_physics_3 = tf.reduce_mean(tf.square(wue_violation_lo) + tf.square(wue_violation_hi))

        return L_physics_1, L_physics_2, L_physics_3

    def train_step(
        self,
        x: tf.Tensor,
        y_true: tf.Tensor,
    ) -> dict[str, float]:
        """Single training step: L_data + physics_weight * (L_physics_1 + L_physics_2 + L_physics_3)."""
        with tf.GradientTape() as tape:
            pred = self._model(x, training=True)
            L_data = tf.reduce_mean(tf.square(pred - y_true))
            L_p1, L_p2, L_p3 = self._physics_losses(x, pred)
            L_physics = L_p1 + L_p2 + L_p3
            total_loss = L_data + self.physics_weight * L_physics

        grads = tape.gradient(total_loss, self._model.trainable_variables)
        self._optimizer.apply_gradients(zip(grads, self._model.trainable_variables))

        return {
            "loss": float(total_loss),
            "L_data": float(L_data),
            "L_physics_1": float(L_p1),
            "L_physics_2": float(L_p2),
            "L_physics_3": float(L_p3),
        }

    def fit(
        self,
        x: np.ndarray,
        y: np.ndarray,
        epochs: int = 100,
        batch_size: int = 32,
        validation_split: float = 0.1,
        verbose: int = 1,
    ) -> dict[str, list[float]]:
        """
        Train PINN with custom loop (data + physics loss).
        x: (N, 7) — utilisation, outside_temp, cooling_mode_4, chilled_water_temp
        y: (N, 3) — outlet_temp, water_consumed_L, pue
        """
        log_function_entry(
            "PINN.fit",
            x_shape=x.shape,
            y_shape=y.shape,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split
        )
        
        try:
            n = len(x)
            if n == 0:
                error_msg = "No training samples"
                log_error("PINN.fit", ValueError(error_msg))
                raise ValueError(error_msg)
            idx = np.random.permutation(n)
            split = max(1, int(n * (1 - validation_split)))
            train_idx, val_idx = idx[:split], idx[split:]
            x_train, y_train = tf.constant(x[train_idx], dtype=tf.float32), tf.constant(y[train_idx], dtype=tf.float32)
            x_val = tf.constant(x[val_idx], dtype=tf.float32) if len(val_idx) > 0 else x_train[:1]
            y_val = tf.constant(y[val_idx], dtype=tf.float32) if len(val_idx) > 0 else y_train[:1]

            history: dict[str, list[float]] = {"loss": [], "val_loss": [], "L_data": [], "L_physics_1": []}
            for epoch in range(epochs):
                perm = np.random.permutation(len(train_idx))
                epoch_loss = []
                for start in range(0, len(perm), batch_size):
                    batch_idx = perm[start : start + batch_size]
                    bx = tf.gather(x_train, batch_idx)
                    by = tf.gather(y_train, batch_idx)
                    metrics = self.train_step(bx, by)
                    epoch_loss.append(metrics["loss"])
                mean_loss = np.mean(epoch_loss)
                pred_val = self._model(x_val, training=False)
                L_data_val = float(tf.reduce_mean(tf.square(pred_val - y_val)))
                L_p1, L_p2, L_p3 = self._physics_losses(x_val, pred_val)
                val_loss = L_data_val + self.physics_weight * (float(L_p1) + float(L_p2) + float(L_p3)) if len(val_idx) > 0 else mean_loss
                history["loss"].append(mean_loss)
                history["val_loss"].append(val_loss)
                history["L_data"].append(metrics["L_data"])
                history["L_physics_1"].append(metrics["L_physics_1"])
                
                # Log training progress
                log_training_progress(
                    "PINN",
                    epoch=epoch + 1,
                    loss=mean_loss,
                    val_loss=val_loss,
                    L_data=metrics["L_data"],
                    L_physics_1=metrics["L_physics_1"]
                )
                
                if verbose and (epoch + 1) % max(1, epochs // 10) == 0:
                    logger.info(
                        "PINN epoch %d loss=%.4f val_loss=%.4f L_data=%.4f L_p1=%.4f",
                        epoch + 1, mean_loss, val_loss, metrics["L_data"], metrics["L_physics_1"],
                    )
            
            log_function_exit("PINN.fit", result=f"Training completed for {epochs} epochs")
            return history
        except Exception as e:
            log_error("PINN.fit", e)
            raise

    def predict(
        self,
        utilisation: np.ndarray | float,
        outside_temp: np.ndarray | float,
        cooling_mode_encoded: np.ndarray,
        chilled_water_temp: np.ndarray | float,
    ) -> np.ndarray:
        """Predict (outlet_temp, water_consumed_L, pue). cooling_mode_encoded: (N, 4) or (4,)."""
        u = np.atleast_1d(np.asarray(utilisation, dtype=np.float32))
        o = np.atleast_1d(np.asarray(outside_temp, dtype=np.float32))
        c = np.asarray(cooling_mode_encoded, dtype=np.float32)
        if c.ndim == 1:
            c = np.broadcast_to(c, (u.shape[0], 4))
        ch = np.atleast_1d(np.asarray(chilled_water_temp, dtype=np.float32))
        n = max(u.shape[0], o.shape[0], c.shape[0], ch.shape[0])
        u = np.broadcast_to(u.ravel()[:n], (n,))
        o = np.broadcast_to(o.ravel()[:n], (n,))
        ch = np.broadcast_to(ch.ravel()[:n], (n,))
        if c.shape[0] != n:
            c = np.broadcast_to(c, (n, 4))
        x = np.concatenate([u[:, None], o[:, None], c, ch[:, None]], axis=-1)
        out = self._model.predict(x, verbose=0)
        return out

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self._model.save_weights(str(path / "pinn_weights.weights.h5"))
        logger.info("PINN saved to %s", path)

    def load(self, path: str | Path) -> None:
        path = Path(path)
        self._model.load_weights(str(path / "pinn_weights.weights.h5"))
        logger.info("PINN loaded from %s", path)


def generate_training_data_from_twin(
    twin: DigitalTwin,
    n_samples: int = 2000,
    seed: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate (x, y) for PINN from digital twin rollouts.
    x: (N, 7) — utilisation, outside_temp, mode_4, chilled_water_temp
    y: (N, 3) — outlet_temp, water_consumed_L (per step), pue
    """
    rng = np.random.default_rng(seed)
    chilled_range = (5.0, 15.0)
    x_list: list[list[float]] = []
    y_list: list[list[float]] = []

    for _ in range(n_samples):
        utilisation = float(rng.uniform(0.2, 0.95))
        outside_temp = float(rng.uniform(15.0, 35.0))
        mode_idx = rng.integers(0, 4)
        mode = COOLING_MODES_ORDER[mode_idx]
        mode_onehot = encode_cooling_mode(mode)

        action = {
            "utilisation": utilisation,
            "outside_temp_C": outside_temp,
            "cooling_mode": mode,
        }
        state = twin.step(action)
        inlet = state.server_inlet_temp_C
        chilled_water = inlet - 3.0
        chilled_water = max(chilled_range[0], min(chilled_range[1], chilled_water))
        outlet = state.server_outlet_temp_C
        it_power = state.it_power_kw
        pue = state.pue
        consumed_this_step = (
            state.wue * it_power * (INTERVAL_MINUTES / 60.0)
            if state.wue and it_power > 0.01
            else 0.0
        )
        x_list.append([utilisation, outside_temp] + list(mode_onehot) + [chilled_water])
        y_list.append([outlet, consumed_this_step, pue])

    return np.array(x_list, dtype=np.float32), np.array(y_list, dtype=np.float32)
