"""
stage0_load_data.py — Load and cache the three core datasets for the filtering pipeline.

This stage is responsible for loading the raw data produced by the MCMC simulation
and preparing it for the CD-HIT clustering steps that follow.

Inputs (configured via .env):
  - ACCEPTED_PEPTIDES_CSV_PATH      : CSV with all MCMC simulation results combined.
  - SIMULATION_CSV_DIR      : Directory of per-seed simulation output CSVs.
  - HLA_COMBINATIONS_PICKLE : Pickle mapping HLA combination tuples → IDs.
  - MEMOIZATION_DIR         : Root folder for pickle caches.

Output:
  A dictionary with the following keys, returned by ``run_stage0()``:
  - ``accepted_peptides_df``                      : The main simulation DataFrame.
  - ``df_dict``                         : Per-seed simulation DataFrames.
  - ``all_hla_combinations``            : Mapping of HLA combos → IDs.
  - ``threshold_8_hla_passing_peptides``: Peptides passing the 8-HLA threshold.
"""
import os
import pickle

import pandas as pd

from filtering.config import (
    ACCEPTED_PEPTIDES_CSV_PATH,
    SIMULATION_CSV_DIR,
    HLA_COMBINATIONS_PICKLE,
    MEMOIZATION_DIR,
)
from filtering.constants import SUPERTYPE_LIST, MIN_HLA_BINDING_COUNT
from filtering.utils.memoize import memoize_function
from filtering.utils.scoring import (
    mean_top8_binding_scores,
    create_dict_of_df,
    get_peptides_by_hla_threshold,
)


def _load_accepted_peptides() -> pd.DataFrame:
    """Loads the combined MCMC results CSV and computes the top8_hla_mean score."""
    accepted_peptides_df = pd.read_csv(ACCEPTED_PEPTIDES_CSV_PATH)
    accepted_peptides_df["top8_hla_mean"] = accepted_peptides_df.loc[:, SUPERTYPE_LIST].apply(
        mean_top8_binding_scores, axis=1
    )
    return accepted_peptides_df


def _load_hla_combinations() -> dict:
    """Loads the pre-computed HLA combination pickle file."""
    with open(HLA_COMBINATIONS_PICKLE, "rb") as fh:
        return pickle.load(fh)


