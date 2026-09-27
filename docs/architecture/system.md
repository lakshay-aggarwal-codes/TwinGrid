# System Architecture

```mermaid
graph TB
    subgraph Client
        FE[React + Vite + Three.js<br/>twin-stream-insight-main]
    end

    subgraph API["FastAPI backend (api/)"]
        Routes[routes/*<br/>digital_twin, optimization,<br/>anomaly, shadow_mode, esg_report,<br/>equipment_health, websocket]
        Services[services/*<br/>twin_service, optimization_service,<br/>anomaly_service, live_broadcast_service,<br/>shadow_mode_service, webhook_service,<br/>esg_report_service]
        Repos[repositories/data_repository.py]
    end

    subgraph Core["Physics + ML core (src/)"]
        Twin[digital_twin.py<br/>DigitalTwin -- single source of<br/>physics truth]
        Gen[data_generator.py<br/>synthetic historical dataset]
        LSTM[lstm_model.py<br/>ThermalForecaster]
        Anom[anomaly_detector.py<br/>LSTM Autoencoder]
        Opt[optimizer.py<br/>JointOptimizer -- PPO via SB3]
        Explain[anomaly_explain.py]
        Bench[facility_benchmarking.py]
        Registry[model_registry.py<br/>JSON lineage log]
    end

    subgraph Storage
        PG[(Postgres<br/>SQLAlchemy + Alembic)]
        Models[models/<br/>forecaster, anomaly, optimizer<br/>.keras / .joblib / .zip]
        Files[data/, logs/<br/>webhooks.json, shadow_mode.jsonl,<br/>registry.json]
    end

    FE <-->|REST + WebSocket, JWT| Routes
    Routes --> Services
    Services --> Repos
    Repos --> PG
    Services --> Core
    Core --> Models
    Services --> Files
    Gen --> Models
```

## Notes

- **`DigitalTwin` is the single source of physics truth.** Both the live
  API path (`step()`/`run_scenario()`) and the offline historical-dataset
  generator (`data_generator.py`, used to train the forecaster and anomaly
  detector) call the same physics methods
  (`compute_cooling_power`/`compute_outlet_temp`/`effective_air_flow_m3_s`).
  Keeping these in sync is why Phase 0's COP and airflow fixes touched
  both call sites, not just the live one -- see the fix commits and
  `docs/model_cards/LIMITATIONS.md`.
- **No message queue yet** (Phase 4, not built): `/api/optimize`'s
  fallback training and PDF report generation run in worker threads
  (`run_in_threadpool`/`asyncio.to_thread`), not a real task queue.
- **File-based state alongside Postgres**: `models/registry.json` (model
  lineage), `data/webhooks.json` (subscribers), `logs/shadow_mode.jsonl`
  (PPO-vs-baseline samples) are deliberately JSON/JSONL, not new DB
  tables -- see each module's docstring for why (avoiding untested
  migrations for opt-in/diagnostic features).
