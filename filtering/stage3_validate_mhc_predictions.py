"""
stage3_validate_mhc_predictions.py — Validate candidate peptides with MHC predictors.

This stage takes the synthesis-feasible peptides from stage 2 and runs them
through three independent MHC binding predictors to cross-validate
their super-binder status:

  1. **netMHCpan (primary)** — whichever version is at MHC_DIR_PATH
  2. **netMHCpan 4.0** — legacy model for comparison
  3. **MHCflurry** — affinity prediction model

For each predictor, a ``top8_hla_mean`` score is computed (mean of the 8 best
HLA binding scores — lower is better).  The top 3 000 peptides per predictor
are selected.

All prediction results are memoized so expensive subprocess calls are
skipped on re-runs.  Delete ``MEMOIZATION_DIR/stage-3/*.pickle`` to re-run.
"""
import os

import pandas as pd

from filtering.config import SYNTHESIS_FILTER_OUTPUT_DIR, MEMOIZATION_DIR, NETMHCPAN_40_DIR_PATH, CANDIDATE_PEPTIDES_FASTA
from filtering.constants import SUPERTYPE_LIST
from filtering.utils.scoring import mean_top8_binding_scores
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
    """Validates peptides using all three MHC predictors and selects the best binders.

    Runs the primary netMHCpan, netMHCpan 4.0, and MHCflurry predictions
    for cross-validation.

    Args:
        filtered_peptides: The synthesis-feasible peptide list from stage 2.

    Returns:
        A dictionary with keys: ``scores_df``, ``top_primary``,
        ``top_net40``, ``top_flurry``.
    """
    import sys
    import time

    memo_dir = os.path.join(MEMOIZATION_DIR, "stage-3")
    os.makedirs(memo_dir, exist_ok=True)

    input_fasta = os.path.join(SYNTHESIS_FILTER_OUTPUT_DIR, "result_no_triple.fasta")

    predictor_dfs = []
    result = {
        "scores_df": pd.DataFrame(),
        "top_primary": pd.DataFrame(),
        "top_net40": pd.DataFrame(),
        "top_flurry": pd.DataFrame(),
    }

    print(f"[Sub-stage 3] Input: {len(filtered_peptides)} peptides from {input_fasta}")
    print(f"[Sub-stage 3] Will run 3 MHC binding predictors for cross-validation")
    sys.stdout.flush()

    # ---- Primary netMHCpan (required) ----
    print("[Sub-stage 3] [1/3] Running primary netMHCpan prediction (this may take a few minutes)...")
    sys.stdout.flush()
    t = time.time()
    primary_df = send_to_prediction_as_is(input_fasta)
    primary_df.index.name = "Peptide"
    primary_df.columns = [f"{col}_primary" for col in primary_df.columns]
    predictor_dfs.append(primary_df)
    print(f"[Sub-stage 3] [1/3] Primary netMHCpan complete ({time.time() - t:.1f}s) — {len(primary_df)} peptides scored")
    sys.stdout.flush()

    # ---- netMHCpan 4.0 ----
    print("[Sub-stage 3] [2/3] Running netMHCpan 4.0 prediction...")
    sys.stdout.flush()
    t = time.time()
    net_40_df = send_to_prediction_as_is_net_4(input_fasta)
    net_40_df.index.name = "Peptide"
    net_40_df.columns = [f"{col}_netMHCpan_4.0" for col in net_40_df.columns]
    predictor_dfs.append(net_40_df)
    print(f"[Sub-stage 3] [2/3] netMHCpan 4.0 complete ({time.time() - t:.1f}s) — {len(net_40_df)} peptides scored")
    sys.stdout.flush()

    # ---- MHCflurry ----
    print("[Sub-stage 3] [3/3] Running MHCflurry prediction...")
    sys.stdout.flush()
    t = time.time()
    flurry_df = memoize_function(
        lambda: send_to_mhcflurry(filtered_peptides),
        os.path.join(memo_dir, "mhcflurry-prediction.pickle"),
    )
    flurry_df.index.name = "Peptide"
    flurry_df.columns = [f"{col}_flurry" for col in flurry_df.columns]
    predictor_dfs.append(flurry_df)
    print(f"[Sub-stage 3] [3/3] MHCflurry complete ({time.time() - t:.1f}s) — {len(flurry_df)} peptides scored")
    sys.stdout.flush()

    # ---- Combine available predictor scores ----
    print("[Sub-stage 3] Combining scores from all available predictors...")
    sys.stdout.flush()
    scores_df = pd.concat(predictor_dfs, axis=1)

    # ---- Compute top8_hla_mean per available predictor ----
    primary_cols = [c for c in scores_df.columns if c.endswith("_primary") and c.split("_primary")[0] in SUPERTYPE_LIST]
    if primary_cols:
        scores_df["top8_hla_mean_primary"] = scores_df[primary_cols].apply(mean_top8_binding_scores, axis=1)
        result["top_primary"] = _select_top_n(scores_df, "top8_hla_mean_primary", TOP_N_PEPTIDES)
        print(f"[Sub-stage 3] Top {TOP_N_PEPTIDES} by primary netMHCpan: {len(result['top_primary'])}")

    net_40_cols = [c for c in scores_df.columns if c.endswith("_netMHCpan_4.0") and c.split("_netMHCpan")[0] in SUPERTYPE_LIST]
    if net_40_cols:
        scores_df["top8_hla_mean_net40"] = scores_df[net_40_cols].apply(mean_top8_binding_scores, axis=1)
        result["top_net40"] = _select_top_n(scores_df, "top8_hla_mean_net40", TOP_N_PEPTIDES)
        print(f"[Sub-stage 3] Top {TOP_N_PEPTIDES} by netMHCpan 4.0: {len(result['top_net40'])}")

    flurry_cols = [c for c in scores_df.columns if c.endswith("_flurry")]
    if flurry_cols:
        scores_df["top8_hla_mean_flurry"] = scores_df[flurry_cols].apply(mean_top8_binding_scores, axis=1)
        result["top_flurry"] = _select_top_n(scores_df, "top8_hla_mean_flurry", TOP_N_PEPTIDES)
        print(f"[Sub-stage 3] Top {TOP_N_PEPTIDES} by MHCflurry: {len(result['top_flurry'])}")

    # ---- Cross-predictor agreement summary ----
    all_peptide_sets = []
    predictor_names = []
    if not result["top_primary"].empty:
        all_peptide_sets.append(set(result["top_primary"].index))
        predictor_names.append("primary")
    if not result["top_net40"].empty:
        all_peptide_sets.append(set(result["top_net40"].index))
        predictor_names.append("net4.0")
    if not result["top_flurry"].empty:
        all_peptide_sets.append(set(result["top_flurry"].index))
        predictor_names.append("flurry")

    if len(all_peptide_sets) > 1:
        shared = all_peptide_sets[0]
        for s in all_peptide_sets[1:]:
            shared = shared & s
        union = all_peptide_sets[0]
        for s in all_peptide_sets[1:]:
            union = union | s
        if shared == union:
            print(f"[Sub-stage 3] All {len(predictor_names)} predictors agree: same {len(shared)} peptides selected")
        else:
            print(f"[Sub-stage 3] Cross-predictor overlap: {len(shared)}/{len(union)} peptides shared across {', '.join(predictor_names)}")
    sys.stdout.flush()

    # ---- Summary ----
    n_total = len(filtered_peptides)
    if n_total <= TOP_N_PEPTIDES:
        print(f"[Sub-stage 3] Note: only {n_total} peptides in input (< {TOP_N_PEPTIDES} cutoff), so ALL pass cross-validation")
    print(f"[Sub-stage 3] Final validated peptides: {len(scores_df)}")
    sys.stdout.flush()

    # ---- Write final candidates FASTA for stage 4 (self-similarity) ----
    final_peptides = list(scores_df.index)
    candidate_fasta = CANDIDATE_PEPTIDES_FASTA
    os.makedirs(os.path.dirname(candidate_fasta), exist_ok=True)
    with open(candidate_fasta, "w") as f:
        for i, pep in enumerate(final_peptides):
            f.write(f">candidate_{i}\n{pep}\n")
    print(f"[Sub-stage 3] Wrote {len(final_peptides)} candidate peptides to {candidate_fasta}")
    print(f"[Sub-stage 3] This file is the input for stage 4 (self-similarity analysis)")
    sys.stdout.flush()

    result["scores_df"] = scores_df
    result["candidate_fasta"] = candidate_fasta
    return result
