# Data Flow

## Training-time (offline)

```mermaid
graph LR
    Gen[data_generator.py<br/>generate_sensor_data]
    CSV[data/raw/sensor_data.csv<br/>90 days synthetic]
    Split{80/20<br/>chronological split}
    LSTMTrain[ThermalForecaster.train]
    AnomTrain[AnomalyDetector.train<br/>normal rows only]
    AnomEval[held-out F1/precision/recall]
    PPOTrain[JointOptimizer.train<br/>x3 seeds, live DigitalTwin env]
    Reg[model_registry.log_model]

    Gen --> CSV --> Split
    Split -->|train 80%| LSTMTrain
    Split -->|train 80%, normal only| AnomTrain
    Split -->|test 20%, held out| AnomEval
    AnomTrain --> AnomEval
    PPOTrain -->|no historical dataset,<br/>trains against live physics| Reg
    LSTMTrain --> Reg
    AnomEval --> Reg
```

## Request-time (live)

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant WS as /ws/live
    participant Broadcast as live_broadcast_service
    participant Twin as shared DigitalTwin
    participant Anom as anomaly_service
    participant Hook as webhook_service

    FE->>WS: connect (JWT)
    loop every 3s
        Broadcast->>Twin: step(diurnal utilisation/outside_temp,<br/>own water_stress random walk)
        Twin-->>Broadcast: DataCentreState
        Broadcast-->>FE: broadcast state
        FE->>Anom: GET /api/anomaly_score (last 12 steps)
        Anom-->>FE: score, alert, explanation (if alert)
        alt alert fired
            Anom->>Hook: dispatch_alert()
            Hook-->>Hook: POST to each registered subscriber
        end
    end
```

## Notes

- The live broadcast loop and `/api/simulate`/`/api/whatif` are
  **deliberately independent** data paths: the broadcast loop generates
  its own diurnal utilisation/outside-temp/water-stress (autonomous "live
  facility" telemetry), while `/api/simulate` and `/api/whatif` build
  profiles from the sidebar's slider values (a "what-if" preview). See the
  Sustainability tab's "Live Water Stress" label and Phase 0 fix #3.
- `/api/anomaly_score` is polled by the frontend every ~3s; the webhook
  path (Phase 3) is the alternative for external consumers who shouldn't
  have to poll.
