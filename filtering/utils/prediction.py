"""
utils/prediction.py — MHC binding prediction wrappers.

This module wraps all three MHC binding prediction tools used in stage 3:
  - netMHCpan 4.1  (send_to_prediction_as_is)
  - netMHCpan 4.0  (send_to_prediction_as_is_net_4)
  - MHCflurry      (send_to_mhcflurry)

It also contains the function that parses raw netMHCpan output into a
structured DataFrame (create_df_from_netmhcpan_output), originally from
pred_analysis.py.

All tool paths are resolved from filtering/config.py — no hardcoded paths.
"""
import math
import subprocess
from io import StringIO

import numpy as np
import pandas as pd

from filtering.config import MHC_DIR_PATH, NETMHCPAN_40_DIR_PATH, MEMOIZATION_DIR
from filtering.constants import SUPERTYPE_LIST, HLA_STR, HLA_FLURRY_LIST
from filtering.utils.memoize import memoize_function
import os


# ---------------------------------------------------------------------------
# NetMHCpan output parsing
# ---------------------------------------------------------------------------

def create_df_from_netmhcpan_output(
    df: pd.DataFrame,
    supertypes_list: list = SUPERTYPE_LIST,
) -> pd.DataFrame:
    """Processes raw netMHCpan output (as a DataFrame) into a feature-rich table.

    Expects ``df`` to have at minimum the columns ``MHC``, ``Peptide``, and
    ``%Rank_EL`` (the elution rank used as binding score).

    Args:
        df: Raw DataFrame read from netMHCpan stdout.
        supertypes_list: HLA types to include. Defaults to
            :data:`~filtering.constants.SUPERTYPE_LIST`.

    Returns:
        A DataFrame where each row is one peptide and columns are:
        - One column per HLA supertype with its ``%Rank_EL`` score.
        - ``WB``, ``SB``, ``NB``: counts of weak / strong / non-binders.
        - ``WB_delta``, ``SB_delta``, ``NB_delta``: deltas between rows.
        - ``sum_of_all_hla``: sum of all rank scores.
        - ``wb_id``, ``sb_id``, ``nb_id``, ``total_binders_id``: HLA lists.
        - ``total_binders``: WB + SB count.
    """
    supertypes = pd.Index(supertypes_list)

    filtered = df[df["MHC"].isin(supertypes)]
    pivoted = filtered.pivot(columns="MHC", values="%Rank_EL", index="Peptide")
    pivoted = pivoted.astype(float)

    # Binder category counts (thresholds: SB <= 0.5%, WB <= 2%, NB > 2%)
    pivoted["WB"] = pivoted[(0.5 < pivoted.loc[:, supertypes]) & (pivoted.loc[:, supertypes] <= 2)].count(axis=1)
    pivoted["SB"] = pivoted[pivoted.loc[:, supertypes] <= 0.5].count(axis=1)
    pivoted["NB"] = pivoted[pivoted.loc[:, supertypes] > 2].count(axis=1)

    pivoted["WB_delta"] = pd.Series([0] + list(np.round(np.diff(pivoted["WB"]), 5)))
    pivoted["NB_delta"] = pd.Series([0] + list(np.round(np.diff(pivoted["NB"]), 5)))
    pivoted["SB_delta"] = pd.Series([0] + list(np.round(np.diff(pivoted["SB"]), 5)))

    pivoted["sum_of_all_hla"] = pivoted.loc[:, supertypes].sum(axis=1)
    pivoted.reset_index(inplace=True)

    # Per-HLA binder classification lists
    pivoted["wb_id"] = pivoted[supertypes][(0.5 < pivoted[supertypes]) & (pivoted[supertypes] <= 2)].apply(
        lambda x: x.dropna().index.tolist(), axis=1
    )
    pivoted["sb_id"] = pivoted[supertypes][pivoted[supertypes] <= 0.5].apply(
        lambda x: x.dropna().index.tolist(), axis=1
    )
    pivoted["nb_id"] = pivoted[supertypes][pivoted[supertypes] > 2].apply(
        lambda x: x.dropna().index.tolist(), axis=1
    )
    pivoted["total_binders_id"] = pivoted["wb_id"] + pivoted["sb_id"]

    pivoted.fillna(0, inplace=True)
    pivoted["total_binders"] = pivoted["SB"] + pivoted["WB"]

    return pivoted


# ---------------------------------------------------------------------------
# netMHCpan 4.1 — batch FASTA prediction
# ---------------------------------------------------------------------------

