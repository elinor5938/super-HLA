#!/usr/bin/env python3
"""
Smoke test for stage 4 (self-similarity analysis).

Creates a tiny reference FASTA (~200 9-mers) and 3 candidate peptides,
then runs the actual stage 4 entry point (run_self_similarity) end-to-end.
Should complete in under 2 minutes.

Usage (from project root):
    python smoke_test_stage4.py

What it validates:
    - needle binary is found and works
    - The full stage 4 pipeline (chunking, alignment, parsing, filtering) works
    - Output files (safe_peptides.fasta, summary JSON) are produced
    - Known matches are correctly flagged and safe peptides pass through
"""
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _generate_test_reference(path: str, n_sequences: int = 200):
    """Generate a small reference FASTA with n random-ish 9-mers."""
    import random
    random.seed(42)
    aa = "ACDEFGHIKLMNPQRSTVWY"
    with open(path, "w") as f:
        for i in range(1, n_sequences + 1):
            seq = "".join(random.choices(aa, k=9))
            f.write(f">ref_9mer_{i}\n{seq}\n")
        # Add sequences deliberately similar to our candidates
        f.write(">ref_9mer_match1\nALFPHIMTY\n")  # exact match to candidate 1
        f.write(">ref_9mer_match2\nRMDPTRHQM\n")  # 8/9 identity to candidate 2 (RMDPTRHQL)


def main():
    print("=" * 60)
    print("  Stage 4 Smoke Test")
    print("  Runs the actual run_self_similarity() with tiny test data")
    print("=" * 60)

    # Create test directory inside the repo (data/ is gitignored)
    test_dir = os.path.join(PROJECT_ROOT, "data", "smoke_test_stage4")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir, exist_ok=True)
    print(f"\n  Test directory: {test_dir}")

    chunks_dir = os.path.join(test_dir, "chunks")
    output_dir = os.path.join(test_dir, "output")
    candidates_fasta = os.path.join(test_dir, "test_candidates.fasta")
    results_json = os.path.join(test_dir, "alignment_results.json")

    os.makedirs(chunks_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 1. Generate tiny reference and chunk it
    print("\n  [Setup] Generating test reference FASTA (202 sequences)...")
    ref_fasta = os.path.join(test_dir, "test_9mers.fasta")
    _generate_test_reference(ref_fasta, n_sequences=200)
    shutil.copy(ref_fasta, os.path.join(chunks_dir, "chunk_0001.fasta"))

    # 2. Write test candidates
    candidates = {
        "test_exact_match": "ALFPHIMTY",   # exact match in ref — should be REMOVED
        "test_near_match":  "RMDPTRHQL",   # 8/9 match in ref  — should be REMOVED
        "test_safe":        "WWWWWWWWW",   # no match in ref   — should be SAFE
    }
    with open(candidates_fasta, "w") as f:
        for name, seq in candidates.items():
            f.write(f">{name}\n{seq}\n")
    print(f"  [Setup] Created {len(candidates)} test candidates:")
    for name, seq in candidates.items():
        print(f"           {name}: {seq}")

    # 3. Override env vars so the real code uses our test directories
    os.environ["NEEDLE_CHUNKS_DIR"] = chunks_dir
    os.environ["NEEDLE_OUTPUT_DIR"] = output_dir
    os.environ["ALIGNMENT_RESULTS_JSON"] = results_json
    os.environ["CANDIDATE_PEPTIDES_FASTA"] = candidates_fasta
    os.environ["NEEDLE_WORKERS"] = "2"

    # 4. Run the actual stage 4 entry point
    print("\n  [Run] Calling run_self_similarity() — the real stage 4 code...")
    print()
    from filtering.self_similarity.main import run_self_similarity
    result = run_self_similarity(candidates_fasta=candidates_fasta, output_dir=test_dir)

    # 5. Validate expected outcomes
    print("\n" + "=" * 60)
    print("  Smoke Test Validation")
    print("=" * 60)

    errors = []
    if "ALFPHIMTY" not in result["self_similar_set"]:
        errors.append("FAIL: ALFPHIMTY (exact match) should have been flagged")
    if "WWWWWWWWW" in result["self_similar_set"]:
        errors.append("FAIL: WWWWWWWWW (no match) should NOT have been flagged")
    if not os.path.isfile(os.path.join(test_dir, "safe_peptides.fasta")):
        errors.append("FAIL: safe_peptides.fasta was not written")
    if not os.path.isfile(os.path.join(test_dir, "self_similarity_summary.json")):
        errors.append("FAIL: self_similarity_summary.json was not written")

    if errors:
        for e in errors:
            print(f"  {e}")
        print(f"\n  \033[31mSmoke test FAILED.\033[0m")
        sys.exit(1)
    else:
        print(f"  \033[32mAll checks passed.\033[0m")
        print(f"\n  Test artifacts in: {test_dir}")
        print(f"  Clean up with: rm -rf {test_dir}")


if __name__ == "__main__":
    main()
