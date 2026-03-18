"""
stage1_cdhit_clustering.py — Two-round CD-HIT clustering to select representative peptides.

This stage reduces the ~471 initial HLA-combination peptide sets down to a
compact set of representative (consensus) sequences using two rounds of
sequence similarity clustering with the CD-HIT tool.

Round 1 — per-combination clustering:
  Each HLA combination's peptide list is clustered independently at 60%
  similarity.  The best-scoring (lowest one_side_mean) peptide from each
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
import subprocess

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
    should_generate_fasta: bool = True,
):
    """Runs CD-HIT on a set of peptides and returns the parsed cluster DataFrame.

    Args:
        peptide_sequences: Peptide strings to cluster.
        similarity_threshold: Integer similarity percentage (e.g. 60 → ``-c 0.60``).
        combination_id: A unique label used to name the input/output files.
        input_fasta_dir: Directory for writing input FASTA files.
        output_dir: Directory for CD-HIT output files.
        should_generate_fasta: If ``True``, writes a fresh FASTA before clustering.
            Set to ``False`` to re-use existing FASTA files (e.g. on re-runs).

    Returns:
        A cluster DataFrame as returned by
        :func:`~filtering.utils.clustering.parse_cdhit_clusters`, with the
        index reset to a regular column.
    """
    base_name = f"{combination_id}_{similarity_threshold}_thresh"
    input_fasta = os.path.join(input_fasta_dir, f"{base_name}.fasta")
    output_base = os.path.join(output_dir, f"{base_name}.fasta.myout")

    if should_generate_fasta:
        write_to_fasta(os.path.join(input_fasta_dir, base_name), peptide_sequences)

    # -c: similarity threshold (0–1)  -g 1: global alignment  -M: memory (MB)
    # -n 3: word length for short peptides  -l 2: ignore seqs shorter than 3 AA
    cd_hit_command = (
        f"cd-hit -i {input_fasta} "
        f"-o {output_base} "
        f"-c 0.{similarity_threshold} -g 1 -M 10000 -n 3 -l 2"
    )
    subprocess.run(cd_hit_command, shell=True, text=True, check=True)

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
    threshold_peptides = stage0_data["threshold_8_hla_passing_peptides"]
    robust_df = stage0_data["robust_df"]

    all_consensus: list = []

    for combination_id, peptides in threshold_peptides.items():
        cluster_df = _run_cdhit(
            peptide_sequences=peptides,
            similarity_threshold=CDHIT_SIMILARITY_THRESHOLD,
            combination_id=combination_id,
            input_fasta_dir=CDHIT_CLUSTER1_INPUT_DIR,
            output_dir=CDHIT_CLUSTER1_OUTPUT_DIR,
            should_generate_fasta=False,  # Use pre-existing FASTA files
        )
        consensus_df = select_cluster_consensus(cluster_df, robust_df)
        consensus_peptides = consensus_df[consensus_df["consensus_SB"] == "consensus"]["index"].tolist()
        all_consensus.append(consensus_peptides)

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

    flat_peptide_list = [pep for sublist in all_consensus_round1 for pep in sublist]
    print(f"[Stage 1] Round 1 flat consensus peptide count (expected ~55 066): {len(flat_peptide_list)}")

    # Round 2 — global re-clustering of all round-1 consensus peptides
    cluster_df_round2 = memoize_function(
        lambda: _run_cdhit(
            peptide_sequences=flat_peptide_list,
            similarity_threshold=CDHIT_SIMILARITY_THRESHOLD,
            combination_id="second_round_on_consensus",
            input_fasta_dir=CDHIT_CLUSTER2_INPUT_DIR,
            output_dir=CDHIT_CLUSTER2_OUTPUT_DIR,
            should_generate_fasta=False,
        ),
        os.path.join(memo_dir, "cluster_df_round2.pickle"),
    )

    consensus_df_round2 = memoize_function(
        lambda: select_cluster_consensus(cluster_df_round2, stage0_data["robust_df"]),
        os.path.join(memo_dir, "consensus_df_round2.pickle"),
    )
    print(f"[Stage 1] Round 2 cluster table row count (expected ~8 435): {len(consensus_df_round2)}")

    consensus_peptides = consensus_df_round2[
        consensus_df_round2["consensus_SB"] == "consensus"
    ]["Peptide"].tolist()

    return {
        "consensus_peptides": consensus_peptides,
        "consensus_df_round2": consensus_df_round2,
    }
