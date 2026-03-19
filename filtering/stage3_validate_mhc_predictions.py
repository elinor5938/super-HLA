"""
stage3_validate_mhc_predictions.py — Validate candidate peptides with MHC predictors.

This stage takes the synthesis-feasible peptides from stage 2 and runs them
through up to three independent MHC binding predictors to cross-validate
their super-binder status:

  1. **netMHCpan (primary)** — whichever version is at MHC_DIR_PATH (required)
  2. **netMHCpan 4.0** — legacy model for comparison (optional)
  3. **MHCflurry** — affinity prediction model (optional)

For each predictor, a ``one_side_mean`` score is computed (mean of the 8 best
HLA binding scores — lower is better).  The top 3 000 peptides per predictor
are selected.

netMHCpan 4.0 and MHCflurry are optional — if not configured/installed, those
predictors are skipped and the corresponding result keys will be empty DataFrames.

All prediction results are memoized so expensive subprocess calls are
skipped on re-runs.  Delete ``MEMOIZATION_DIR/stage-3/*.pickle`` to re-run.
"""
import os

import pandas as pd

from filtering.config import STAGE2_OUTPUT_DIR, MEMOIZATION_DIR, NETMHCPAN_40_DIR_PATH
from filtering.constants import SUPERTYPE_LIST
from filtering.utils.scoring import one_side_trimmed_min
from filtering.utils.memoize import memoize_function
from filtering.utils.prediction import (
    send_to_prediction_as_is,
    send_to_prediction_as_is_net_4,
    send_to_mhcflurry,
)

# Number of top peptides to select per predictor
TOP_N_PEPTIDES = 3_000


def _select_top_n(df: pd.DataFrame, score_col: str, n: int) -> pd.DataFrame:
    """Returns the top-N rows of ``df`` sorted ascending by ``score_col``."""
    if df.empty or score_col not in df.columns:
        return pd.DataFrame()
    return df.nsmallest(n, score_col)


