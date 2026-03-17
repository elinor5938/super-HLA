import os
import argparse
import sys
from simulation import simulation_process
from config import OUTPUT_DIR_PATH

def main_random_peptide(seed: int, accepted_count: int, output_dir: str):
    """Run simulation with random peptide generation."""
    print(f"Starting simulation with random peptide (Seed: {seed}, Accepted target: {accepted_count})")
    df_name = simulation_process(seed, number_of_accepted_peptides=accepted_count)
    
    out_path = os.path.join(output_dir, f"{seed}.csv")
    df_name.to_csv(out_path, index=False)
    print(f"Results successfully saved to: {out_path}")
    return df_name

def main_external_peptide_list(seed: int, fasta_path: str, accepted_count: int, output_dir: str):
    """Run simulation for a list of peptides provided via FASTA file."""
    if not os.path.isfile(fasta_path):
        print(f"Error: FASTA file not found at {fasta_path}")
        sys.exit(1)
        
    print(f"Parsing FASTA file at {fasta_path}...")
    with open(fasta_path, "r") as f:
        peptides_list = [line.strip() for line in f.read().splitlines() if line.strip() and not line.startswith(">")]
        
    if not peptides_list:
        print("No valid peptides found in the file.")
        sys.exit(1)
        
    for i, peptide in enumerate(peptides_list, start=1):
        print(f"[{i}/{len(peptides_list)}] Running simulation for peptide: {peptide}")
        df_name = simulation_process(seed, peptide, accepted_count)
        
        out_path = os.path.join(output_dir, f"{i}_{seed}_{peptide}.csv")
        df_name.to_csv(out_path, index=False)
        print(f"Saved: {out_path}")
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filtering Algorithm Simulation Workflow")
    
    parser.add_argument("--seed", type=int, required=True, help="Random seed for simulation and mutations")
    parser.add_argument("--mode", choices=["random", "external"], default="random", help="Simulation mode: random generation or from fasta file")
    parser.add_argument("--fasta", type=str, help="Path to external peptides fasta file (required if mode is 'external')")
    parser.add_argument("--accepted", type=int, default=2, help="Number of accepted peptides to reach before stopping")
    parser.add_argument("--output", type=str, default=OUTPUT_DIR_PATH, help="Directory to save the resulting CSV files")

    args = parser.parse_args()
    
    # Check output dir
    os.makedirs(args.output, exist_ok=True)
    
    if args.mode == "random":
        main_random_peptide(args.seed, args.accepted, args.output)
    elif args.mode == "external":
        if not args.fasta:
            print("Error: --fasta argument is required when mode is 'external'")
            sys.exit(1)
        main_external_peptide_list(args.seed, args.fasta, args.accepted, args.output)
