"""
self_similarity/main.py — Self-similarity analysis: check if candidate
super-binder peptides resemble naturally occurring human peptides.

Usage (from project root):
    python -m self_similarity.main

Or with options:
    python -m self_similarity.main --candidates data/candidate_peptides.fasta
    python -m self_similarity.main --precomputed data/needle/alignment_results.json

Pipeline:
    1. Load candidate peptides (from filtering output or FASTA file).
    2. Either load pre-computed alignment results or run fresh needle alignments.
    3. Parse results and apply self-similarity thresholds.
    4. Output: safe peptides (not similar to self) and a summary report.

NOTE: Running fresh needle alignments is extremely compute-intensive.
      For 100 peptides × ~400M 9-mers it can take hours/days.
      Pre-computed results (alignment_results.json) are strongly preferred.
"""
import json
import os
import sys
import time

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from Bio import SeqIO

from self_similarity.config import (
    ALIGNMENT_RESULTS_JSON,
    CANDIDATE_PEPTIDES_FASTA,
    HUMAN_9MERS_FASTA,
    HUMAN_PROTEOME_FASTA,
    IDENTITY_THRESHOLD,
    NEEDLE_CHUNKS_DIR,
    NEEDLE_OUTPUT_DIR,
    SIMILARITY_THRESHOLD,
)
from self_similarity.filter_self import filter_candidates, find_self_similar_peptides
from self_similarity.parse_results import (
    alignments_to_dataframe,
    enrich_with_sequences,
    load_alignment_results,
    load_fasta_index_from_chunks,
    parse_all_needle_outputs,
    save_alignment_results,
)


def _load_peptides_from_fasta(fasta_path: str) -> dict:
    """Load peptides from a FASTA file. Returns {name: sequence}."""
    peptides = {}
    for record in SeqIO.parse(fasta_path, "fasta"):
        peptides[record.id] = str(record.seq)
    return peptides


def _write_peptides_fasta(peptides: dict, fasta_path: str) -> None:
    """Write peptides dict to a FASTA file."""
    os.makedirs(os.path.dirname(fasta_path) or ".", exist_ok=True)
    with open(fasta_path, "w") as f:
        for name, seq in peptides.items():
            f.write(f">{name}\n{seq}\n")