def run_stage0() -> dict:
    """Loads and caches all datasets needed by the filtering pipeline.

    All three datasets are memoized: if a pickle cache already exists in
    ``MEMOIZATION_DIR/stage-0/``, it will be loaded from disk instead of
    re-computing.  Delete the cache files to force a fresh load.

    Returns:
        A dictionary with the following keys:

        - ``"accepted_peptides_df"`` (:class:`pandas.DataFrame`): One row per peptide with
          ``%Rank_EL`` scores for all 12 HLA supertypes and a computed
          ``top8_hla_mean`` column.

        - ``"df_dict"`` (dict): Per-seed DataFrames from the simulation CSV
          directory, keyed by filename stem.

        - ``"all_hla_combinations"`` (dict): Maps HLA combination tuples to
          their integer IDs (794 entries in the original dataset).

        - ``"threshold_8_hla_passing_peptides"`` (dict): Maps HLA combination
          IDs to lists of peptides that bind at least 8 HLA supertypes.

    Example::

        data = run_stage0()
        print("Peptides above threshold:", len(data["threshold_8_hla_passing_peptides"]))
    """
    import sys
    import glob

    memo_dir = os.path.join(MEMOIZATION_DIR, "stage-0")
    os.makedirs(memo_dir, exist_ok=True)

    # Source files for cache invalidation
    accepted_src = [ACCEPTED_PEPTIDES_CSV_PATH] if ACCEPTED_PEPTIDES_CSV_PATH else []
    hla_src = [HLA_COMBINATIONS_PICKLE] if HLA_COMBINATIONS_PICKLE else []
    sim_csvs = sorted(glob.glob(os.path.join(SIMULATION_CSV_DIR, "*.csv"))) if SIMULATION_CSV_DIR else []

    cache_path = os.path.join(memo_dir, "accepted_peptides_df.pickle")
    cached = os.path.exists(cache_path)
    print(f"[Sub-stage 0] Loading combined MCMC results from {ACCEPTED_PEPTIDES_CSV_PATH}...")
    if cached:
        # Check if cache is stale
        if accepted_src and os.path.exists(accepted_src[0]) and os.path.getmtime(accepted_src[0]) > os.path.getmtime(cache_path):
            print(f"[Sub-stage 0]   (cache stale — source file is newer, recomputing)")
        else:
            print(f"[Sub-stage 0]   (cached at {cache_path})")
    sys.stdout.flush()
    accepted_peptides_df = memoize_function(_load_accepted_peptides, cache_path, source_paths=accepted_src)
    print(f"[Sub-stage 0]   -> {len(accepted_peptides_df)} peptides, {len(accepted_peptides_df.columns)} columns")
    sys.stdout.flush()

    cache_path = os.path.join(memo_dir, "all_hla_combinations.pickle")
    cached = os.path.exists(cache_path)
    print(f"[Sub-stage 0] Loading HLA combination mapping from {HLA_COMBINATIONS_PICKLE}...")
    if cached:
        if hla_src and os.path.exists(hla_src[0]) and os.path.getmtime(hla_src[0]) > os.path.getmtime(cache_path):
            print(f"[Sub-stage 0]   (cache stale — source file is newer, recomputing)")
        else:
            print(f"[Sub-stage 0]   (cached)")
    sys.stdout.flush()
    all_hla_combinations = memoize_function(_load_hla_combinations, cache_path, source_paths=hla_src)
    print(f"[Sub-stage 0]   -> {len(all_hla_combinations)} unique HLA combinations")
    sys.stdout.flush()

    cache_path = os.path.join(memo_dir, "df_dict.pickle")
    cached = os.path.exists(cache_path)
    print(f"[Sub-stage 0] Loading per-seed simulation DataFrames from {SIMULATION_CSV_DIR}...")
    if cached:
        if sim_csvs and os.path.getmtime(sim_csvs[-1]) > os.path.getmtime(cache_path):
            print(f"[Sub-stage 0]   (cache stale — CSV files are newer, recomputing)")
        else:
            print(f"[Sub-stage 0]   (cached)")
    sys.stdout.flush()
    df_dict = memoize_function(
        lambda: create_dict_of_df(SIMULATION_CSV_DIR), cache_path,
        source_paths=sim_csvs,
    )
    print(f"[Sub-stage 0]   -> {len(df_dict)} seed files loaded")
    sys.stdout.flush()

    # threshold depends on both df_dict and hla_combinations — invalidate if either changed
    cache_path = os.path.join(memo_dir, "threshold_8_hla_passing_peptides.pickle")
    threshold_sources = accepted_src + hla_src + sim_csvs
    cached = os.path.exists(cache_path)
    print(f"[Sub-stage 0] Filtering peptides binding >={MIN_HLA_BINDING_COUNT} HLA supertypes...")
    if cached:
        stale = any(os.path.exists(s) and os.path.getmtime(s) > os.path.getmtime(cache_path) for s in threshold_sources)
        if stale:
            print(f"[Sub-stage 0]   (cache stale — source data is newer, recomputing)")
        else:
            print(f"[Sub-stage 0]   (cached)")
    sys.stdout.flush()
    threshold_8_hla_passing_peptides = memoize_function(
        lambda: get_peptides_by_hla_threshold(
            df_dict,
            min_hla_count=MIN_HLA_BINDING_COUNT,
            hla_combinations_map=all_hla_combinations,
        ),
        cache_path,
        source_paths=threshold_sources,
    )
    print(f"[Sub-stage 0]   -> {len(threshold_8_hla_passing_peptides)} HLA combinations passed threshold")
    sys.stdout.flush()

    return {
        "accepted_peptides_df": accepted_peptides_df,
        "df_dict": df_dict,
        "all_hla_combinations": all_hla_combinations,
        "threshold_8_hla_passing_peptides": threshold_8_hla_passing_peptides,
    }
