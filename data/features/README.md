# data/features/

Model-ready features — windowed, scaled, and split into
train/validation/test — read directly by training scripts in
`notebooks/train_all.py` and `src/predictive_maintenance/` (Phase 5).

**Not yet populated.** Created in Phase 1 as a placeholder.

Contract for anything written here:
- Every file documents which `data/cleaned/` inputs it was built from and
  the exact feature-engineering parameters used (window size, scaler
  type, split ratio) — so results are reproducible, not just plausible.
- Not committed to git — regenerate via the relevant script rather than
  storing derived arrays in version control.