def run_self_similarity(
    candidate_peptides: list = None,
    candidates_fasta: str = None,
    precomputed_json: str = None,
    output_dir: str = None,
) -> dict:
    """Run the full self-similarity analysis.

    Args:
        candidate_peptides: List of peptide sequences (strings).
        candidates_fasta: Path to FASTA file with candidates (alternative to list).
        precomputed_json: Path to pre-computed alignment_results.json.
                          If provided, skip needle runs entirely.
        output_dir: Directory for output files. Defaults to data/needle/.

    Returns:
        Dict with keys:
            - safe_peptides: List of peptides that passed the self-similarity filter.
            - removed_peptides: List of peptides removed (similar to self).
            - self_similar_set: Set of flagged peptide sequences.
            - similar_human_peptides: Set of matched human peptides.
            - alignment_count: Total number of alignments processed.
            - thresholds: Dict with similarity and identity thresholds used.
    """
    print("\n" + "=" * 60)
    print("  Self-Similarity Analysis")
    print("  Compare stage 3 candidates against human proteome 9-mers")
    print("  to remove peptides that resemble human self-peptides")
    print("=" * 60)

    t_start = time.time()

    # ── Step 1: Load candidates (output from stage 3 filtering) ───────────
    candidates_source = None
    if candidate_peptides is not None:
        pep_dict = {f"seq{i}": seq for i, seq in enumerate(candidate_peptides)}
        candidates_source = "passed as list"
    elif candidates_fasta:
        pep_dict = _load_peptides_from_fasta(candidates_fasta)
        candidates_source = candidates_fasta
    elif os.path.isfile(CANDIDATE_PEPTIDES_FASTA):
        pep_dict = _load_peptides_from_fasta(CANDIDATE_PEPTIDES_FASTA)
        candidates_source = CANDIDATE_PEPTIDES_FASTA
    else:
        raise FileNotFoundError(
            "No candidate peptides provided. Pass candidate_peptides list, "
            "candidates_fasta path, or set CANDIDATE_PEPTIDES_FASTA in .env"
        )

    print(f"\n  [Step 1] Loaded {len(pep_dict)} candidate peptides from: {candidates_source}")
    all_sequences = list(pep_dict.values())

    # Show what we're comparing against
    human_ref = HUMAN_9MERS_FASTA or "(will be generated from proteome)"
    print(f"  [Step 1] Human reference 9-mers: {human_ref}")

    # ── Step 2: Get alignment results ─────────────────────────────────────
    precomputed = precomputed_json or ALIGNMENT_RESULTS_JSON
    alignments = None

    if precomputed and os.path.isfile(precomputed):
        print(f"\n  Loading pre-computed alignments from: {precomputed}")
        alignments = load_alignment_results(precomputed)
        print(f"  Loaded {len(alignments):,} alignments.")
    elif os.path.isdir(NEEDLE_OUTPUT_DIR) and any(
        f.endswith(".txt") for f in os.listdir(NEEDLE_OUTPUT_DIR)
    ):
        print(f"\n  Parsing needle output files from: {NEEDLE_OUTPUT_DIR}")
        alignments = parse_all_needle_outputs(NEEDLE_OUTPUT_DIR)
        print(f"  Parsed {len(alignments):,} alignments.")

        # Optionally enrich with FASTA sequences
        if os.path.isdir(NEEDLE_CHUNKS_DIR):
            print("  Loading FASTA index from chunks for sequence enrichment...")
            fasta_index = load_fasta_index_from_chunks(NEEDLE_CHUNKS_DIR)
            alignments = enrich_with_sequences(alignments, fasta_index)

        # Cache parsed results
        save_alignment_results(alignments, precomputed or ALIGNMENT_RESULTS_JSON)
        print(f"  Saved parsed results to: {precomputed or ALIGNMENT_RESULTS_JSON}")
    else:
        # Need to run needle from scratch
        print("\n  No pre-computed results found. Running needle alignments...")
        print("  WARNING: This is extremely compute-intensive and may take hours/days.")

        # Check prerequisites
        if not os.path.isdir(NEEDLE_CHUNKS_DIR) or not any(
            f.endswith(".fasta") for f in os.listdir(NEEDLE_CHUNKS_DIR)
        ):
            # Need to prepare chunks
            if not HUMAN_9MERS_FASTA or not os.path.isfile(HUMAN_9MERS_FASTA):
                if not HUMAN_PROTEOME_FASTA or not os.path.isfile(HUMAN_PROTEOME_FASTA):
                    raise FileNotFoundError(
                        "No reference peptidome available.\n"
                        "Set HUMAN_9MERS_FASTA (pre-chopped 9-mers) or "
                        "HUMAN_PROTEOME_FASTA (full proteome) in .env.\n"
                        "Or provide pre-computed results via --precomputed."
                    )
                print("  Chopping proteome into 9-mers (this may take a while)...")
                from self_similarity.chopper import chop_fasta_to_9mers, split_fasta_into_chunks

                ninemer_path = HUMAN_9MERS_FASTA or os.path.join(
                    _PROJECT_ROOT, "data", "needle", "human_9mers.fasta"
                )
                n_kmers = chop_fasta_to_9mers(HUMAN_PROTEOME_FASTA, ninemer_path)
                print(f"  Wrote {n_kmers:,} 9-mers.")

                print("  Splitting into chunks...")
                split_fasta_into_chunks(ninemer_path, NEEDLE_CHUNKS_DIR)
            else:
                print("  Splitting 9-mer FASTA into chunks...")
                from self_similarity.chopper import split_fasta_into_chunks
                split_fasta_into_chunks(HUMAN_9MERS_FASTA, NEEDLE_CHUNKS_DIR)

        # Write candidate FASTA for reference
        _write_peptides_fasta(pep_dict, CANDIDATE_PEPTIDES_FASTA)

        # Run needle
        from self_similarity.needle_runner import run_needle_alignments
        run_needle_alignments(pep_dict)

        # Parse results
        alignments = parse_all_needle_outputs(NEEDLE_OUTPUT_DIR)

        # Enrich and save
        if os.path.isdir(NEEDLE_CHUNKS_DIR):
            fasta_index = load_fasta_index_from_chunks(NEEDLE_CHUNKS_DIR)
            alignments = enrich_with_sequences(alignments, fasta_index)

        save_alignment_results(alignments, ALIGNMENT_RESULTS_JSON)

    if not alignments:
        print("\n  No alignments found — all peptides considered safe.")
        return {
            "safe_peptides": all_sequences,
            "removed_peptides": [],
            "self_similar_set": set(),
            "similar_human_peptides": set(),
            "alignment_count": 0,
            "thresholds": {
                "similarity": SIMILARITY_THRESHOLD,
                "identity": IDENTITY_THRESHOLD,
            },
        }

    # ── Step 3: Apply self-similarity filter ──────────────────────────────
    df = alignments_to_dataframe(alignments)
    print(f"\n  Applying thresholds: similarity >= {SIMILARITY_THRESHOLD}/9 "
          f"OR identity >= {IDENTITY_THRESHOLD}/9")

    self_similar, similar_human, flagged_df = find_self_similar_peptides(
        df, SIMILARITY_THRESHOLD, IDENTITY_THRESHOLD
    )

    safe, removed = filter_candidates(all_sequences, self_similar)

    # ── Step 4: Report ────────────────────────────────────────────────────
    elapsed = time.time() - t_start

    print(f"\n  Results:")
    print(f"    Total alignments analyzed: {len(alignments):,}")
    print(f"    Flagged as self-similar:   {len(self_similar)}")
    print(f"    Human peptides matched:    {len(similar_human)}")
    print(f"    Candidates removed:        {len(removed)}")
    print(f"    Safe peptides remaining:   {len(safe)}")
    print(f"\n  Elapsed: {elapsed:.1f}s")
    print("=" * 60)

    # Save safe peptides FASTA
    out_dir = output_dir or os.path.join(_PROJECT_ROOT, "data", "needle")
    os.makedirs(out_dir, exist_ok=True)

    safe_fasta = os.path.join(out_dir, "safe_peptides.fasta")
    with open(safe_fasta, "w") as f:
        for i, seq in enumerate(safe):
            f.write(f">safe_{i}\n{seq}\n")
    print(f"  Safe peptides written to: {safe_fasta}")

    # Save removed peptides list
    removed_path = os.path.join(out_dir, "removed_self_similar.txt")
    with open(removed_path, "w") as f:
        for seq in removed:
            f.write(f"{seq}\n")
    print(f"  Removed peptides written to: {removed_path}")

    # Save summary
    summary = {
        "total_candidates": len(all_sequences),
        "total_alignments": len(alignments),
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "identity_threshold": IDENTITY_THRESHOLD,
        "self_similar_count": len(self_similar),
        "human_matches_count": len(similar_human),
        "removed_count": len(removed),
        "safe_count": len(safe),
        "self_similar_peptides": sorted(self_similar),
        "safe_peptides": safe,
    }
    summary_path = os.path.join(out_dir, "self_similarity_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary written to: {summary_path}")

    return {
        "safe_peptides": safe,
        "removed_peptides": removed,
        "self_similar_set": self_similar,
        "similar_human_peptides": similar_human,
        "alignment_count": len(alignments),
        "thresholds": {
            "similarity": SIMILARITY_THRESHOLD,
            "identity": IDENTITY_THRESHOLD,
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Self-similarity analysis for super-binder peptides"
    )
    parser.add_argument(
        "--candidates", default="",
        help="FASTA file with candidate peptides",
    )
    parser.add_argument(
        "--precomputed", default="",
        help="Pre-computed alignment_results.json (skip needle runs)",
    )
    parser.add_argument(
        "--output-dir", default="",
        help="Output directory for results",
    )
    args = parser.parse_args()

    run_self_similarity(
        candidates_fasta=args.candidates or None,
        precomputed_json=args.precomputed or None,
        output_dir=args.output_dir or None,
    )


if __name__ == "__main__":
    main()
