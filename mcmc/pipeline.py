import os
import random
import re
import subprocess

import numpy as np
import pandas as pd

from config import INPUT_DIR_PATH, HLA_STR, NETMHCPAN_EXECUTABLE
from analysis import create_df_from_netmhcpan_output


def _parse_netmhcpan_stdout(stdout_string: str, stderr_string: str = "") -> pd.DataFrame:
    """Parses netMHCpan stdout into a DataFrame with MHC, Peptide, %Rank_EL columns.

    Handles 4.1 output format. Correctly handles the `<= SB`
    and `<= WB` binding level markers that break naive whitespace-based parsing.
    """
    rows = []
    for line in stdout_string.splitlines():
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
        import platform
        # Build a detailed diagnostic message
        stdout_preview = stdout_string[:2000] if stdout_string else "(empty)"
        stderr_preview = stderr_string[:1000] if stderr_string else "(empty)"
        total_lines = len(stdout_string.splitlines()) if stdout_string else 0
        raise RuntimeError(
            f"Failed to parse any data rows from netMHCpan output.\n"
            f"\n"
            f"--- Diagnostic info ---\n"
            f"Platform:       {platform.system()} {platform.machine()}\n"
            f"Executable:     {NETMHCPAN_EXECUTABLE}\n"
            f"Stdout lines:   {total_lines}\n"
            f"Stderr preview: {stderr_preview}\n"
            f"Stdout preview:\n{stdout_preview}\n"
            f"--- End diagnostic ---"
        )

    return pd.DataFrame(rows)


# Base amino acids list used across the pipeline
AMINO_ACID_LIST = ["A", "R", "N", "D", "C", "E", "Q", "G", "H", "I", "L", "K", "M", "F", "P", "S", "T", "W", "Y", "V"]

def send_pep_to_prediction(peptide: str, seed: int) -> pd.DataFrame:
    """Gets a peptide and seed, sends the peptide to NetMHCpan, and returns the analyzed df."""
    input_file = os.path.join(INPUT_DIR_PATH, f"peptides_for_pred_{seed}.txt")
    
    with open(input_file, 'w+') as f:
        f.write(peptide + "\n")
        
    command = [
        NETMHCPAN_EXECUTABLE,
        "-p", input_file,
        "-l", "9",
        "-a", HLA_STR
    ]
    
    try:
        out_object = subprocess.run(command, text=True, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        import platform
        raise RuntimeError(
            f"netMHCpan process exited with code {e.returncode}.\n"
            f"\n"
            f"--- Diagnostic info ---\n"
            f"Platform:   {platform.system()} {platform.machine()}\n"
            f"Executable: {NETMHCPAN_EXECUTABLE}\n"
            f"Command:    {' '.join(command)}\n"
            f"Stderr:     {(e.stderr or '(empty)')[:1000]}\n"
            f"Stdout:     {(e.stdout or '(empty)')[:1000]}\n"
            f"--- End diagnostic ---"
        ) from e
    
    stdout_string = out_object.stdout
    stderr_string = out_object.stderr or ""
    if "no binaries found" in stdout_string or len(stdout_string.splitlines()) < 3:
        raise RuntimeError(
            f"netMHCpan execution failed or returned invalid output.\n"
            f"Executable: {NETMHCPAN_EXECUTABLE}\n"
            f"Command: {' '.join(command)}\n"
            f"Stdout:\n{stdout_string.strip()}\n"
            f"Stderr:\n{stderr_string.strip()}"
        )

    df = _parse_netmhcpan_stdout(stdout_string, stderr_string)
    
    full_df = create_df_from_netmhcpan_output(df)
    return full_df


def first_pep_init(peptide: str, seed: int) -> pd.DataFrame:
    """Gets a peptide and calculates the first prediction, returning df with initial tracking initialized."""
    first_pep_df = send_pep_to_prediction(peptide, seed)
    
    # Setting initial status for tracking columns
    first_pep_df["mcmc_accepted"] = ["First"]
    first_pep_df["acceptance_probability"] = ["First"]
    first_pep_df["score_delta"] = ["First"]
    first_pep_df["position_changed"] = ["no change"]
    first_pep_df["former_AA"] = ["no change"]
    first_pep_df["new_AA"] = ["no change"]
    
    return first_pep_df


def peptide_creator(length: int) -> str:
    """Generates a random peptide of the desired length."""
    return "".join(random.choice(AMINO_ACID_LIST) for _ in range(length))


def mutation_creator(peptide: str) -> tuple:
    """Randomly mutates exactly one amino acid residue in the peptide, ensuring the new base is different from the old."""
    index = random.choice(range(len(peptide)))
    old_residue = peptide[index]
    
    random_amino_acid = random.choice(AMINO_ACID_LIST)
    while old_residue == random_amino_acid:
        random_amino_acid = random.choice(AMINO_ACID_LIST)
        
    mutated_peptide = "".join((peptide[:index], random_amino_acid, peptide[index + 1:]))
    position = index + 1  # 1-indexed for logging Output
    
    return mutated_peptide, position, old_residue, random_amino_acid


def check_delta(df: pd.DataFrame, probability_fn, col_contains_data: str, last_true_val=None):
    """
    Checks the difference (delta) against an acceptance probability mapping, 
    and applies a simulated annealing / MCMC style random toss to accept/reject.
    """
    index = df.shape[0] - 1
    
    # Calculate difference
    if df.shape[0] == 2:
        # First transition delta
        delta = float(np.diff(df.tail(2)[col_contains_data])[0])
    else:
        current_val = df[col_contains_data].tail(1).values[0]
        if last_true_val is not None:
            delta = current_val - last_true_val
        else:
            delta = 0  # Fallback if no last true value found
            
    # Use probability function
    prob_res = round(probability_fn(delta), 5)
    random_toss = random.random()
    acceptance_flag = random_toss <= prob_res
    
    # Update df
    df.at[index, "mcmc_accepted"] = acceptance_flag
    df.at[index, "score_delta"] = delta
    df.at[index, "acceptance_probability"] = prob_res
    
    return df, acceptance_flag
