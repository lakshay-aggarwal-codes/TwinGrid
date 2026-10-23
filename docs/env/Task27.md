# Task 27 environment variables

| Variable | Default | Meaning |
|---|---|---|
| `RATE_LIMIT_CARBON_SCHEDULE` | `30/minute` | Rate limit of `GET /api/carbon/schedule` (same limiter as the core routes). The route reads the memoised carbon signal; it does not run the twin. |

No other configuration. No migration, no new dependency. The carbon file itself is configured as before (`data/cleaned/carbon_intensity.csv`, `SITE_TIMEZONE`).
