"""
utils/scoring.py — Peptide scoring, binding analysis, and data loading helpers.

This module consolidates all the functions from the original ``common_utils.py``
that deal with loading simulation data, computing HLA binding statistics, and
selecting consensus peptides from clusters.
"""
import os

import pandas as pd

from filtering.constants import SUPERTYPE_LIST


# ---------------------------------------------------------------------------
# Binding score helpers
# ---------------------------------------------------------------------------

def one_side_trimmed_min(series: pd.Series) -> float:
    """Returns the mean of the 8 lowest (best) binding rank scores in a series.

    The "one-sided trimmed minimum" is the key metric used throughout the
    pipeline to represent a peptide's binding strength.  By averaging the 8
    best scores across all supertypes we reward broad coverage while reducing
    noise from marginal binders.

    Args:
        series: A pandas Series of ``%Rank_EL`` binding scores for one peptide
            across all HLA supertypes (lower = stronger binder).

    Returns:
        The mean of the 8 lowest values in ``series``.
    """
    return series.sort_values(ascending=True)[0:8].mean()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def create_dict_of_df(directory: str) -> dict:
    """Loads MCMC simulation CSVs from a directory into a dictionary of DataFrames.

    Each CSV file represents one simulation seed.  Only rows where
    ``probabilty_res_MCMC == "True"`` (MCMC-accepted peptides) are retained.
    Duplicate peptides within the same seed are dropped (keeping first
    occurrence), and peptides that already appeared in an earlier seed's file
    are excluded to avoid double-counting across seeds.

    Args:
        directory: Path to a directory containing one or more ``.csv`` files,
            each produced by the MCMC pipeline.

    Returns:
        A dictionary mapping the CSV filename stem (without extension) to a
        DataFrame indexed by ``"Peptide"``.

    Raises:
        FileNotFoundError: If ``directory`` does not exist.
    """
    if not os.path.exists(directory):
        raise FileNotFoundError(f"Simulation CSV directory not found: {directory!r}")

    df_dict: dict = {}
    seen_peptides: set = set()

    for filename in os.listdir(directory):
        if not filename.endswith(".csv"):
            continue

        df_key = filename.rstrip(".csv")
        df = pd.read_csv(os.path.join(directory, filename), low_memory=False)

        # Keep only MCMC-accepted rows
        df = df[df["probabilty_res_MCMC"] == "True"].copy()
        df = df.drop_duplicates(subset="Peptide", keep="first")

        if not seen_peptides:
            # First file — accept all peptides
            seen_peptides.update(df["Peptide"].unique())
        else:
            # Subsequent files — remove peptides already seen in earlier seeds
            df = df[~df["Peptide"].isin(seen_peptides)]
            seen_peptides.update(df["Peptide"].unique())

        df.set_index("Peptide", inplace=True)
        df_dict[df_key] = df

    return df_dict


# ---------------------------------------------------------------------------
# HLA binding mapping
# ---------------------------------------------------------------------------

def create_hla_binding_mappings(
    df: pd.DataFrame,
    supertypes_list: list = SUPERTYPE_LIST,
) -> tuple:
    """Builds a mapping from HLA combinations to their binding peptides.

    A peptide is considered to "bind" an HLA type if its ``%Rank_EL`` score
    for that type is ``< 2`` (includes both strong and weak binders per
    standard NetMHCpan convention).

    Args:
        df: DataFrame indexed by peptide sequence with HLA supertypes as
            columns containing ``%Rank_EL`` binding scores.
        supertypes_list: List of HLA supertype column names to consider.
            Defaults to :data:`~filtering.constants.SUPERTYPE_LIST`.

    Returns:
        A 2-tuple ``(hla_peptide_map, binding_counts)`` where:

        - ``hla_peptide_map`` maps each ``tuple`` of binding HLA types to
          ``[list_of_peptides, count]``.
        - ``binding_counts`` maps each HLA combination tuple to the integer
          count of peptides binding it.

    Example::

        hla_peptide_map[('HLA-A*03:01', 'HLA-B*27:05')] == [['RQAMVHASK', ...], 42]
    """
    hla_supertypes = pd.Series(supertypes_list)
    hla_peptide_map: dict = {}
    binding_counts: dict = {}

    for peptide in df.index:
        # Identify which supertypes this peptide binds (score < 2)
        binding_hlas = hla_supertypes.values[df.loc[peptide][hla_supertypes] < 2]
        binding_hlas.sort()
        hla_combination = tuple(binding_hlas)

        if hla_combination not in hla_peptide_map:
            hla_peptide_map[hla_combination] = [[peptide], 1]
            binding_counts[hla_combination] = 1
        else:
            hla_peptide_map[hla_combination][0].append(peptide)
            hla_peptide_map[hla_combination][1] += 1
            binding_counts[hla_combination] += 1

    return hla_peptide_map, binding_counts


