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
import re
import subprocess
from io import StringIO

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
# netMHCpan (primary installation) — batch FASTA prediction
# ---------------------------------------------------------------------------

def send_to_prediction_as_is(peptides_fasta_path: str) -> pd.DataFrame:
    """Runs the primary netMHCpan installation on a FASTA file and returns binding scores.

    Uses whichever netMHCpan version is configured via MHC_DIR_PATH (supports
    4.1 and 4.2+ output formats). Results are cached in the stage-3 memoization
    subdirectory so that the expensive subprocess call is skipped on re-runs.

    Args:
        peptides_fasta_path: Absolute path to the input FASTA file.

    Returns:
        A pivoted DataFrame with one row per peptide and one column per HLA
        supertype containing ``%Rank_EL`` scores, plus a ``total_binders``
        column.
    """
    netmhcpan_exec = os.path.join(MHC_DIR_PATH, "netMHCpan")
    command = f"{netmhcpan_exec} -f {peptides_fasta_path} -l 9 -a {HLA_STR}"

    cache_path = os.path.join(MEMOIZATION_DIR, "stage-3", "netMHCpan-primary-prediction.pickle")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    out_object = memoize_function(
        lambda: subprocess.run(command, shell=True, text=True, check=True, capture_output=True),
        cache_path,
    )

    df = _parse_netmhcpan_output(out_object.stdout)
    return _pivot_netmhcpan(df)


def _parse_netmhcpan_output(stdout: str) -> pd.DataFrame:
    """Parses netMHCpan stdout into a DataFrame with MHC, Peptide, %Rank_EL columns.

    Supports 4.0, 4.1, and 4.2+ output formats. Correctly handles the ``<= SB``
    and ``<= WB`` binding level markers that break naive whitespace-based parsing.
    """
    rows = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-") or stripped.startswith("Protein") or stripped.startswith("Pos"):
            continue
        # Remove binding level markers that break \s+ parsing
        cleaned = re.sub(r'\s*<=\s*(SB|WB)\s*$', '', stripped)
        tokens = cleaned.split()
        if len(tokens) >= 13:
            mhc = tokens[1]
            peptide = tokens[2]
            rank = tokens[12]  # %Rank or %Rank_EL is always at position 12
            rows.append({"MHC": mhc, "Peptide": peptide, "%Rank_EL": float(rank)})

    if not rows:
        raise RuntimeError("Failed to parse any data rows from netMHCpan output")

    return pd.DataFrame(rows)


def _pivot_netmhcpan(df: pd.DataFrame) -> pd.DataFrame:
    """Pivots a raw netMHCpan output DataFrame to peptide x HLA format."""
    supertypes = pd.Index(SUPERTYPE_LIST)
    df = df[df["MHC"].isin(supertypes)]
    df = df.pivot(columns="MHC", values="%Rank_EL", index="Peptide")
    df = df.astype(float)
    df["total_binders"] = df[df.loc[:, supertypes] <= 2].count(axis=1)
    return df


# ---------------------------------------------------------------------------
# netMHCpan 4.0 — batch FASTA prediction
# ---------------------------------------------------------------------------

def _resolve_netmhcpan_executable(install_dir: str) -> str:
    """Finds the correct netMHCpan executable for the current platform.

    Looks for platform-specific wrappers in order of preference:

      1. ``netMHCpan_docker``       — runs via Docker (macOS/Linux)
      2. ``netMHCpan_darwin_arm64`` — runs via Rosetta (macOS arm64)
      3. ``netMHCpan_wsl.bat``      — runs via WSL (Windows)
      4. ``netMHCpan_docker.bat``   — runs via Docker (Windows)
      5. ``netMHCpan``             — native tcsh wrapper (default)
    """
    import sys as _sys
    for wrapper_name in ("netMHCpan_docker", "netMHCpan_wsl", "netMHCpan_darwin_arm64"):
        wrapper = os.path.join(install_dir, wrapper_name)
        if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
            return wrapper
    # Windows-specific wrappers
    if _sys.platform == "win32":
        for wrapper_name in ("netMHCpan_wsl.bat", "netMHCpan_docker.bat"):
            wrapper = os.path.join(install_dir, wrapper_name)
            if os.path.isfile(wrapper):
                return wrapper
    return os.path.join(install_dir, "netMHCpan")


def send_to_prediction_as_is_net_4(peptides_fasta_path: str) -> pd.DataFrame:
    """Runs a secondary netMHCpan installation on a FASTA file for cross-validation.

    Uses whichever netMHCpan version is at ``NETMHCPAN_40_DIR_PATH`` (supports
    4.0, 4.1, and 4.2 output formats).

    Args:
        peptides_fasta_path: Absolute path to the input FASTA file.

    Returns:
        A pivoted DataFrame with one row per peptide and one column per HLA
        supertype containing binding rank scores.

    Raises:
        FileNotFoundError: If ``NETMHCPAN_40_DIR_PATH`` is not configured.
    """
    if not NETMHCPAN_40_DIR_PATH:
        raise FileNotFoundError(
            "Secondary netMHCpan path not configured. Set NETMHCPAN_40_DIR_PATH in .env."
        )

    netmhcpan_exec = _resolve_netmhcpan_executable(NETMHCPAN_40_DIR_PATH)
    command = f"{netmhcpan_exec} -f {peptides_fasta_path} -l 9 -a {HLA_STR}"

    cache_path = os.path.join(MEMOIZATION_DIR, "stage-3", "netMHCpan-secondary-prediction.pickle")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    out_object = memoize_function(
        lambda: subprocess.run(command, shell=True, text=True, check=True, capture_output=True),
        cache_path,
    )

    df = _parse_netmhcpan_output(out_object.stdout)
    return _pivot_netmhcpan(df)


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
