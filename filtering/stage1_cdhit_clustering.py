"""
stage1_cdhit_clustering.py — Two-round CD-HIT clustering to select representative peptides.

This stage reduces the ~471 initial HLA-combination peptide sets down to a
compact set of representative (consensus) sequences using two rounds of
sequence similarity clustering with the CD-HIT tool.

Round 1 — per-combination clustering:
  Each HLA combination's peptide list is clustered independently at 60%
  similarity.  The best-scoring (lowest top8_hla_mean) peptide from each
  cluster that does not have P/D/E at position 4 is chosen as the consensus.

Round 2 — global re-clustering:
  All first-round consensus peptides (from all HLA combinations) are pooled
  and clustered again at 60% similarity.  A second consensus selection gives
  the final representative set (~55 k → ~8.4 k peptides in the original data).

Inputs:
  - stage0 data dict (output of stage0_load_data.run_stage0)
  - CD-HIT directory paths configured in .env

Output of run_stage1():
  - ``consensus_peptides_round2`` (list): Final list of representative peptides.
  - ``consensus_df_round2`` (DataFrame): Full cluster + score table for round 2.
"""
import os
import shutil
import subprocess
import sys

from filtering.config import (
    CDHIT_CLUSTER1_INPUT_DIR,
    CDHIT_CLUSTER1_OUTPUT_DIR,
    CDHIT_CLUSTER2_INPUT_DIR,
    CDHIT_CLUSTER2_OUTPUT_DIR,
    MEMOIZATION_DIR,
)
from filtering.constants import CDHIT_SIMILARITY_THRESHOLD
from filtering.utils.fasta import write_to_fasta
from filtering.utils.clustering import parse_cdhit_clusters
from filtering.utils.scoring import select_cluster_consensus
from filtering.utils.memoize import memoize_function


def _run_cdhit(
    peptide_sequences: list,
    similarity_threshold: int,
    combination_id: str,
    input_fasta_dir: str,
    output_dir: str,
):
    """Runs CD-HIT on a set of peptides and returns the parsed cluster DataFrame.

    Args:
        peptide_sequences: Peptide strings to cluster.
        similarity_threshold: Integer similarity percentage (e.g. 60 → ``-c 0.60``).
        combination_id: A unique label used to name the input/output files.
        input_fasta_dir: Directory for writing input FASTA files.
        output_dir: Directory for CD-HIT output files.

    Returns:
        A cluster DataFrame as returned by
        :func:`~filtering.utils.clustering.parse_cdhit_clusters`, with the
        index reset to a regular column.
    """
    base_name = f"{combination_id}_{similarity_threshold}_thresh"
    input_fasta = os.path.join(input_fasta_dir, f"{base_name}.fasta")
    output_base = os.path.join(output_dir, f"{base_name}.fasta.myout")

    write_to_fasta(os.path.join(input_fasta_dir, base_name), peptide_sequences)

    # -c: similarity threshold (0-1)  -g 1: global alignment  -M: memory (MB)
    # -n 3: word length for short peptides  -l 2: ignore seqs shorter than 3 AA
    cd_hit_args = [
        "-i", input_fasta,
        "-o", output_base,
        "-c", f"0.{similarity_threshold}",
        "-g", "1", "-M", "10000", "-n", "3", "-l", "2",
    ]

    if shutil.which("cd-hit"):
        subprocess.run(["cd-hit"] + cd_hit_args, text=True, check=True)
    elif sys.platform == "win32":
        # On Windows, run cd-hit through WSL with path conversion
        wsl_input = input_fasta.replace("\\", "/")
        wsl_output = output_base.replace("\\", "/")
        if len(wsl_input) >= 2 and wsl_input[1] == ":":
            drive = wsl_input[0].lower()
            wsl_input = f"/mnt/{drive}{wsl_input[2:]}"
        if len(wsl_output) >= 2 and wsl_output[1] == ":":
            drive = wsl_output[0].lower()
            wsl_output = f"/mnt/{drive}{wsl_output[2:]}"
        wsl_args = ["-i", wsl_input, "-o", wsl_output] + cd_hit_args[4:]
        subprocess.run(["wsl", "cd-hit"] + wsl_args, text=True, check=True)
    else:
        raise FileNotFoundError("cd-hit not found on PATH. Install: brew install cd-hit")

    cluster_df = parse_cdhit_clusters(f"{output_base}.clstr")
    cluster_df.reset_index(inplace=True)
    return cluster_df