def get_peptides_by_hla_threshold(
    simulation_dfs: dict,
    min_hla_count: int,
    hla_combinations_map: dict,
) -> dict:
    """Collects peptides that bind to at least ``min_hla_count`` HLA supertypes.

    Aggregates results from all simulation seeds and maps them to their HLA
    combination ID (as stored in ``hla_combinations_map``).

    Args:
        simulation_dfs: Dictionary of per-seed DataFrames as returned by
            :func:`create_dict_of_df`.
        min_hla_count: Minimum number of HLA supertypes a peptide must bind to.
        hla_combinations_map: Pre-computed mapping from HLA combination tuples
            to their integer IDs (loaded from the HLA combinations pickle in
            stage 0).

    Returns:
        A dictionary mapping each qualifying HLA combination ID to a list of
        peptide sequences that pass the threshold across all seeds.

    Example::

        {
            42: ["ALFPHIMTY", "RLMPIFNTY", ...],
            17: ["RQREPFYQR", ...],
        }
    """
    threshold_passing_peptides: dict = {}

    for seed_df in simulation_dfs.values():
        hla_peptide_map, _ = create_hla_binding_mappings(seed_df, supertypes_list=SUPERTYPE_LIST)

        for hla_combo, (peptides, _) in hla_peptide_map.items():
            if len(hla_combo) < min_hla_count:
                continue

            # Resolve the numeric ID for this HLA combination
            combo_ids = [v for k, v in hla_combinations_map.items() if k == hla_combo]
            if not combo_ids:
                continue
            combo_id = combo_ids[0]

            if combo_id not in threshold_passing_peptides:
                threshold_passing_peptides[combo_id] = list(peptides)
            else:
                threshold_passing_peptides[combo_id].extend(peptides)

    return threshold_passing_peptides


# ---------------------------------------------------------------------------
# Consensus selection
# ---------------------------------------------------------------------------

def select_cluster_consensus(cluster_df: pd.DataFrame, scores_df: pd.DataFrame) -> pd.DataFrame:
    """Selects one representative (consensus) peptide per CD-HIT cluster.

    The representative is the peptide with the lowest ``one_side_mean`` score
    within the cluster that does *not* have ``P``, ``D``, or ``E`` at position
    4 (index 3).  If all peptides in a cluster have a PDE at position 4, the
    one with the lowest score is picked regardless.

    Args:
        cluster_df: DataFrame produced by
            :func:`~filtering.utils.clustering.parse_cdhit_clusters`, with
            columns ``cluster_n``, ``cluster_size``, ``is_consensus``, and
            ``sim_to_is_consensus``.  The index is the peptide sequence.
        scores_df: The robust DataFrame (from stage 0) containing
            ``one_side_mean`` per peptide, indexed by ``"Peptide"``.

    Returns:
        A merged DataFrame with an additional ``"consensus_SB"`` column.
        Rows where ``consensus_SB == "consensus"`` are the chosen
        representatives.

    Raises:
        Exception: If the number of consensus entries does not equal the
            maximum cluster number (sanity check).
    """
    # Merge cluster assignments with peptide binding scores
    merged = cluster_df.merge(
        scores_df,
        how="left",
        left_on="index",
        right_on="Peptide",
        suffixes=("_cluster", "_y"),
    )
    merged.drop_duplicates(subset="Peptide", keep="first", inplace=True)
    merged["cluster_size"] = merged["cluster_size"].replace(["Singleton"], 1)
    merged["pos_4"] = [pep[3] for pep in merged["Peptide"]]
    merged["consensus_SB"] = None

    PDE = {"P", "D", "E"}

    for cluster_num in merged["cluster_n"].sort_values().unique():
        cluster_rows = merged[merged["cluster_n"] == cluster_num].copy()
        non_pde_rows = cluster_rows[~cluster_rows["pos_4"].isin(PDE)]

        if not non_pde_rows.empty:
            best_idx = non_pde_rows["one_side_mean"].idxmin()
        else:
            # All peptides have PDE at position 4 — pick best anyway
            best_idx = cluster_rows["one_side_mean"].idxmin()

        merged.at[best_idx, "consensus_SB"] = "consensus"

    # Sanity check: one consensus per cluster
    n_clusters = merged["cluster_n"].max()
    n_consensus = merged[merged["consensus_SB"] == "consensus"].shape[0]
    if n_clusters != n_consensus:
        raise ValueError(
            f"Consensus count mismatch: expected {n_clusters} clusters "
            f"but found {n_consensus} consensus entries."
        )

    return merged