def send_to_prediction_as_is(peptides_fasta_path: str) -> pd.DataFrame:
    """Runs netMHCpan 4.1 on a FASTA file and returns a binding score DataFrame.

    Results are cached in the stage-3 memoization subdirectory so that the
    expensive subprocess call is skipped on re-runs.

    Args:
        peptides_fasta_path: Absolute path to the input FASTA file.

    Returns:
        A pivoted DataFrame with one row per peptide and one column per HLA
        supertype containing ``%Rank_EL`` scores, plus a ``total_binders``
        column.
    """
    netmhcpan_exec = os.path.join(MHC_DIR_PATH, "netMHCpan")
    command = f"{netmhcpan_exec} -f {peptides_fasta_path} -l 9 -a {HLA_STR}"

    cache_path = os.path.join(MEMOIZATION_DIR, "stage-3", "netMHCpan_4.1-prediction.pickle")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    out_object = memoize_function(
        lambda: subprocess.run(command, shell=True, text=True, check=True, capture_output=True),
        cache_path,
    )

    output_string = StringIO(out_object.stdout)
    df = pd.read_csv(output_string, sep=r"\s+", comment="#", header=2, usecols=[1, 2, 12])
    return _pivot_netmhcpan_41(df)


def _pivot_netmhcpan_41(df: pd.DataFrame) -> pd.DataFrame:
    """Pivots a raw netMHCpan 4.1 output DataFrame to peptide × HLA format."""
    supertypes = pd.Index(SUPERTYPE_LIST)
    df = df[df["MHC"].isin(supertypes)]
    df = df.pivot(columns="MHC", values="%Rank_EL", index="Peptide")
    df = df.astype(float)
    df["total_binders"] = df[df.loc[:, supertypes] <= 2].count(axis=1)
    return df


# ---------------------------------------------------------------------------
# netMHCpan 4.0 — batch FASTA prediction
# ---------------------------------------------------------------------------

def send_to_prediction_as_is_net_4(peptides_fasta_path: str) -> pd.DataFrame:
    """Runs netMHCpan 4.0 on a FASTA file and returns a binding score DataFrame.

    netMHCpan 4.0 uses a different output column name (``%Rank`` instead of
    ``%Rank_EL``) and a different HLA notation — both are handled here.

    Args:
        peptides_fasta_path: Absolute path to the input FASTA file.

    Returns:
        A pivoted DataFrame with one row per peptide and one column per HLA
        supertype containing ``%Rank`` scores.
    """
    netmhcpan_exec = os.path.join(NETMHCPAN_40_DIR_PATH, "netMHCpan")
    command = f"{netmhcpan_exec} -f {peptides_fasta_path} -l 9 -a {HLA_STR}"

    cache_path = os.path.join(MEMOIZATION_DIR, "stage-3", "netMHCpan_4.0-prediction.pickle")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    out_object = memoize_function(
        lambda: subprocess.run(command, shell=True, text=True, check=True, capture_output=True),
        cache_path,
    )

    output_string = StringIO(out_object.stdout)
    df = pd.read_csv(output_string, sep=r"\s+", comment="#", header=2, usecols=[1, 2, 12])

    supertypes = SUPERTYPE_LIST
    df = df[df["HLA"].isin(supertypes)]
    df.set_index("Peptide", inplace=True)
    df = df.pivot(columns="HLA", values="%Rank")
    return df


# ---------------------------------------------------------------------------
# MHCflurry — batch peptide prediction
# ---------------------------------------------------------------------------

def send_to_mhcflurry(peptides: list) -> pd.DataFrame:
    """Runs MHCflurry on a list of peptides and returns percentile rank scores.

    Predicts binding affinity (as percentile rank) for all 12 HLA supertypes
    in :data:`~filtering.constants.HLA_FLURRY_LIST` using MHCflurry's
    ``Class1AffinityPredictor``.

    Args:
        peptides: List of peptide sequence strings.

    Returns:
        A DataFrame indexed by peptide sequence with one column per HLA
        type (in MHCflurry notation) containing ``prediction_percentile``
        values.

    Note:
        Requires the ``mhcflurry`` package to be installed and a downloaded
        predictor (run ``mhcflurry-downloads fetch`` if needed).
    """
    from mhcflurry import Class1AffinityPredictor  # type: ignore

    predictor = Class1AffinityPredictor.load()
    appended_data = []

    for peptide in peptides:
        data = predictor.predict_to_dataframe(
            alleles=HLA_FLURRY_LIST,
            peptides=[peptide] * len(HLA_FLURRY_LIST),
        )
        appended_data.append(data)

    combined = pd.concat(appended_data)
    combined.set_index("peptide", inplace=True)

    # Restructure so each HLA type is a column
    result = pd.DataFrame()
    for hla in HLA_FLURRY_LIST:
        result[hla] = combined["prediction_percentile"][combined["allele"] == hla]

    return result
