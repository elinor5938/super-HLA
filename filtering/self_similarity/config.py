"""
filtering/filtering/self_similarity/config.py — Load .env variables for the self-similarity stage.
"""
import os
import sys

# 3 levels up: filtering/filtering/self_similarity/config.py → filtering/self_similarity → filtering → project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Load .env (same as other modules)
# ---------------------------------------------------------------------------
_env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the original human proteome FASTA (full-length proteins).
# This is the source from which 9-mers are generated.
HUMAN_PROTEOME_FASTA = os.environ.get("HUMAN_PROTEOME_FASTA", "")

# Path to the pre-chopped 9-mer FASTA (can be ~16 GB).
# If this already exists, the chopping step is skipped.
HUMAN_9MERS_FASTA = os.environ.get("HUMAN_9MERS_FASTA", "")

# Directory for chunked 9-mer FASTA files (for parallel needle runs).
NEEDLE_CHUNKS_DIR = os.environ.get(
    "NEEDLE_CHUNKS_DIR",
    os.path.join(PROJECT_ROOT, "data", "needle", "chunks"),
)

# Directory where needle output text files are written.
NEEDLE_OUTPUT_DIR = os.environ.get(
    "NEEDLE_OUTPUT_DIR",
    os.path.join(PROJECT_ROOT, "data", "needle", "output"),
)

# Path to the parsed alignment results JSON.
ALIGNMENT_RESULTS_JSON = os.environ.get(
    "ALIGNMENT_RESULTS_JSON",
    os.path.join(PROJECT_ROOT, "data", "needle", "alignment_results.json"),
)

# Input FASTA of candidate peptides (output of stage 3 filtering pipeline).
CANDIDATE_PEPTIDES_FASTA = os.environ.get(
    "CANDIDATE_PEPTIDES_FASTA",
    os.path.join(PROJECT_ROOT, "data", "stage2-files", "candidate_peptides.fasta"),
)

# Self-similarity thresholds (out of 9 for 9-mer peptides)
SIMILARITY_THRESHOLD = int(os.environ.get("SELF_SIM_SIMILARITY_THRESHOLD", "8"))
IDENTITY_THRESHOLD = int(os.environ.get("SELF_SIM_IDENTITY_THRESHOLD", "7"))

# Number of parallel needle worker processes
NEEDLE_WORKERS = int(os.environ.get("NEEDLE_WORKERS", str(os.cpu_count() or 4)))
