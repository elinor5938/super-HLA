"""
prepare_filtering_data.py — Build filtering-stage inputs from MCMC output CSVs.

After running the MCMC simulation (one or more seeds), this script:
  1. Combines all per-seed CSVs into a single ``robust_df`` CSV.
  2. Builds the HLA combination mapping pickle.
  3. Updates .env with the correct paths.

Usage (from project root):
    python prepare_filtering_data.py [--mcmc-output-dir mcmc/output]

This bridges the gap between the MCMC stage output and the filtering stage
input, so you don't need to manually construct the intermediate files.
"""
import argparse
import os
import pickle
import sys

import pandas as pd

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
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

    # ---- Step 1: Combine all CSVs into robust_df ----
    all_dfs = []
    for f in sorted(csv_files):
        df = pd.read_csv(os.path.join(mcmc_dir, f), low_memory=False)
        # Keep only MCMC-accepted rows (True boolean or "True" string)
        accepted = df[
            (df["probabilty_res_MCMC"] == True) |  # noqa: E712
            (df["probabilty_res_MCMC"] == "True")
        ].copy()
        accepted = accepted.drop_duplicates(subset="Peptide", keep="first")
        all_dfs.append(accepted)
        print(f"  {f}: {len(df)} total rows, {len(accepted)} accepted peptides")

    robust_df = pd.concat(all_dfs, ignore_index=True)
    robust_df = robust_df.drop_duplicates(subset="Peptide", keep="first")
    print(f"\nCombined robust_df: {len(robust_df)} unique accepted peptides")

    os.makedirs(data_dir, exist_ok=True)
    robust_csv_path = os.path.join(data_dir, "robust_df.csv")
    robust_df.to_csv(robust_csv_path, index=False)
    print(f"Saved: {robust_csv_path}")

    # ---- Step 2: Build HLA combination mapping ----
    hla_combinations = {}
    combo_id = 0

    for _, row in robust_df.iterrows():
        binding_hlas = []
        for hla in SUPERTYPE_LIST:
            if hla in robust_df.columns and row[hla] < 2:
                binding_hlas.append(hla)
        binding_hlas.sort()
        combo_tuple = tuple(binding_hlas)

        if len(combo_tuple) >= MIN_HLA_BINDING_COUNT and combo_tuple not in hla_combinations:
            hla_combinations[combo_tuple] = combo_id
            combo_id += 1

    pickle_path = os.path.join(data_dir, "all_hla_combinations.pickle")
    with open(pickle_path, "wb") as fh:
        pickle.dump(hla_combinations, fh)
    print(f"Saved: {pickle_path} ({len(hla_combinations)} HLA combinations with >={MIN_HLA_BINDING_COUNT} binders)")

    # ---- Step 3: Update .env with correct paths ----
    env_path = os.path.join(PROJECT_ROOT, ".env")
    env_updates = {
        "ROBUST_DF_CSV_PATH": robust_csv_path,
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
    print(f"\nUpdated .env with filtering paths.")

    print(f"\nDone! You can now run the filtering pipeline:")
    print(f"  python -m filtering.main")


if __name__ == "__main__":
    main()
