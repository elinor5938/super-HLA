"""
self_similarity/needle_runner.py — Run EMBOSS needle alignments in parallel.

Each candidate peptide is aligned against every sequence in the reference
peptidome (chunked FASTA files).  High gap penalties enforce ungapped
global alignment of equal-length 9-mers.

The needle command:
    needle -asequence asis:<PEPTIDE> -bsequence <CHUNK>
           -gapopen 100 -gapextend 10 -endweight Y -endopen 100 -endextend 10
           -error N -warning N -sprotein -stdout Y -filter Y -verbose Y

Output is filtered in Python (no grep dependency) to keep only hits with
identity >= 6/9, extracting identity, similarity, score, and sequence ID lines.
"""
import os
import re
import shutil
import subprocess
import sys
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
    if path:
        return path
    # On Windows, try WSL
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["wsl", "which", "needle"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "wsl needle"  # Will be used as prefix
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        raise FileNotFoundError(
            "EMBOSS needle not found. Install WSL and run: sudo apt install emboss"
        )
    raise FileNotFoundError(
        "EMBOSS needle not found on PATH. Install: brew install emboss"
    )


def _filter_needle_output(raw_stdout: str) -> str:
    """Pure-Python replacement for grep filtering of needle output.

    Keeps blocks around lines matching 'Identity: N/9' where N >= 6,
    extracting Identity, Similarity, Score, and sequence ID (# 2:) lines.
    """
    lines = raw_stdout.splitlines()
    result_lines = []

    for i, line in enumerate(lines):
        # Look for identity lines with high identity (6-9 out of 9)
        if re.search(r'Identity:\s+[6-9]/9', line):
            # Collect context: look backwards for # 2: line, and forward for similarity/score
            block = []
            # Search backwards up to 6 lines for the sequence ID
            for j in range(max(0, i - 6), i):
                if '# 2:' in lines[j]:
                    block.append(lines[j].strip())
            # The identity line itself
            block.append(line.strip())
            # Look forward for similarity and score (up to 3 lines)
            for j in range(i + 1, min(len(lines), i + 4)):
                if re.search(r'Similarity:|Score:', lines[j]):
                    block.append(lines[j].strip())
            result_lines.extend(block)

    return "\n".join(result_lines)


def _build_needle_cmd(needle_bin: str, peptide: str, chunk_path: str) -> list:
    """Build the needle command as a list (cross-platform)."""
    args = [
        "-asequence", f"asis:{peptide}",
        "-bsequence", chunk_path,
        "-gapopen", "100", "-gapextend", "10",
        "-endweight", "Y", "-endopen", "100", "-endextend", "10",
        "-error", "N", "-warning", "N",
        "-sprotein", "-stdout", "Y", "-filter", "Y", "-verbose", "Y",
    ]

    if needle_bin.startswith("wsl "):
        # Running through WSL on Windows — convert path
        wsl_chunk = chunk_path.replace("\\", "/")
        # Convert Windows drive paths to WSL: C:\foo -> /mnt/c/foo
        if len(wsl_chunk) >= 2 and wsl_chunk[1] == ":":
            drive = wsl_chunk[0].lower()
            wsl_chunk = f"/mnt/{drive}{wsl_chunk[2:]}"
        args[3] = wsl_chunk  # -bsequence
        return ["wsl", "needle"] + args
    else:
        return [needle_bin] + args


def _run_needle_one_peptide_one_chunk(
    peptide: str, chunk_path: str, needle_bin: str
) -> str:
    """Run needle for a single peptide against a single chunk FASTA.

    Returns the filtered output text (or empty string on failure).
    Uses pure-Python filtering instead of grep for cross-platform compatibility.
    """
    cmd = _build_needle_cmd(needle_bin, peptide, chunk_path)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=7200,
        )
        if result.returncode != 0:
            return ""
        return _filter_needle_output(result.stdout)
    except subprocess.TimeoutExpired:
        return ""


