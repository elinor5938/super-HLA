"""
stage0_load_data.py — Load and cache the three core datasets for the filtering pipeline.

This stage is responsible for loading the raw data produced by the MCMC simulation
and preparing it for the CD-HIT clustering steps that follow.

Inputs (configured via .env):
  - ROBUST_DF_CSV_PATH      : CSV with all MCMC simulation results combined.
  - SIMULATION_CSV_DIR      : Directory of per-seed simulation output CSVs.
  - HLA_COMBINATIONS_PICKLE : Pickle mapping HLA combination tuples → IDs.
  - MEMOIZATION_DIR         : Root folder for pickle caches.

Output:
  A dictionary with the following keys, returned by ``run_stage0()``:
  - ``robust_df``                      : The main simulation DataFrame.
  - ``df_dict``                         : Per-seed simulation DataFrames.
  - ``all_hla_combinations``            : Mapping of HLA combos → IDs.
  - ``threshold_8_hla_passing_peptides``: Peptides passing the 8-HLA threshold.
"""
import os
import pickle

import pandas as pd

from filtering.config import (
    ROBUST_DF_CSV_PATH,
    SIMULATION_CSV_DIR,
    HLA_COMBINATIONS_PICKLE,
    MEMOIZATION_DIR,
)
from filtering.constants import SUPERTYPE_LIST, MIN_HLA_BINDING_COUNT
from filtering.utils.memoize import memoize_function
from filtering.utils.scoring import (
    one_side_trimmed_min,
    create_dict_of_df,
    get_peptides_by_hla_threshold,
)


def _load_robust_df() -> pd.DataFrame:
    """Loads the combined MCMC results CSV and computes the one_side_mean score."""
    robust_df = pd.read_csv(ROBUST_DF_CSV_PATH)
    robust_df["one_side_mean"] = robust_df.loc[:, SUPERTYPE_LIST].apply(
        one_side_trimmed_min, axis=1
    )
    return robust_df


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

        - ``"robust_df"`` (:class:`pandas.DataFrame`): One row per peptide with
          ``%Rank_EL`` scores for all 12 HLA supertypes and a computed
          ``one_side_mean`` column.

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
    memo_dir = os.path.join(MEMOIZATION_DIR, "stage-0")
    os.makedirs(memo_dir, exist_ok=True)

    robust_df = memoize_function(
        _load_robust_df,
        os.path.join(memo_dir, "robust_df.pickle"),
    )

    all_hla_combinations = memoize_function(
        _load_hla_combinations,
        os.path.join(memo_dir, "all_hla_combinations.pickle"),
    )

    df_dict = memoize_function(
        lambda: create_dict_of_df(SIMULATION_CSV_DIR),
        os.path.join(memo_dir, "df_dict.pickle"),
    )

    threshold_8_hla_passing_peptides = memoize_function(
        lambda: get_peptides_by_hla_threshold(
            df_dict,
            min_hla_count=MIN_HLA_BINDING_COUNT,
            hla_combinations_map=all_hla_combinations,
        ),
        os.path.join(memo_dir, "threshold_8_hla_passing_peptides.pickle"),
    )

    return {
        "robust_df": robust_df,
        "df_dict": df_dict,
        "all_hla_combinations": all_hla_combinations,
        "threshold_8_hla_passing_peptides": threshold_8_hla_passing_peptides,
    }
