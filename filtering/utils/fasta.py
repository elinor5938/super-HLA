"""
utils/fasta.py — FASTA file I/O helper.
"""


def write_to_fasta(output_path: str, peptides: list) -> None:
    """Writes a list of peptide sequences to a FASTA file.

    Each peptide is written as a FASTA entry where the header is the peptide
    sequence itself (a common convention for short peptide sets).

    Args:
        output_path: Destination file path. The ``.fasta`` extension is
            appended automatically if not already present.
        peptides: List of peptide sequence strings.

    Example:
        >>> write_to_fasta("/data/my_peptides", ["ALFPHIMTY", "RLMPIFNTY"])
        # Creates /data/my_peptides.fasta with 2 entries.
    """
    if not output_path.endswith(".fasta"):
        output_path = output_path + ".fasta"

    with open(output_path, "w") as fh:
        for peptide in peptides:
            fh.write(f">{peptide}\n")
            fh.write(f"{peptide}\n")
