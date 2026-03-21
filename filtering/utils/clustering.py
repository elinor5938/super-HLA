"""
utils/clustering.py — CD-HIT output parser.

CD-HIT is an external clustering tool that groups similar sequences by a
similarity threshold.  Its output is a text file with a ``.clstr`` extension.
This module provides a single function that parses that file into a tidy
pandas DataFrame so the rest of the pipeline can work with it in a
predictable, structured way.
"""
import re
from itertools import groupby

import pandas as pd


def parse_cdhit_clusters(cluster_file_path: str) -> pd.DataFrame:
    """Parses a CD-HIT ``.clstr`` output file into a pandas DataFrame.

    Each row in the returned DataFrame corresponds to one peptide that
    appeared in the clustering.  The DataFrame includes cluster membership,
    cluster size, and whether each peptide was selected as the cluster
    representative (consensus).

    Args:
        cluster_file_path: Absolute path to the ``.clstr`` file produced by
            the ``cd-hit`` command.

    Returns:
        A DataFrame with the following columns:

        - ``cluster_n`` (int): Cluster number (1-indexed).
        - ``cluster_size`` (int | str): Number of sequences in the cluster,
          or the string ``"Singleton"`` for single-member clusters.
        - ``is_consensus`` (str): ``"yes"`` if this peptide is the cluster
          representative, ``"No"`` otherwise.
        - ``sim_to_is_consensus`` (str): Percentage similarity to the
          representative, or ``"consensus"`` for the representative itself.

        The DataFrame index is the peptide sequence.

    Example:
        >>> df = parse_cdhit_clusters("/data/cluster1/output/combo1_60_thresh.fasta.myout.clstr")
        >>> print(df.head())
    """
    with open(cluster_file_path, "r+") as cfh:
        # Split the file into per-cluster groups, skipping the ">Cluster N" header lines
        full_data = [
            list(group)
            for key, group in groupby(cfh, lambda line: line.startswith(">Cluster"))
            if not key
        ]

    # Extract peptide IDs from each cluster: lines look like ">PEPTIDENAME..."
    nested_cluster_peps = [
        re.findall(r">(.*)\.\.\.", "".join(g)) for g in full_data
    ]

    # Extract similarity percentages for non-representative members
    clus_peps_nums = [
        re.findall(r"[A-Z]{9}.{3} at \d+\.\d+\%", "".join(g)) for g in full_data
    ]
    percent_similarity: dict = {}
    for group in clus_peps_nums:
        for match in group:
            identity = re.findall(r"[A-Z]{9}.{3} at \d+\.\d+\%", match)[0]
            peptide_key = re.findall(r"[A-Z]{9}", identity)[0]
            sim_value = re.findall(r"\d+\.\d+\%", identity)[0]
            percent_similarity[peptide_key] = sim_value

    # Build flat lists for constructing the DataFrame
    cluster_size_col = []
    cluster_num_col = []
    peptide_col = []

    for i, cluster in enumerate(nested_cluster_peps):
        cluster_num_col.extend([i + 1] * len(cluster))
        if len(cluster) > 1:
            for pep in cluster:
                peptide_col.append(pep.lstrip(" "))
                cluster_size_col.append(len(cluster))
        else:
            peptide_col.append(cluster[0].lstrip(" "))
            cluster_size_col.append(1)

    result_df = pd.DataFrame(
        index=peptide_col,
        columns=["is_consensus", "sim_to_is_consensus"],
    )

    for pep in result_df.index:
        if pep in percent_similarity:
            result_df.at[pep, "is_consensus"] = False
            result_df.at[pep, "sim_to_is_consensus"] = percent_similarity[pep]
        else:
            result_df.at[pep, "is_consensus"] = True
            result_df.at[pep, "sim_to_is_consensus"] = "consensus"

    result_df["cluster_n"] = cluster_num_col
    result_df["cluster_size"] = cluster_size_col

    return result_df
