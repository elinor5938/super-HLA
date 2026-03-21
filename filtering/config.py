import os

# ---------------------------------------------------------------------------
# Load .env from the project root (same pattern as mcmc/config.py)
# ---------------------------------------------------------------------------

def _load_env(env_path: str) -> None:
    """Reads a .env file and sets variables into os.environ (no-op if absent)."""
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()


# Base directory = project root (two levels up from this file)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_load_env(os.path.join(BASE_DIR, ".env"))

# ---------------------------------------------------------------------------
# Input data paths — set in .env, no defaults (data is user-specific)
# ---------------------------------------------------------------------------

ROBUST_DF_CSV_PATH = os.environ.get("ROBUST_DF_CSV_PATH", "")
"""Path to the all_data_frames_sims_october.csv produced by the MCMC pipeline."""

SIMULATION_CSV_DIR = os.environ.get("SIMULATION_CSV_DIR", "")
"""Directory containing per-seed simulation CSV files (e.g. semi-strict-october-40000/)."""

HLA_COMBINATIONS_PICKLE = os.environ.get("HLA_COMBINATIONS_PICKLE", "")
"""Path to the all_hla_cominations.pickle file."""

# ---------------------------------------------------------------------------
# Memoization root — all stage-level pickle caches live under subdirectories
# ---------------------------------------------------------------------------

MEMOIZATION_DIR = os.environ.get("MEMOIZATION_DIR", "")
"""Root directory for pickle-based memoization. Subdirs per stage are created automatically."""

# ---------------------------------------------------------------------------
# CD-HIT file directories
# ---------------------------------------------------------------------------

CDHIT_CLUSTER1_INPUT_DIR = os.environ.get("CDHIT_CLUSTER1_INPUT_DIR", "")
"""Directory for FASTA input files of the first CD-HIT clustering round."""

CDHIT_CLUSTER1_OUTPUT_DIR = os.environ.get("CDHIT_CLUSTER1_OUTPUT_DIR", "")
"""Directory for CD-HIT output files of the first clustering round."""

CDHIT_CLUSTER2_INPUT_DIR = os.environ.get("CDHIT_CLUSTER2_INPUT_DIR", "")
"""Directory for FASTA input files of the second CD-HIT clustering round."""

CDHIT_CLUSTER2_OUTPUT_DIR = os.environ.get("CDHIT_CLUSTER2_OUTPUT_DIR", "")
"""Directory for CD-HIT output files of the second clustering round."""

# ---------------------------------------------------------------------------
# Stage output directories
# ---------------------------------------------------------------------------

STAGE2_OUTPUT_DIR = os.environ.get("STAGE2_OUTPUT_DIR", "")
"""Directory where stage 2 FASTA and CSV outputs are saved."""

CANDIDATE_PEPTIDES_FASTA = os.environ.get(
    "CANDIDATE_PEPTIDES_FASTA",
    os.path.join(BASE_DIR, "data", "stage2-files", "candidate_peptides.fasta"),
)
"""Path to the candidate peptides FASTA written by stage 3 and read by stage 4."""

# ---------------------------------------------------------------------------
# MHC prediction tool path (shared with mcmc — reads the same env var)
# ---------------------------------------------------------------------------

MHC_DIR_PATH = os.environ.get("MHC_DIR_PATH", "")
"""Path to the netMHCpan directory (e.g. /path/to/netMHCpan-4.1/)."""

NETMHCPAN_40_DIR_PATH = os.environ.get("NETMHCPAN_40_DIR_PATH", "")
"""Path to the netMHCpan 4.0 directory (used in stage 3 for cross-validation)."""
