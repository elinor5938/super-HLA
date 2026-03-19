"""
self_similarity/needle_runner.py — Run EMBOSS needle alignments in parallel.

Each candidate peptide is aligned against every sequence in the reference
peptidome (chunked FASTA files).  High gap penalties enforce ungapped
global alignment of equal-length 9-mers.

The needle command:
    needle -asequence asis:<PEPTIDE> -bsequence <CHUNK>
           -gapopen 100 -gapextend 10 -endweight Y -endopen 100 -endextend 10
           -error N -warning N -sprotein -stdout Y -filter Y -verbose Y

Output is piped through grep to keep only hits with identity >= 6/9,
extracting identity, similarity, score, and matched sequence ID lines.
"""
import os
import re
import shutil
import subprocess
from multiprocessing import Pool
from typing import Dict, List, Optional

from self_similarity.config import (
    NEEDLE_CHUNKS_DIR,
    NEEDLE_OUTPUT_DIR,
    NEEDLE_WORKERS,
)


def _find_needle() -> str:
    """Return the path to the needle executable, or raise."""
    path = shutil.which("needle")
    if not path:
        raise FileNotFoundError(
            "EMBOSS needle not found on PATH. Install: brew install emboss"
        )
    return path


def _run_needle_one_peptide_one_chunk(
    peptide: str, chunk_path: str, needle_bin: str
) -> str:
    """Run needle for a single peptide against a single chunk FASTA.

    Returns the filtered stdout text (or empty string on failure).
    """
    cmd = (
        f"{needle_bin} -asequence asis:{peptide} -bsequence {chunk_path} "
        f"-gapopen 100 -gapextend 10 -endweight Y -endopen 100 -endextend 10 "
        f"-error N -warning N -sprotein -stdout Y -filter Y -verbose Y"
    )
    # Pipe through grep for high-identity hits (identity digit >= 6 out of 9)
    full_cmd = (
        f"{cmd} | grep -E -B 6 -A 3 'Identity:\\s+[6-9]' "
        f"| grep -E 'Identity:|2:|Score:|Similarity'"
    )
    try:
        result = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True, timeout=7200,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return ""


def _run_needle_for_peptide(args: tuple) -> dict:
    """Worker function for multiprocessing Pool.

    Args is a tuple of (peptide_name, peptide_seq, chunk_paths, needle_bin).
    Returns a dict with the peptide name and the combined raw output.
    """
    pep_name, pep_seq, chunk_paths, needle_bin = args
    all_output = []

    for chunk_path in chunk_paths:
        out = _run_needle_one_peptide_one_chunk(pep_seq, chunk_path, needle_bin)
        if out.strip():
            chunk_label = os.path.basename(chunk_path)
            all_output.append(f"---- B={chunk_label}\n{out}")

    return {
        "name": pep_name,
        "seq": pep_seq,
        "raw_output": "\n".join(all_output),
    }


def run_needle_alignments(
    peptides: Dict[str, str],
    chunks_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    workers: Optional[int] = None,
) -> List[str]:
    """Run needle alignments for all candidate peptides.

    Args:
        peptides: Mapping of peptide name → sequence (e.g. {"seq0": "ALFPHIMTY"}).
        chunks_dir: Directory containing chunked reference FASTA files.
        output_dir: Where to write per-peptide needle output text files.
        workers: Number of parallel processes (defaults to config).

    Returns:
        List of output file paths written.
    """
    chunks_dir = chunks_dir or NEEDLE_CHUNKS_DIR
    output_dir = output_dir or NEEDLE_OUTPUT_DIR
    workers = workers or NEEDLE_WORKERS

    os.makedirs(output_dir, exist_ok=True)
    needle_bin = _find_needle()

    # Collect chunk files
    chunk_paths = sorted(
        os.path.join(chunks_dir, f)
        for f in os.listdir(chunks_dir)
        if f.endswith(".fasta")
    )
    if not chunk_paths:
        raise FileNotFoundError(f"No .fasta chunk files found in {chunks_dir}")

    print(f"  Needle: {len(peptides)} peptides × {len(chunk_paths)} chunks, "
          f"{workers} workers")

    # Skip peptides that already have output files (resume support)
    tasks = []
    output_paths = []
    for pep_name, pep_seq in peptides.items():
        out_path = os.path.join(output_dir, f"needle-{pep_name}.txt")
        output_paths.append(out_path)
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            continue  # already computed
        tasks.append((pep_name, pep_seq, chunk_paths, needle_bin))

    if not tasks:
        print("  All needle results already exist — skipping.")
        return output_paths

    print(f"  Running needle for {len(tasks)} peptides ({len(peptides) - len(tasks)} cached)...")

    # Run in parallel
    with Pool(processes=workers) as pool:
        results = pool.map(_run_needle_for_peptide, tasks)

    # Write output files
    for res in results:
        out_path = os.path.join(output_dir, f"needle-{res['name']}.txt")
        with open(out_path, "w") as f:
            f.write(f"### A={res['name']}, seq={res['seq']}\n")
            f.write(res["raw_output"])

    return output_paths


def run_needle_single_peptide(
    peptide_seq: str,
    reference_fasta: str,
) -> str:
    """Run needle for a single peptide against a single FASTA (non-chunked).

    Useful for quick tests. Returns the raw filtered output.
    """
    needle_bin = _find_needle()
    return _run_needle_one_peptide_one_chunk(peptide_seq, reference_fasta, needle_bin)
