# Model artifact load failure

Signals: `/readyz` `components` shows a model `degraded` or `not_loaded`; `anomaly_scoring_errors_total` rising; start-up logs
an integrity or promotion error. Only promoted, integrity-verified artifacts load (`ARTIFACT_VERIFY=enforce`; in production it
cannot be relaxed).

1. `docker compose logs backend --tail 200` and find the load error for the named model.
2. Check the mounted `models/` directory is present and unchanged (compose mounts it read-only) and that `models/registry.json` still
   lists the promoted version. A hash mismatch means the files differ from the manifest: restore them, do not disable verification.
3. Redeploy or restore the artifacts, then `docker compose restart backend` and confirm the component is `ok` in `/readyz`.
4. While degraded the live feed and history keep working; anomaly scoring reports its own unavailable status instead of inventing results.
