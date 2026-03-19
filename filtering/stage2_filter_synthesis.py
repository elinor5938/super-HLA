"""
stage2_filter_synthesis.py — Filter peptides that are difficult to chemically synthesize.

After CD-HIT clustering (stage 1) we have ~8 400 candidate representative
peptides.  Not all of them are practical for wet-lab synthesis.  This stage
applies a set of rule-based filters to remove peptides with known synthesis
complications.

Filters applied (in order of priority, first match wins):
  1. **Q at N-terminus** — glutamine at position 1 causes cyclization artifacts.
  2. **MM** — two adjacent methionines are problematic for oxidation.
  3. **HH** — two adjacent histidines can cause metal chelation issues.
  4. **DG** — aspartate-glycine motif promotes aspartimide formation.
  5. **DD** — double aspartate motif.
  6. **GG** — double glycine reduces structural rigidity.
  7. **M + C + H simultaneously** — combination of hard-to-protect residues.
  8. **C + H** — cysteine-histidine pairing.
  9. **C + M** — cysteine-methionine pairing.
  10. **≥ 3× M or H total** — excessive methionine / histidine count.
  11. **Any amino acid repeated 3× consecutively** (e.g. AAA, GGG) — homopolymer
      runs degrade synthesis quality.

Peptides that pass all filters (``result_no_triple``) are written to a FASTA
file in ``STAGE2_OUTPUT_DIR`` for use in stage 3.

Expected output size (original dataset): ~6 599 peptides.
"""
import os

from filtering.config import STAGE2_OUTPUT_DIR
from filtering.constants import AMINO_ACID_LIST
from filtering.utils.fasta import write_to_fasta


def _is_difficult_to_synthesize(peptide: str) -> bool:
    """Returns True if the peptide should be excluded due to synthesis difficulty."""
    if peptide[0] == "Q":
        return True
    if "MM" in peptide:
        return True
    if "HH" in peptide:
        return True
    if "DG" in peptide:
        return True
    if "DD" in peptide:
        return True
    if "GG" in peptide:
        return True
    if "M" in peptide and "C" in peptide and "H" in peptide:
        return True
    if "C" in peptide and "H" in peptide:
        return True
    if "C" in peptide and "M" in peptide:
        return True
    if (peptide.count("M") + peptide.count("H")) >= 3:
        return True
    return False


def _has_triple_repeat(peptide: str) -> bool:
    """Returns True if any amino acid appears 3 or more times consecutively."""
    return any(aa * 3 in peptide for aa in AMINO_ACID_LIST)


def run_stage2(consensus_peptides: list) -> dict:
    """Filters out synthesis-difficult peptides from the stage 1 candidate set.

    Args:
        consensus_peptides: The representative peptide list from
            :func:`~filtering.stage1_cdhit_clustering.run_stage1`
            (``stage1_data["consensus_peptides"]``).

    Returns:
        A dictionary with the following keys:

        - ``"filtered_peptides"`` (list): Peptides that passed all filters.
          These are written to ``STAGE2_OUTPUT_DIR/result_no_triple.fasta``.
        - ``"filter_stats"`` (dict): Counts of peptides removed per filter
          category, sorted ascending by count.

        Validation target (original dataset):
          ``len(filtered_peptides)`` should be ~6 599.

    Side effects:
        Writes ``result_no_triple.fasta`` to ``STAGE2_OUTPUT_DIR``.
    """
    import sys

    if not consensus_peptides:
        print("[Stage 2] No peptides to filter.")
        return {"filtered_peptides": [], "filter_stats": {}}

    print(f"[Stage 2] Applying 11 synthesis-difficulty filters to {len(consensus_peptides)} peptides...")
    sys.stdout.flush()

    # Tally removal reasons
    stats = {
        "Q_n_terminus": 0,
        "MM_adjacent": 0,
        "HH_adjacent": 0,
        "DG_motif": 0,
        "DD_motif": 0,
        "GG_motif": 0,
        "M_C_H_combo": 0,
        "C_H_combo": 0,
        "C_M_combo": 0,
        "M_H_count_ge3": 0,
        "triple_repeat": 0,
    }

    kept_peptides = []

    for pep in consensus_peptides:
        if pep[0] == "Q":
            stats["Q_n_terminus"] += 1
        elif "MM" in pep:
            stats["MM_adjacent"] += 1
        elif "HH" in pep:
            stats["HH_adjacent"] += 1
        elif "DG" in pep:
            stats["DG_motif"] += 1
        elif "DD" in pep:
            stats["DD_motif"] += 1
        elif "GG" in pep:
            stats["GG_motif"] += 1
        elif "M" in pep and "C" in pep and "H" in pep:
            stats["M_C_H_combo"] += 1
        elif "C" in pep and "H" in pep:
            stats["C_H_combo"] += 1
        elif "C" in pep and "M" in pep:
            stats["C_M_combo"] += 1
        elif (pep.count("M") + pep.count("H")) >= 3:
            stats["M_H_count_ge3"] += 1
        else:
            kept_peptides.append(pep)

    removed_pass1 = len(consensus_peptides) - len(kept_peptides)
    print(f"[Stage 2]   Pass 1 (motif filters): {removed_pass1} removed, {len(kept_peptides)} remaining")
    sys.stdout.flush()

    # Second pass: remove triple repeats from the remaining set
    print(f"[Stage 2]   Pass 2: checking for triple amino acid repeats...")
    sys.stdout.flush()
    filtered_no_triple = [p for p in kept_peptides if not _has_triple_repeat(p)]
    stats["triple_repeat"] = len(kept_peptides) - len(filtered_no_triple)

    # Sorted ascending (least-filtered → most-filtered) for readability
    sorted_stats = dict(sorted(stats.items(), key=lambda item: item[1]))

    total_removed = len(consensus_peptides) - len(filtered_no_triple)
    print(f"[Stage 2] Result: {len(filtered_no_triple)} peptides passed ({total_removed} removed)")
    print(f"[Stage 2] Filter breakdown:")
    for filter_name, count in sorted_stats.items():
        if count > 0:
            print(f"[Stage 2]   {filter_name}: {count} removed")
    sys.stdout.flush()

    # Write FASTA output for stage 3
    os.makedirs(STAGE2_OUTPUT_DIR, exist_ok=True)
    output_fasta_path = os.path.join(STAGE2_OUTPUT_DIR, "result_no_triple")
    write_to_fasta(output_fasta_path, filtered_no_triple)
    print(f"[Stage 2] Output FASTA written to: {output_fasta_path}.fasta")

    return {
        "filtered_peptides": filtered_no_triple,
        "filter_stats": sorted_stats,
    }