def run_stage3(filtered_peptides: list) -> dict:
    """Validates peptides using available MHC predictors and selects the best binders.

    The primary netMHCpan prediction (MHC_DIR_PATH) is always run.
    netMHCpan 4.0 and MHCflurry are optional — they are skipped if not
    configured or not installed, with a warning printed.

    Args:
        filtered_peptides: The synthesis-feasible peptide list from stage 2.

    Returns:
        A dictionary with keys: ``scores_df``, ``top_primary``,
        ``top_net40``, ``top_flurry``. Optional predictors return empty
        DataFrames if skipped.
    """
    import sys
    import time

    memo_dir = os.path.join(MEMOIZATION_DIR, "stage-3")
    os.makedirs(memo_dir, exist_ok=True)

    input_fasta = os.path.join(STAGE2_OUTPUT_DIR, "result_no_triple.fasta")

    predictor_dfs = []
    result = {
        "scores_df": pd.DataFrame(),
        "top_primary": pd.DataFrame(),
        "top_net40": pd.DataFrame(),
        "top_flurry": pd.DataFrame(),
    }

    print(f"[Stage 3] Input: {len(filtered_peptides)} peptides from {input_fasta}")
    print(f"[Stage 3] Will run up to 3 MHC binding predictors for cross-validation")
    sys.stdout.flush()

    # ---- Primary netMHCpan (required) ----
    print("[Stage 3] [1/3] Running primary netMHCpan prediction (this may take a few minutes)...")
    sys.stdout.flush()
    t = time.time()
    primary_df = send_to_prediction_as_is(input_fasta)
    primary_df.index.name = "Peptide"
    primary_df.columns = [f"{col}_primary" for col in primary_df.columns]
    predictor_dfs.append(primary_df)
    print(f"[Stage 3] [1/3] Primary netMHCpan complete ({time.time() - t:.1f}s) — {len(primary_df)} peptides scored")
    sys.stdout.flush()

    # ---- netMHCpan 4.0 (optional) ----
    net_40_df = None
    if NETMHCPAN_40_DIR_PATH:
        try:
            print("[Stage 3] [2/3] Running netMHCpan 4.0 prediction...")
            sys.stdout.flush()
            t = time.time()
            net_40_df = send_to_prediction_as_is_net_4(input_fasta)
            net_40_df.index.name = "Peptide"
            net_40_df.columns = [f"{col}_netMHCpan_4.0" for col in net_40_df.columns]
            predictor_dfs.append(net_40_df)
            print(f"[Stage 3] [2/3] netMHCpan 4.0 complete ({time.time() - t:.1f}s) — {len(net_40_df)} peptides scored")
            sys.stdout.flush()
        except Exception as e:
            print(f"[Stage 3] [2/3] WARNING: netMHCpan 4.0 failed ({e}), skipping.")
            sys.stdout.flush()
    else:
        print("[Stage 3] [2/3] netMHCpan 4.0 not configured — skipping")
        sys.stdout.flush()

    # ---- MHCflurry (optional) ----
    flurry_df = None
    try:
        import mhcflurry  # noqa: F401
        print("[Stage 3] [3/3] Running MHCflurry prediction...")
        sys.stdout.flush()
        t = time.time()
        flurry_df = memoize_function(
            lambda: send_to_mhcflurry(filtered_peptides),
            os.path.join(memo_dir, "mhcflurry-prediction.pickle"),
        )
        flurry_df.index.name = "Peptide"
        flurry_df.columns = [f"{col}_flurry" for col in flurry_df.columns]
        predictor_dfs.append(flurry_df)
        print(f"[Stage 3] [3/3] MHCflurry complete ({time.time() - t:.1f}s) — {len(flurry_df)} peptides scored")
        sys.stdout.flush()
    except ImportError:
        print("[Stage 3] [3/3] MHCflurry not installed — skipping")
        sys.stdout.flush()

    # ---- Combine available predictor scores ----
    print("[Stage 3] Combining scores from all available predictors...")
    sys.stdout.flush()
    scores_df = pd.concat(predictor_dfs, axis=1)

    # ---- Compute one_side_mean per available predictor ----
    primary_cols = [c for c in scores_df.columns if c.endswith("_primary") and c.split("_primary")[0] in SUPERTYPE_LIST]
    if primary_cols:
        scores_df["one_side_mean_primary"] = scores_df[primary_cols].apply(one_side_trimmed_min, axis=1)
        result["top_primary"] = _select_top_n(scores_df, "one_side_mean_primary", TOP_N_PEPTIDES)
        print(f"[Stage 3] Top {TOP_N_PEPTIDES} by primary netMHCpan: {len(result['top_primary'])}")

    if net_40_df is not None:
        net_40_cols = [c for c in scores_df.columns if c.endswith("_netMHCpan_4.0") and c.split("_netMHCpan")[0] in SUPERTYPE_LIST]
        if net_40_cols:
            scores_df["one_side_mean_net40"] = scores_df[net_40_cols].apply(one_side_trimmed_min, axis=1)
            result["top_net40"] = _select_top_n(scores_df, "one_side_mean_net40", TOP_N_PEPTIDES)
            print(f"[Stage 3] Top {TOP_N_PEPTIDES} by netMHCpan 4.0: {len(result['top_net40'])}")

    if flurry_df is not None:
        flurry_cols = [c for c in scores_df.columns if c.endswith("_flurry")]
        if flurry_cols:
            scores_df["one_side_mean_flurry"] = scores_df[flurry_cols].apply(one_side_trimmed_min, axis=1)
            result["top_flurry"] = _select_top_n(scores_df, "one_side_mean_flurry", TOP_N_PEPTIDES)
            print(f"[Stage 3] Top {TOP_N_PEPTIDES} by MHCflurry: {len(result['top_flurry'])}")

    result["scores_df"] = scores_df
    return result
