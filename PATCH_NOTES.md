# TwinGrid small documentation fix

## Changes
- `README.md`: accurately documents the public viewer-access form and the existing "Explore read-only demo" button on the sign-in screen, including the backend feature flag and test coverage.
- `docs/roadmap/EVIDENCE_MATRIX.md`: accurately links the existing Task 31 release-candidate report and records its BLOCKED verdict instead of saying the report does not exist.

## Basis
- `twin-stream-insight-main/src/components/LoginScreen.tsx`
- `twin-stream-insight-main/src/components/LoginScreen.access.test.tsx`
- `docs/roadmap/RC_REPORT.md`

## Verification
Documentation-only changes. The referenced frontend test file already contains coverage for the demo button, disabled-server response, unexpected errors, and duplicate-click prevention. No application code or runtime behaviour was changed. The frontend test suite was not run as part of this patch.
