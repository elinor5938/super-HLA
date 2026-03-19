"""
filtering/main.py — Orchestration entry point for the filtering pipeline.

Usage (from the project root):
    python -m filtering.main

This script runs all four filtering stages sequentially:
  Stage 0 - Load data (MCMC simulation results + HLA combination map)
  Stage 1 - CD-HIT clustering (two rounds, ~55k → ~8.4k peptides)
  Stage 2 - Synthesis difficulty filter (~8.4k → ~6.6k peptides)
  Stage 3 - MHC prediction cross-validation (top 3000 per predictor)

All stage inputs/outputs are connected automatically.  Intermediate results
are memoized to disk — re-running skips expensive steps that are already done.

Prerequisites:
  1. Both MCMC and filtering .env variables must be configured (see README.md).
  2. cd-hit must be installed and on your PATH.
  3. netMHCpan 4.1 or 4.2 must be installed.
  4. (Optional) netMHCpan 4.0 for cross-validation.
  5. (Optional) Python package mhcflurry for cross-validation.
"""
import os
import sys
import time

# Ensure the project root is on sys.path so both `python -m filtering.main`
# and `python filtering/main.py` resolve the `filtering` package correctly.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from filtering.stage0_load_data import run_stage0
from filtering.stage1_cdhit_clustering import run_stage1
from filtering.stage2_filter_synthesis import run_stage2
from filtering.stage3_validate_mhc_predictions import run_stage3


def main():
    import sys as _sys

    print("=" * 60)
    print("  Super-HLA Filtering Pipeline")
    print("=" * 60)
    _sys.stdout.flush()

    total_start = time.time()

    # ── Stage 0 ──────────────────────────────────────────────────────────────
    print("\n" + "-" * 60)
    print("[Stage 0] Loading MCMC simulation data...")
    print("-" * 60)
    _sys.stdout.flush()
    t0 = time.time()
    stage0_data = run_stage0()
    print(f"[Stage 0] Done in {time.time() - t0:.1f}s — "
          f"{len(stage0_data['threshold_8_hla_passing_peptides'])} HLA combinations with >=8 binders")
    _sys.stdout.flush()

    # ── Stage 1 ──────────────────────────────────────────────────────────────
    print("\n" + "-" * 60)
    print("[Stage 1] Two-round CD-HIT clustering")
    print("-" * 60)
    _sys.stdout.flush()
    t1 = time.time()
    stage1_data = run_stage1(stage0_data)
    print(f"[Stage 1] Done in {time.time() - t1:.1f}s — "
          f"{len(stage1_data['consensus_peptides'])} representative peptides")
    _sys.stdout.flush()

    # ── Stage 2 ──────────────────────────────────────────────────────────────
    print("\n" + "-" * 60)
    print("[Stage 2] Synthesis difficulty filter")
    print("-" * 60)
    _sys.stdout.flush()
    t2 = time.time()
    stage2_data = run_stage2(stage1_data["consensus_peptides"])
    print(f"[Stage 2] Done in {time.time() - t2:.1f}s — "
          f"{len(stage2_data['filtered_peptides'])} synthesis-feasible peptides")
    _sys.stdout.flush()

    # ── Stage 3 ──────────────────────────────────────────────────────────────
    if not stage2_data["filtered_peptides"]:
        print("\n[Stage 3] No peptides to validate — skipping.")
        stage3_data = {"scores_df": None, "top_primary": [], "top_net40": [], "top_flurry": []}
    else:
        print("\n" + "-" * 60)
        print("[Stage 3] MHC binding cross-validation")
        print("-" * 60)
        _sys.stdout.flush()
        t3 = time.time()
        stage3_data = run_stage3(stage2_data["filtered_peptides"])
        print(f"[Stage 3] Done in {time.time() - t3:.1f}s")
        _sys.stdout.flush()

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Pipeline Complete")
    print(f"  Total runtime: {time.time() - total_start:.1f}s")
    print("=" * 60)
    print(f"  Input peptides (>=8 HLA binders): {len(stage0_data['threshold_8_hla_passing_peptides'])}")
    print(f"  After CD-HIT clustering:          {len(stage1_data['consensus_peptides'])}")
    print(f"  After synthesis filter:            {len(stage2_data['filtered_peptides'])}")
    print(f"  Top by primary netMHCpan:          {len(stage3_data['top_primary'])}")
    print(f"  Top by netMHCpan 4.0:              {len(stage3_data['top_net40'])}")
    print(f"  Top by MHCflurry:                  {len(stage3_data['top_flurry'])}")
    print("=" * 60)
    print("\nFiltering pipeline finished. Results are ready for downstream analysis.")
    _sys.stdout.flush()


if __name__ == "__main__":
    main()
