"""
self_similarity/chopper.py — Chop a protein FASTA into overlapping 9-mer peptides.

This is a one-time preprocessing step.  The output can be 10–20 GB for a
full human proteome, so the function streams to disk without holding
everything in memory.

Usage (standalone):
    python -m self_similarity.chopper \\
        --input  /path/to/human_proteome.fasta \\
        --output /path/to/human_9mers.fasta

The output FASTA uses numeric sequence IDs (incrementing integers) so that
downstream needle results can be efficiently joined back to the original
sequence.
"""
import os
import sys

KMER_LENGTH = 9


def chop_fasta_to_9mers(input_path: str, output_path: str) -> int:
    """Read *input_path* and write every overlapping 9-mer to *output_path*.

    Returns the total number of 9-mers written.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    count = 0
    current_header = ""
    current_seq = []

    def _flush(header: str, seq_parts: list, fout, counter: int) -> int:
        seq = "".join(seq_parts).upper()
        if len(seq) < KMER_LENGTH:
            return counter
        for i in range(len(seq) - KMER_LENGTH + 1):
            kmer = seq[i : i + KMER_LENGTH]
            counter += 1
            fout.write(f">{counter}\n{kmer}\n")
        return counter

    with open(input_path, "r") as fin, open(output_path, "w") as fout:
        for line in fin:
            line = line.strip()
            if line.startswith(">"):
                if current_seq:
                    count = _flush(current_header, current_seq, fout, count)
                current_header = line
                current_seq = []
            elif line:
                current_seq.append(line)
        # Last record
        if current_seq:
            count = _flush(current_header, current_seq, fout, count)

    return count


def split_fasta_into_chunks(
    fasta_path: str, chunks_dir: str, seqs_per_chunk: int = 16_000_000
) -> list:
    """Split a large FASTA file into smaller chunk files for parallel processing.

    Returns a list of chunk file paths.
    """
    os.makedirs(chunks_dir, exist_ok=True)

    chunk_paths = []
    chunk_idx = 0
    seq_count = 0
    fout = None

    def _open_next():
        nonlocal chunk_idx, fout
        if fout:
            fout.close()
        chunk_idx += 1
        path = os.path.join(chunks_dir, f"chunk_{chunk_idx:04d}.fasta")
        chunk_paths.append(path)
        fout = open(path, "w")

    _open_next()

    with open(fasta_path, "r") as fin:
        for line in fin:
            if line.startswith(">"):
                seq_count += 1
                if seq_count > seqs_per_chunk:
                    _open_next()
                    seq_count = 1
            fout.write(line)

    if fout:
        fout.close()

    return chunk_paths


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Chop a protein FASTA into 9-mers")
    parser.add_argument("--input", required=True, help="Input protein FASTA")
    parser.add_argument("--output", required=True, help="Output 9-mer FASTA")
    parser.add_argument(
        "--split", type=int, default=0,
        help="If > 0, also split into chunks of this many sequences",
    )
    parser.add_argument("--chunks-dir", default="", help="Directory for chunk files")
    args = parser.parse_args()

    print(f"Chopping {args.input} into 9-mers → {args.output}")
    n = chop_fasta_to_9mers(args.input, args.output)
    print(f"Done. Wrote {n:,} 9-mers.")

    if args.split > 0:
        cdir = args.chunks_dir or os.path.join(os.path.dirname(args.output), "chunks")
        print(f"Splitting into chunks of {args.split:,} → {cdir}")
        paths = split_fasta_into_chunks(args.output, cdir, args.split)
        print(f"Created {len(paths)} chunk files.")
