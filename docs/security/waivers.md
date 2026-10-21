# Dependency waivers

Each waiver names the package, why it is not exploitable here, the owner and an expiry. Re-run `pip-audit` / `npm audit` before the expiry; an expired waiver is a failed review.

| Package (where) | Advisory | Why it does not apply here | Owner | Expires |
|---|---|---|---|---|
| `python-jose` 3.5.0 (runtime) | PYSEC-2026-4298 / CVE-2026-85394: HS256 tokens can be forged by someone who holds the service's public key, when the accepted algorithms are not restricted | `api/auth.py` decodes with `algorithms=[ALGORITHM]` (HS256) and signs with a symmetric secret; there is no public key to hold. Tests `test_forged_or_malformed_tokens_are_401` (HS512, `none`, wrong key) fail if the list is widened. No fixed release exists. | Lakshay | 2027-01-21 |
| `ecdsa` 0.19.2 (runtime, pulled in by `python-jose`) | PYSEC-2026-1325 / CVE-2024-23342: timing side channel when signing with P-256 | Nothing here signs with ECDSA; tokens are HS256 and `python-jose` uses its `cryptography` backend. The project calls side channels out of scope and plans no fix. | Lakshay | 2027-01-21 |
| `tailwindcss` 3.4.19 chain: `braces`, `micromatch`, `fast-glob`, `chokidar`, `postcss-selector-parser`, `postcss-nested`, `@tailwindcss/typography`, `tailwindcss-animate`, `lovable-tagger` (frontend devDependencies; 10 advisories, 5 high) | Stack exhaustion on deeply nested glob patterns; quadratic selector parsing | Run only on the developer's and CI's machine while building, over this repo's own source files; none of it is in the shipped bundle. `npm audit` offers no real fix (it suggests downgrading `lovable-tagger`); the proper fix is the Tailwind 4 migration, a separate task. | Lakshay | 2027-01-21 |

Upgraded instead of waived (Task 27): `pillow` 12.3.0 to 13.0.0, `certifi` 2026.7.22 to 2026.10.19, `vite` 7.3.6 to 7.3.7.
