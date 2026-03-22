"""
filtering/self_similarity/filter_self.py — Filter candidate peptides by self-similarity.

Removes peptides that are too similar to sequences naturally found in the
human proteome.  A peptide is flagged as "similar to self" if any alignment
in the needle results meets:
    similarity >= SIMILARITY_THRESHOLD (default 8 out of 9)
    OR
    identity >= IDENTITY_THRESHOLD (default 7 out of 9)
"""
import pandas as pd
from typing import Dict, List, Set, Tuple

from filtering.self_similarity.config import IDENTITY_THRESHOLD, SIMILARITY_THRESHOLD


def find_self_similar_peptides(
    alignment_df: pd.DataFrame,
    similarity_threshold: int = SIMILARITY_THRESHOLD,
    identity_threshold: int = IDENTITY_THRESHOLD,
) -> Tuple[Set[str], Set[str], pd.DataFrame]:
    """Identify peptides that are too similar to self.

    Args:
        alignment_df: DataFrame with columns: pep, identity, similarity, score,
                      and optionally fasta_seq_string.
        similarity_threshold: Minimum similarity count to flag (default 8).
        identity_threshold: Minimum identity count to flag (default 7).

    Returns:
        A tuple of:
            - self_similar_peptides: Set of peptide sequences flagged as self-similar.
            - similar_human_peptides: Set of human peptides that matched.
            - filtered_df: The subset of alignment_df that triggered the flags.
    """
    mask = (
        alignment_df["similarity"].isin(range(similarity_threshold, 10))
        | alignment_df["identity"].isin(range(identity_threshold, 10))
    )
    filtered_df = alignment_df[mask].copy()

    self_similar_peptides = set(filtered_df["pep"].unique())

    similar_human_peptides = set()
    if "fasta_seq_string" in filtered_df.columns:
        similar_human_peptides = set(
            filtered_df["fasta_seq_string"].dropna().unique()
        )

    return self_similar_peptides, similar_human_peptides, filtered_df


def filter_candidates(
    candidate_peptides: List[str],
    self_similar_peptides: Set[str],
) -> Tuple[List[str], List[str]]:
    """Split candidates into safe and self-similar lists.

    Returns:
        (safe_peptides, removed_peptides)
    """
    safe = [p for p in candidate_peptides if p not in self_similar_peptides]
    removed = [p for p in candidate_peptides if p in self_similar_peptides]
    return safe, removed
