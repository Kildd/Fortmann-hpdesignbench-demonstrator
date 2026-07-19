# Vendored analysis engine

Frozen snapshot of the HP-slab analysis stack used by this demonstrator.

- Not a git submodule of `hpdesignbench`
- No runtime coupling to the original repository
- Update only by intentionally replacing files here and pinning versions in `requirements-engine.txt`

Entry point for the website: `demo_optimize.py` (Optuna TPE → `analysis()`).
