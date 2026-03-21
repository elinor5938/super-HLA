"""
filtering/prepare_data.py — Build filtering-stage inputs from MCMC output CSVs.

After running the MCMC simulation (one or more seeds), this script:
  1. Combines all per-seed CSVs into a single ``accepted_peptides_df`` CSV.
  2. Builds the HLA combination mapping pickle.
  3. Updates .env with the correct paths.

Usage (from project root):
    python -m filtering.prepare_data [--mcmc-output-dir mcmc/output]

This bridges the gap between the MCMC stage output and the filtering stage
input, so you don't need to manually construct the intermediate files.
"""
import argparse
import os
import pickle
import sys

import pandas as pd

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from filtering.constants import SUPERTYPE_LIST, MIN_HLA_BINDING_COUNT


def main():
    parser = argparse.ArgumentParser(description="Prepare filtering data from MCMC output")
    parser.add_argument(
        "--mcmc-output-dir",
        default=os.path.join(PROJECT_ROOT, "mcmc", "output"),
        help="Directory containing per-seed MCMC output CSVs (default: mcmc/output/)",
    )
    parser.add_argument(
        "--data-dir",
        default=os.path.join(PROJECT_ROOT, "data"),
        help="Directory to write prepared data files (default: data/)",
    )
    args = parser.parse_args()

    mcmc_dir = args.mcmc_output_dir
    data_dir = args.data_dir

    if not os.path.isdir(mcmc_dir):
        print(f"Error: MCMC output directory not found: {mcmc_dir}")
        sys.exit(1)

    csv_files = [f for f in os.listdir(mcmc_dir) if f.endswith(".csv")]
    if not csv_files:
        print(f"Error: No CSV files found in {mcmc_dir}")
        sys.exit(1)

    print(f"Found {len(csv_files)} MCMC output CSV(s) in {mcmc_dir}")

    # ---- Step 1: Combine all CSVs into accepted_peptides_df ----
    print(f"\n[Step 1/3] Combining MCMC output CSVs into a single dataset...")
    all_dfs = []
    for i, f in enumerate(sorted(csv_files), 1):
        print(f"  Loading CSV {i}/{len(csv_files)}: {f}...")
        df = pd.read_csv(os.path.join(mcmc_dir, f), low_memory=False)
        # Keep only MCMC-accepted rows (True boolean or "True" string)
        accepted = df[
            (df["mcmc_accepted"] == True) |  # noqa: E712
            (df["mcmc_accepted"] == "True")
        ].copy()
        accepted = accepted.drop_duplicates(subset="Peptide", keep="first")
        all_dfs.append(accepted)
        print(f"    {len(df)} total rows, {len(accepted)} accepted peptides")

    accepted_peptides_df = pd.concat(all_dfs, ignore_index=True)
    accepted_peptides_df = accepted_peptides_df.drop_duplicates(subset="Peptide", keep="first")
    print(f"  Combined accepted_peptides_df: {len(accepted_peptides_df)} unique accepted peptides")

    os.makedirs(data_dir, exist_ok=True)
    accepted_csv_path = os.path.join(data_dir, "accepted_peptides.csv")
    accepted_peptides_df.to_csv(accepted_csv_path, index=False)
    print(f"  Saved: {accepted_csv_path}")

    # ---- Step 2: Build HLA combination mapping ----
    print(f"\n[Step 2/3] Building HLA combination mapping...")
    hla_combinations = {}
    combo_id = 0

    for _, row in accepted_peptides_df.iterrows():
        binding_hlas = []
        for hla in SUPERTYPE_LIST:
            if hla in accepted_peptides_df.columns and row[hla] < 2:
                binding_hlas.append(hla)
        binding_hlas.sort()
        combo_tuple = tuple(binding_hlas)

        if len(combo_tuple) >= MIN_HLA_BINDING_COUNT and combo_tuple not in hla_combinations:
            hla_combinations[combo_tuple] = combo_id
            combo_id += 1

    pickle_path = os.path.join(data_dir, "all_hla_combinations.pickle")
    with open(pickle_path, "wb") as fh:
        pickle.dump(hla_combinations, fh)
    print(f"  Saved: {pickle_path} ({len(hla_combinations)} HLA combinations with >={MIN_HLA_BINDING_COUNT} binders)")

    # ---- Step 3: Update .env with correct paths ----
    print(f"\n[Step 3/3] Updating .env configuration...")
    env_path = os.path.join(PROJECT_ROOT, ".env")
    env_updates = {
        "ACCEPTED_PEPTIDES_CSV_PATH": accepted_csv_path,
        "SIMULATION_CSV_DIR": mcmc_dir,
        "HLA_COMBINATIONS_PICKLE": pickle_path,
    }

    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            env_lines = f.readlines()
    else:
        env_lines = []

    for key, value in env_updates.items():
        updated = False
        for i, line in enumerate(env_lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"# {key}="):
                env_lines[i] = f"{key}={value}\n"
                updated = True
                break
        if not updated:
            env_lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(env_lines)
    print(f"  Updated {env_path} with:")
    for key, value in env_updates.items():
        print(f"    {key}={value}")

    print(f"\nDone! You can now run the filtering pipeline:")
    print(f"  python -m filtering.main")


if __name__ == "__main__":
    main()