def _cluster_all_combinations_round1(stage0_data: dict) -> list:
    """First-round clustering: one CD-HIT run per HLA combination.

    For each HLA combination (from ``threshold_8_hla_passing_peptides``),
    clusters its peptides and selects consensus representatives.

    Args:
        stage0_data: Dict as returned by ``run_stage0()``.

    Returns:
        A nested list — one inner list of consensus peptides per HLA
        combination.  Expected total (original data): ~55 066 peptides.
    """
    import sys

    threshold_peptides = stage0_data["threshold_8_hla_passing_peptides"]
    accepted_peptides_df = stage0_data["accepted_peptides_df"]

    all_consensus: list = []
    total_combos = len(threshold_peptides)

    os.makedirs(CDHIT_CLUSTER1_INPUT_DIR, exist_ok=True)
    os.makedirs(CDHIT_CLUSTER1_OUTPUT_DIR, exist_ok=True)

    print(f"[Sub-stage 1] Round 1: clustering {total_combos} HLA combinations independently...")
    sys.stdout.flush()

    for i, (combination_id, peptides) in enumerate(threshold_peptides.items(), 1):
        if i % 50 == 1 or i == total_combos:
            print(f"[Sub-stage 1]   Clustering combination {i}/{total_combos} ({len(peptides)} peptides)...")
            sys.stdout.flush()
        cluster_df = _run_cdhit(
            peptide_sequences=peptides,
            similarity_threshold=CDHIT_SIMILARITY_THRESHOLD,
            combination_id=combination_id,
            input_fasta_dir=CDHIT_CLUSTER1_INPUT_DIR,
            output_dir=CDHIT_CLUSTER1_OUTPUT_DIR,
        )
        consensus_df = select_cluster_consensus(cluster_df, accepted_peptides_df)
        consensus_peptides = consensus_df[consensus_df["is_representative"] == True]["index"].tolist()
        all_consensus.append(consensus_peptides)

    print(f"[Sub-stage 1] Round 1 complete: {sum(len(c) for c in all_consensus)} consensus peptides from {total_combos} combinations")
    sys.stdout.flush()

    return all_consensus


def run_stage1(stage0_data: dict) -> dict:
    """Runs two rounds of CD-HIT clustering and returns the final representative peptide set.

    Round 1 clusters per HLA combination independently.  Round 2 re-clusters
    all round-1 representatives globally.

    All intermediate and final results are memoized.  Delete the
    ``MEMOIZATION_DIR/stage-1/`` pickle files to force a full re-run.

    Args:
        stage0_data: Dict as returned by
            :func:`~filtering.stage0_load_data.run_stage0`.

    Returns:
        A dictionary with the following keys:

        - ``"consensus_peptides"`` (list): Final de-duplicated representative
          peptides after round 2.  These will feed into stage 2.
        - ``"consensus_df_round2"`` (:class:`pandas.DataFrame`): Full cluster
          table for the second round (useful for downstream analysis).

        Validation targets from the original dataset:
          - Flat peptide list after round 1: ~55 066 entries.
          - ``consensus_df_round2`` row count: ~8 435 rows.
    """
    memo_dir = os.path.join(MEMOIZATION_DIR, "stage-1")
    os.makedirs(memo_dir, exist_ok=True)

    # Round 1 — per-combination clustering (nested list of consensus peptides)
    all_consensus_round1 = memoize_function(
        lambda: _cluster_all_combinations_round1(stage0_data),
        os.path.join(memo_dir, "all_consensus_peptides_round1.pickle"),
    )

    import sys

    flat_peptide_list = [pep for sublist in all_consensus_round1 for pep in sublist]
    print(f"[Sub-stage 1] Round 1 total consensus peptides (expected ~55,066): {len(flat_peptide_list)}")
    sys.stdout.flush()

    if not flat_peptide_list:
        import pandas as pd
        print("[Sub-stage 1] No peptides to cluster in round 2 — skipping.")
        return {
            "consensus_peptides": [],
            "consensus_df_round2": pd.DataFrame(),
        }

    os.makedirs(CDHIT_CLUSTER2_INPUT_DIR, exist_ok=True)
    os.makedirs(CDHIT_CLUSTER2_OUTPUT_DIR, exist_ok=True)

    # Round 2 — global re-clustering of all round-1 consensus peptides
    cache_path = os.path.join(memo_dir, "cluster_df_round2.pickle")
    cached = os.path.exists(cache_path)
    print(f"[Sub-stage 1] Round 2: global re-clustering of {len(flat_peptide_list)} peptides... {'(cached)' if cached else '(running cd-hit)'}")
    sys.stdout.flush()
    cluster_df_round2 = memoize_function(
        lambda: _run_cdhit(
            peptide_sequences=flat_peptide_list,
            similarity_threshold=CDHIT_SIMILARITY_THRESHOLD,
            combination_id="second_round_on_consensus",
            input_fasta_dir=CDHIT_CLUSTER2_INPUT_DIR,
            output_dir=CDHIT_CLUSTER2_OUTPUT_DIR,
        ),
        cache_path,
    )

    cache_path = os.path.join(memo_dir, "consensus_df_round2.pickle")
    cached = os.path.exists(cache_path)
    print(f"[Sub-stage 1] Selecting round 2 consensus representatives... {'(cached)' if cached else '(computing)'}")
    sys.stdout.flush()
    consensus_df_round2 = memoize_function(
        lambda: select_cluster_consensus(cluster_df_round2, stage0_data["accepted_peptides_df"]),
        cache_path,
    )
    print(f"[Sub-stage 1] Round 2 cluster table rows (expected ~8,435): {len(consensus_df_round2)}")
    sys.stdout.flush()

    consensus_peptides = consensus_df_round2[
        consensus_df_round2["is_representative"] == True
    ]["Peptide"].tolist()

    return {
        "consensus_peptides": consensus_peptides,
        "consensus_df_round2": consensus_df_round2,
    }
