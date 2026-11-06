# Amendment to TASK_07_ADR.md, dated 2026-11-06 (append as Appendix)

**Authority:** owner approval of Task 9 (decision D-2, bundle-only registry), 2026-11-06. Detail and reasons: `TASK_09_ADR.md` section 7A. TASK_07_ADR.md itself (SHA-256 `8f13794c...f7ccf438`) is not edited here.

- **D3.** Tier 1 (6 racks, 37 rack probes, 3 power channels) is registered in the dataset bundle `entity` table, not materialised as `asset`/`sensor` rows in v1. Tier 2 register-only and the 12 deferred supplementary columns are unchanged.
- **D6.** Attachments (probe to rack, power channel to its own `pdu` entry, Tier 2 to the room `zone`) are register relationships with the same meaning and the same ids. No Asset, Sensor, AssetEdge or AssetPose row exists in v1. Later materialisation follows the original D6.
- **D9.** Separate Facility, separate namespace, no edges to demo assets: unchanged. The Facility row is the only shared-table row; created after the demo Facility by the owner-run script, subject to Task 9 D-8.
- **Reason.** `GET /api/maintenance/health` is not facility-scoped (every asset and sensor is listed), and the current sensor-creation function defaults `source_tz` to `UTC`.
