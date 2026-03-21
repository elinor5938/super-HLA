"""
self_similarity/parse_results.py — Parse needle output files into structured data.

Needle output (after grep filtering) looks like:
    # 2: 728472
    # Identity:       6/9 (66.7%)
    # Similarity:     6/9 (66.7%)
    # Score: 33.0

This module parses those blocks and optionally resolves the FASTA sequence
index back to the actual 9-mer sequence from the reference peptidome.
"""
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


def parse_needle_output_file(file_path: str) -> List[dict]:
    """Parse a single needle output text file.

    Returns a list of dicts, each with keys:
        pep, fasta_seq_index, identity, similarity, score
    """
    results = []
    current_pep = None

    with open(file_path, "r") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        line = line.strip()

        # Peptide header
        if line.startswith("### A="):
            match = re.search(r"seq=(\w+)", line)
            if match:
                current_pep = match.group(1)

        # FASTA sequence index line
        elif line.startswith("# 2:"):
            try:
                entry = {"pep": current_pep}
                entry["fasta_seq_index"] = line.split(":")[1].strip()

                # Identity (next line)
                identity_line = lines[i + 1].strip()
                identity_match = re.search(r"(\d+)/9", identity_line)
                if identity_match:
                    entry["identity"] = int(identity_match.group(1))

                # Similarity (line after)
                similarity_line = lines[i + 2].strip()
                similarity_match = re.search(r"(\d+)/9", similarity_line)
                if similarity_match:
                    entry["similarity"] = int(similarity_match.group(1))

                # Score (line after that)
                score_line = lines[i + 3].strip()
                score_match = re.search(r"Score:\s*([\d.\-]+)", score_line)
                if score_match:
                    entry["score"] = float(score_match.group(1))

                results.append(entry)
            except (IndexError, AttributeError):
                pass  # Incomplete block at end of file

    return results


def parse_all_needle_outputs(output_dir: str) -> List[dict]:
    """Parse all needle-*.txt files in *output_dir*.

    Returns a flat list of alignment dicts.
    """
    results = []
    output_path = Path(output_dir)

    needle_files = sorted(output_path.glob("needle-*.txt"))
    if not needle_files:
        return results

    for nf in needle_files:
        alignments = parse_needle_output_file(str(nf))
        results.extend(alignments)

    return results


def load_fasta_index(fasta_path: str) -> Dict[str, str]:
    """Build a mapping from numeric FASTA IDs to sequences.

    This reads the reference 9-mer FASTA and returns {id: sequence}.
    For very large files (16 GB), this can take significant memory (~20 GB).
    Consider using chunked files if memory is limited.
    """
    index = {}
    current_id = None

    with open(fasta_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                current_id = line[1:].split()[0]
            elif current_id and line:
                index[current_id] = line
                current_id = None

    return index


def load_fasta_index_from_chunks(chunks_dir: str) -> Dict[str, str]:
    """Build FASTA index from chunked files (lower peak memory per chunk)."""
    index = {}
    chunk_dir = Path(chunks_dir)

    for chunk_file in sorted(chunk_dir.glob("*.fasta")):
        current_id = None
        with open(chunk_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    current_id = line[1:].split()[0]
                elif current_id and line:
                    index[current_id] = line
                    current_id = None

    return index


def enrich_with_sequences(
    alignments: List[dict],
    fasta_index: Dict[str, str],
) -> List[dict]:
    """Add 'fasta_seq_string' to each alignment dict using the FASTA index."""
    for aln in alignments:
        seq_idx = aln.get("fasta_seq_index", "")
        aln["fasta_seq_string"] = fasta_index.get(seq_idx, "")
    return alignments


def save_alignment_results(alignments: List[dict], output_path: str) -> None:
    """Write alignment results to a JSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(alignments, f, indent=2)


def load_alignment_results(json_path: str) -> List[dict]:
    """Load previously saved alignment results from JSON."""
    with open(json_path, "r") as f:
        return json.load(f)


def alignments_to_dataframe(alignments: List[dict]) -> pd.DataFrame:
    """Convert alignment list to a pandas DataFrame."""
    return pd.DataFrame(alignments)
