# Filtering Pipeline — Super-HLA

This module implements the **four-stage peptide filtering pipeline** that takes raw MCMC simulation output and progressively narrows it down to a high-confidence set of super-binder candidates.

> [!NOTE]
> **Prerequisite:** The MCMC stage must have been run first and produced simulation output CSVs. Configure all filtering `.env` variables before running.

---

## 🔄 Pipeline Overview

The filtering pipeline takes ~10 000s of peptides produced by the MCMC simulation and reduces them to a few thousand high-confidence HLA super-binders through four sequential stages:

```mermaid
flowchart TD
    A([Input: MCMC Simulation CSVs]) --> S0

    subgraph Stage 0 - Load Data
        S0["Load robust_df<br/>Load df_dict<br/>Load all_hla_combinations"]
        S0 --> S0b["get_peptides_by_hla_threshold<br/>min 8 HLA supertypes"]
    end

    S0b -->|"~471 HLA combos<br/>each with peptide lists"| S1

    subgraph Stage 1 - CD-HIT Clustering
        S1["Round 1: cluster per HLA combination<br/>at 60 pct similarity"]
        S1 -->|"select_cluster_consensus<br/>per cluster"| S1b
        S1b["Flatten all consensus<br/>peptides ~55k"]
        S1b --> S1c["Round 2: global re-cluster<br/>at 60 pct similarity"]
        S1c -->|select_cluster_consensus| S1d["Final representative set<br/>~8400 peptides"]
    end

    S1d --> S2

    subgraph Stage 2 - Synthesis Filter
        S2{"Apply rule-based filters<br/>Q N-terminus, MM, HH, DG, DD, GG<br/>M+C+H, C+H, C+M, 3x M/H, triple repeats"}
        S2 -->|"Removed: ~1800"| Trash1[Discarded]
        S2 -->|Kept| S2b["Synthesis-feasible peptides<br/>~6600"]
    end

    S2b --> S3
    S2b -->|write_to_fasta| FASTA[(result_no_triple.fasta)]

    subgraph Stage 3 - MHC Cross-Validation
        S3[Run 3 predictors on FASTA]
        S3 --> P1[netMHCpan 4.1]
        S3 --> P2[netMHCpan 4.0]
        S3 --> P3[MHCflurry]
        P1 & P2 & P3 --> Score["Compute one_side_mean<br/>per predictor"]
        Score --> Top["Select top 3000<br/>per predictor"]
    end

    Top --> Out(["Output: top_net41, top_net40, top_flurry"])
```

---

## ⚙️ Configuration

All paths are configured via the root `.env` file. Copy the commented-out variables from `.env` and fill in your actual paths:

| Variable | Description |
|----------|-------------|
| `ROBUST_DF_CSV_PATH` | Path to `all_data_frames_sims_october.csv` |
| `SIMULATION_CSV_DIR` | Directory of per-seed MCMC simulation CSVs |
| `HLA_COMBINATIONS_PICKLE` | Path to `all_hla_cominations.pickle` |
| `MEMOIZATION_DIR` | Root directory for all pickle caches |
| `CDHIT_CLUSTER1_INPUT_DIR` | FASTA input dir for cluster round 1 |
| `CDHIT_CLUSTER1_OUTPUT_DIR` | CD-HIT output dir for cluster round 1 |
| `CDHIT_CLUSTER2_INPUT_DIR` | FASTA input dir for cluster round 2 |
| `CDHIT_CLUSTER2_OUTPUT_DIR` | CD-HIT output dir for cluster round 2 |
| `STAGE2_OUTPUT_DIR` | Directory for stage 2 FASTA output |
| `NETMHCPAN_40_DIR_PATH` | Path to netMHCpan 4.0 binary directory |

---

## 🚀 How to Run

```bash
python filtering/main.py
```

The pipeline will print progress and counts after each stage. Memoized results are loaded from the `MEMOIZATION_DIR` automatically — re-runs only recompute what's missing.

### Expected Progress (original dataset)

| Stage | Output Count |
|-------|-------------|
| Stage 0 — Threshold peptides | ~471 HLA combinations |
| Stage 1 Round 1 — Flat consensus | ~55 066 peptides |
| Stage 1 Round 2 — Representatives | ~8 435 rows |
| Stage 2 — Synthesis-feasible | ~6 599 peptides |
| Stage 3 — Top 3000 per predictor | 3 000 × 3 lists |

---

## 📁 Module Breakdown

```
filtering/
├── main.py                       # Orchestration entry point
├── config.py                     # .env loader → Python constants
├── constants.py                  # Shared scientific constants (HLA list, thresholds)
├── stage0_load_data.py           # Load MCMC output and HLA combination map
├── stage1_cdhit_clustering.py    # Two-round CD-HIT sequence clustering
├── stage2_filter_synthesis.py    # Rule-based synthesis difficulty filter
├── stage3_validate_mhc_predictions.py  # MHC binding cross-validation
└── utils/
    ├── fasta.py                  # FASTA file writer
    ├── memoize.py                # Pickle-based result caching
    ├── clustering.py             # CD-HIT .clstr output parser
    ├── scoring.py                # Binding score helpers + DataFrame loaders
    └── prediction.py             # MHC predictor wrappers (netMHCpan + MHCflurry)
```

---

## 🔧 External Tool Requirements

| Tool | Used in | Install |
|------|---------|---------|
| `cd-hit` | Stage 1 | `brew install cd-hit` (macOS) |
| `netMHCpan 4.1` | Stage 3 | [DTU download page](https://services.healthtech.dtu.dk/) |
| `netMHCpan 4.0` | Stage 3 | Same DTU page (optional, for cross-validation) |
| `mhcflurry` | Stage 3 | `pip install mhcflurry && mhcflurry-downloads fetch` |

---

## 🗒️ Known TODOs

- **Stage 3 — Cross-predictor intersection**: The original analysis selected peptides that ranked in the top N across *all three* predictors simultaneously. This logic was incomplete in the legacy code and is marked as a `TODO` in `stage3_validate_mhc_predictions.py`.
