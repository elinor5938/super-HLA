"""
stage3_validate_mhc_predictions.py — Validate candidate peptides with three MHC predictors.

This stage takes the ~6 600 synthesis-feasible peptides from stage 2 and
runs them through three independent MHC binding predictors to cross-validate
their super-binder status:

  1. **netMHCpan 4.1** (newer EL-rank model)
  2. **netMHCpan 4.0** (legacy EL-rank model, used for comparison)
  3. **MHCflurry**     (affinity prediction model)

For each predictor, a ``one_side_mean`` score is computed (mean of the 8 best
HLA binding scores — lower is better).  The top 3 000 peptides per predictor
are selected.

.. note::
    The original ``stage3_validate_superbinders_mhc_pred.py`` in the legacy
    codebase was partially incomplete (it contained undefined variables like
    ``flury_hla``, ``intersection``, etc. that were leftover from an
    interactive analysis session).  This migration ports the well-defined
    portions: running the three predictors, computing one_side_mean per
    predictor, and selecting the top N peptides.

    Downstream cross-predictor intersection analysis is marked as a TODO
    and should be completed once the variable ambiguities are resolved.

All prediction results are memoized so expensive subprocess calls are
skipped on re-runs.  Delete ``MEMOIZATION_DIR/stage-3/*.pickle`` to re-run.
"""
import os

import pandas as pd

from filtering.config import STAGE2_OUTPUT_DIR, MEMOIZATION_DIR
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
    return df.nsmallest(n, score_col)


def run_stage3(filtered_peptides: list) -> dict:
    """Validates peptides using three MHC predictors and selects the best binders.

    Args:
        filtered_peptides: The synthesis-feasible peptide list from stage 2
            (``stage2_data["filtered_peptides"]``).

    Returns:
        A dictionary with the following keys:

        - ``"scores_df"`` (:class:`pandas.DataFrame`): Combined score table
          with columns from all three predictors, one row per peptide.
        - ``"top_net41"`` (:class:`pandas.DataFrame`): Top ``TOP_N_PEPTIDES``
          peptides ranked by netMHCpan 4.1 one_side_mean.
        - ``"top_net40"`` (:class:`pandas.DataFrame`): Top ``TOP_N_PEPTIDES``
          peptides ranked by netMHCpan 4.0 one_side_mean.
        - ``"top_flurry"`` (:class:`pandas.DataFrame`): Top ``TOP_N_PEPTIDES``
          peptides ranked by MHCflurry one_side_mean.

    .. note::
        Cross-predictor intersection analysis (finding peptides that rank in
        the top N across *all three* predictors) is a TODO.  The supporting
        data is all present in ``scores_df`` — it just needs additional
        filtering logic once requirements are clarified.
    """
    memo_dir = os.path.join(MEMOIZATION_DIR, "stage-3")
    os.makedirs(memo_dir, exist_ok=True)

    # ---- Input FASTA (written by stage 2) ----
    input_fasta = os.path.join(STAGE2_OUTPUT_DIR, "result_no_triple.fasta")

    # ---- Run three predictors (memoized) ----
    print("[Stage 3] Running netMHCpan 4.1 prediction...")
    net_41_df = send_to_prediction_as_is(input_fasta)

    print("[Stage 3] Running netMHCpan 4.0 prediction...")
    net_40_df = send_to_prediction_as_is_net_4(input_fasta)

    print("[Stage 3] Running MHCflurry prediction...")
    flurry_df = memoize_function(
        lambda: send_to_mhcflurry(filtered_peptides),
        os.path.join(memo_dir, "mhcflurry-prediction.pickle"),
    )

    # ---- Rename columns to avoid collisions when joining ----
    net_41_df.index.name = "index"
    net_40_df.index.name = "index"
    flurry_df.index.name = "index"

    net_41_df.columns = [f"{col}_netMHCpan_4.1" for col in net_41_df.columns]
    net_40_df.columns = [f"{col}_netMHCpan_4.0" for col in net_40_df.columns]
    flurry_df.columns = [f"{col}_flurry" for col in flurry_df.columns]

    # ---- Combine all predictor scores ----
    scores_df = pd.concat([net_41_df, net_40_df, flurry_df], axis=1)

    # ---- Compute one_side_mean per predictor ----
    # Identify column subsets for each predictor
    net_41_cols = [c for c in scores_df.columns if c.endswith("_netMHCpan_4.1") and c.split("_netMHCpan")[0] in SUPERTYPE_LIST]
    net_40_cols = [c for c in scores_df.columns if c.endswith("_netMHCpan_4.0") and c.split("_netMHCpan")[0] in SUPERTYPE_LIST]
    flurry_cols   = [c for c in scores_df.columns if c.endswith("_flurry")]

    scores_df["one_side_mean_net41"] = scores_df[net_41_cols].apply(one_side_trimmed_min, axis=1)
    scores_df["one_side_mean_net40"] = scores_df[net_40_cols].apply(one_side_trimmed_min, axis=1)
    scores_df["one_side_mean_flurry"] = scores_df[flurry_cols].apply(one_side_trimmed_min, axis=1)

    # ---- Select top N per predictor ----
    top_net41  = _select_top_n(scores_df, "one_side_mean_net41",  TOP_N_PEPTIDES)
    top_net40  = _select_top_n(scores_df, "one_side_mean_net40",  TOP_N_PEPTIDES)
    top_flurry = _select_top_n(scores_df, "one_side_mean_flurry", TOP_N_PEPTIDES)

    print(f"[Stage 3] Top {TOP_N_PEPTIDES} by netMHCpan 4.1: {len(top_net41)}")
    print(f"[Stage 3] Top {TOP_N_PEPTIDES} by netMHCpan 4.0: {len(top_net40)}")
    print(f"[Stage 3] Top {TOP_N_PEPTIDES} by MHCflurry:     {len(top_flurry)}")

    # TODO: cross-predictor intersection — identify super-binders that rank
    # in top N across all three predictors simultaneously.

    return {
        "scores_df": scores_df,
        "top_net41": top_net41,
        "top_net40": top_net40,
        "top_flurry": top_flurry,
    }
