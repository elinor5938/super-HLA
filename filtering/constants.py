"""
Shared constants for the filtering pipeline.

These values define the HLA supertypes used throughout the study and the
standard amino acid alphabet. They are intentionally kept as plain Python
constants (not env-var driven) because they are scientific parameters that
do not change between environments — only between experiment designs.
"""

# ---------------------------------------------------------------------------
# HLA supertypes
# ---------------------------------------------------------------------------

SUPERTYPE_LIST = [
    "HLA-A*01:01",
    "HLA-A*02:01",
    "HLA-A*03:01",
    "HLA-A*24:02",
    "HLA-B*07:02",
    "HLA-B*08:01",
    "HLA-B*27:05",
    "HLA-B*40:01",
    "HLA-B*58:01",
    "HLA-B*15:01",
    "HLA-A*29:02",
    "HLA-A*30:01",
]
"""12 canonical HLA supertypes used as the binding coverage target."""

# NetMHCpan requires a slightly different notation (no asterisks) when passed
# on the command line via -a flag.
HLA_STR = (
    "HLA-A01:01,HLA-A02:01,HLA-A03:01,HLA-A24:02,HLA-A29:02,"
    "HLA-B07:02,HLA-B08:01,HLA-B27:05,HLA-A30:01,HLA-B40:01,"
    "HLA-B58:01,HLA-B15:01"
)
"""Comma-separated HLA string passed directly to netMHCpan -a flag."""

# MHCflurry also uses a different notation (no dashes/colons).
HLA_FLURRY_LIST = [
    "HLA-A0101", "HLA-A0201", "HLA-A0301", "HLA-A2402",
    "HLA-A2902", "HLA-B0702", "HLA-B0801", "HLA-B2705",
    "HLA-A3001", "HLA-B4001", "HLA-B5801", "HLA-B1501",
]
"""HLA identifiers in MHCflurry notation (no asterisks or colons)."""

# ---------------------------------------------------------------------------
# Amino acid alphabet
# ---------------------------------------------------------------------------

AMINO_ACID_LIST = [
    "A", "R", "N", "D", "C", "E", "Q", "G", "H", "I",
    "L", "K", "M", "F", "P", "S", "T", "W", "Y", "V",
]
"""Standard 20-letter amino acid alphabet."""

# ---------------------------------------------------------------------------
# Pipeline thresholds
# ---------------------------------------------------------------------------

MIN_HLA_BINDING_COUNT = 8
"""
Minimum number of HLA supertypes a peptide must bind to (score < 2) in order
to be considered a candidate super-binder in stage 0.
"""

CDHIT_SIMILARITY_THRESHOLD = 60
"""
Similarity threshold (as integer percentage) used in both CD-HIT clustering
rounds. Corresponds to the -c 0.60 flag passed to cd-hit.
"""