def _run_needle_one_task(args: tuple) -> dict:
    """Worker function for multiprocessing Pool.

    Args is a tuple of (peptide_name, peptide_seq, chunk_path, needle_bin).
    Returns a dict with the peptide name, chunk, and the filtered output.
    """
    pep_name, pep_seq, chunk_path, needle_bin = args
    out = _run_needle_one_peptide_one_chunk(pep_seq, chunk_path, needle_bin)
    chunk_label = os.path.basename(chunk_path)
    return {
        "name": pep_name,
        "seq": pep_seq,
        "chunk": chunk_label,
        "output": f"---- B={chunk_label}\n{out}" if out.strip() else "",
    }


def run_needle_alignments(
    peptides: Dict[str, str],
    chunks_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    workers: Optional[int] = None,
) -> List[str]:
    """Run needle alignments for all candidate peptides.

    Args:
        peptides: Mapping of peptide name -> sequence (e.g. {"seq0": "ALFPHIMTY"}).
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

    total_alignments = len(peptides) * len(chunk_paths)
    print(f"  [Step 2b] Needle alignment plan:")
    print(f"            Candidates:  {len(peptides)} peptides")
    print(f"            Reference:   {len(chunk_paths)} chunks")
    print(f"            Total runs:  {total_alignments:,} (each peptide vs each chunk)")
    print(f"            Workers:     {workers} parallel processes")
    print(f"            Output dir:  {output_dir}")
    sys.stdout.flush()

    # Skip peptides that already have output files (resume support)
    tasks = []
    output_paths = []
    cached_count = 0
    for pep_name, pep_seq in peptides.items():
        out_path = os.path.join(output_dir, f"needle-{pep_name}.txt")
        output_paths.append(out_path)
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            cached_count += 1
            continue  # already computed
        tasks.append((pep_name, pep_seq))

    if not tasks:
        print(f"  [Step 2b] All {len(peptides)} peptide results already cached — skipping needle.")
        return output_paths

    if cached_count > 0:
        print(f"  [Step 2b] {cached_count} peptides already cached, {len(tasks)} remaining to compute")
    total_chunk_tasks = len(tasks) * len(chunk_paths)
    chunk_size_gb = os.path.getsize(chunk_paths[0]) / (1024**3)
    print(f"  [Step 2b] Running needle: {len(tasks)} peptides x {len(chunk_paths)} chunks = {total_chunk_tasks} alignment jobs")
    print(f"            Chunk size: ~{chunk_size_gb:.1f} GB each — progress shown per chunk completion")
    sys.stdout.flush()

    import time as _time
    t_start = _time.time()

    # Build per-chunk tasks for finer-grained progress
    chunk_tasks = []
    for pep_name, pep_seq in tasks:
        for cp in chunk_paths:
            chunk_tasks.append((pep_name, pep_seq, cp, needle_bin))

    # Collect results grouped by peptide
    peptide_outputs = {}
    for pep_name, pep_seq in tasks:
        peptide_outputs[pep_name] = {"seq": pep_seq, "parts": []}

    completed = 0
    with Pool(processes=workers) as pool:
        for result in pool.imap_unordered(_run_needle_one_task, chunk_tasks):
            completed += 1
            elapsed = _time.time() - t_start
            avg = elapsed / completed
            remaining = avg * (total_chunk_tasks - completed)
            eta_str = f"{remaining:.0f}s" if remaining < 3600 else f"{remaining/3600:.1f}h"
            print(
                f"  [Step 2b] {completed}/{total_chunk_tasks}: "
                f"{result['name']} ({result['seq']}) vs {result['chunk']} "
                f"| {elapsed:.0f}s elapsed | ETA ~{eta_str}"
            )
            sys.stdout.flush()
            if result["output"]:
                peptide_outputs[result["name"]]["parts"].append(result["output"])

    elapsed = _time.time() - t_start
    print(f"  [Step 2b] All {total_chunk_tasks} alignments done in {elapsed:.1f}s")
    sys.stdout.flush()

    # Write output files
    for pep_name, data in peptide_outputs.items():
        out_path = os.path.join(output_dir, f"needle-{pep_name}.txt")
        with open(out_path, "w") as f:
            f.write(f"### A={pep_name}, seq={data['seq']}\n")
            f.write("\n".join(data["parts"]))

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
