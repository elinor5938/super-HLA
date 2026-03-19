#!/usr/bin/env python3
"""
run.py — Super-HLA Pipeline Orchestrator

A single entry point to run, monitor, and manage the entire Super-HLA pipeline.
Tracks which stages have been completed and guides you through the workflow.

Usage:
    python run.py              # Interactive menu
    python run.py --status     # Show pipeline status only
    python run.py --run-all    # Run all stages sequentially
    python run.py --stage 1    # Run a specific stage
"""
import argparse
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
from datetime import datetime

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
MCMC_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "mcmc", "output")
STATE_FILE = os.path.join(DATA_DIR, ".pipeline_state.json")

# Cross-platform venv Python path
if sys.platform == "win32":
    VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
else:
    VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")

# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------
_env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

# ---------------------------------------------------------------------------
# Terminal UI helpers
# ---------------------------------------------------------------------------
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"

# Status icons
DONE = f"{GREEN}\u2705{RESET}"
RUNNING = f"{YELLOW}\u23f3{RESET}"
PENDING = f"{DIM}\u25cb{RESET}"
FAILED = f"{RED}\u274c{RESET}"
SKIP = f"{CYAN}\u23ed{RESET}"

HEADER_ART = f"""{CYAN}{BOLD}
    \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
    \u2502     \U0001f9ec Super-HLA Analysis Pipeline \U0001f9ec        \u2502
    \u2502  Discover super-binder peptides for broad    \u2502
    \u2502  MHC class I HLA supertype binding            \u2502
    \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518{RESET}
"""

# ---------------------------------------------------------------------------
# Pipeline stage definitions
# ---------------------------------------------------------------------------
STAGES = [
    {
        "id": 1,
        "name": "MCMC Simulation",
        "description": "Explore peptide space via Markov Chain Monte Carlo",
        "module": "mcmc",
        "icon": "\U0001f3b2",
    },
    {
        "id": 2,
        "name": "Prepare Filtering Data",
        "description": "Combine MCMC seeds into robust_df + HLA mapping",
        "module": "prepare",
        "icon": "\U0001f4e6",
    },
    {
        "id": 3,
        "name": "Filtering Pipeline",
        "description": "CD-HIT clustering \u2192 synthesis filter \u2192 MHC cross-validation",
        "module": "filtering",
        "icon": "\U0001f52c",
    },
    {
        "id": 4,
        "name": "Self-Similarity Analysis",
        "description": "Remove candidates similar to human proteome peptides",
        "module": "self_similarity",
        "icon": "\U0001f9ec",
    },
]


# ---------------------------------------------------------------------------
# Pipeline state management
# ---------------------------------------------------------------------------
def _load_state() -> dict:
    """Load pipeline state from disk."""
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_state(state: dict) -> None:
    """Persist pipeline state to disk."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _update_stage_state(stage_id: int, status: str, details: str = "") -> None:
    """Update a single stage's state."""
    state = _load_state()
    state[str(stage_id)] = {
        "status": status,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "details": details,
    }
    _save_state(state)


# ---------------------------------------------------------------------------
# Detect what has already been completed (from data on disk)
# ---------------------------------------------------------------------------
def _detect_stage_status() -> dict:
    """Auto-detect pipeline status from files on disk."""
    status = {}

    # Stage 1: MCMC — check for output CSVs
    mcmc_csvs = []
    if os.path.isdir(MCMC_OUTPUT_DIR):
        mcmc_csvs = [f for f in os.listdir(MCMC_OUTPUT_DIR) if f.endswith(".csv")]
    if mcmc_csvs:
        seeds = [f.removesuffix(".csv") for f in sorted(mcmc_csvs)]
        status[1] = {
            "complete": True,
            "details": f"{len(mcmc_csvs)} seed(s): {', '.join(seeds[:5])}{'...' if len(seeds) > 5 else ''}",
        }
    else:
        status[1] = {"complete": False, "details": "No MCMC output CSVs found"}

    # Stage 2: Prepare — check for robust_df.csv and pickle
    robust_csv = os.path.join(DATA_DIR, "robust_df.csv")
    hla_pickle = os.path.join(DATA_DIR, "all_hla_combinations.pickle")
    if os.path.isfile(robust_csv) and os.path.isfile(hla_pickle):
        import pandas as pd
        try:
            df = pd.read_csv(robust_csv, nrows=0)
            row_count = sum(1 for _ in open(robust_csv)) - 1
            with open(hla_pickle, "rb") as f:
                combos = pickle.load(f)
            status[2] = {
                "complete": True,
                "details": f"{row_count} peptides, {len(combos)} HLA combinations",
            }
        except Exception:
            status[2] = {"complete": True, "details": "Files exist"}
    else:
        status[2] = {"complete": False, "details": "robust_df.csv or HLA pickle missing"}

    # Stage 3: Filtering — check for memoized stage results or stage2 output
    stage2_dir = os.environ.get("STAGE2_OUTPUT_DIR", os.path.join(DATA_DIR, "stage2-files"))
    memoization_dir = os.environ.get("MEMOIZATION_DIR", os.path.join(DATA_DIR, "memoization"))

    # Count memoized stage pickles (stored in subdirectories like stage-0/, stage-1/, etc.)
    memo_stages = []
    if os.path.isdir(memoization_dir):
        for entry in sorted(os.listdir(memoization_dir)):
            sub = os.path.join(memoization_dir, entry)
            if os.path.isdir(sub) and entry.startswith("stage"):
                memo_stages.append(entry)

    stage2_files = []
    if os.path.isdir(stage2_dir):
        stage2_files = [f for f in os.listdir(stage2_dir)
                        if f.endswith((".csv", ".fasta"))]

    if memo_stages or stage2_files:
        parts = []
        if memo_stages:
            parts.append(f"memoized: {', '.join(memo_stages)}")
        if stage2_files:
            parts.append(f"{len(stage2_files)} stage-2 output(s)")
        status[3] = {"complete": True, "details": ", ".join(parts)}
    else:
        status[3] = {"complete": False, "details": "No filtering outputs found"}

    # Stage 4: Self-similarity
    needle_dir = os.path.join(DATA_DIR, "needle")
    summary_json = os.path.join(needle_dir, "self_similarity_summary.json")
    if os.path.isfile(summary_json):
        try:
            with open(summary_json) as f:
                summary = json.load(f)
            safe = summary.get("safe_count", "?")
            removed = summary.get("removed_count", "?")
            status[4] = {
                "complete": True,
                "details": f"{safe} safe, {removed} removed",
            }
        except Exception:
            status[4] = {"complete": True, "details": "Summary exists"}
    else:
        # Check if pre-computed alignments are available
        alignment_json = os.environ.get(
            "ALIGNMENT_RESULTS_JSON",
            os.path.join(needle_dir, "alignment_results.json"),
        )
        if os.path.isfile(alignment_json):
            status[4] = {"complete": False, "details": "Pre-computed alignments ready, not yet analyzed"}
        else:
            status[4] = {"complete": False, "details": "No alignment data found"}

    return status


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------
def _print_divider(char="\u2500", width=56):
    print(f"    {DIM}{char * width}{RESET}")


def print_status():
    """Print the full pipeline status dashboard."""
    print(HEADER_ART)
    detected = _detect_stage_status()
    saved = _load_state()

    print(f"    {BOLD}Pipeline Status{RESET}")
    _print_divider()
    print()

    for stage in STAGES:
        sid = stage["id"]
        det = detected.get(sid, {"complete": False, "details": ""})

        # Use saved state if we have a more recent failure/running indicator
        saved_stage = saved.get(str(sid), {})
        saved_status = saved_stage.get("status", "")

        if saved_status == "running":
            icon = RUNNING
            label = f"{YELLOW}RUNNING{RESET}"
        elif saved_status == "failed":
            icon = FAILED
            label = f"{RED}FAILED{RESET}"
        elif det["complete"]:
            icon = DONE
            label = f"{GREEN}DONE{RESET}"
        else:
            icon = PENDING
            label = f"{DIM}PENDING{RESET}"

        # Stage header
        print(f"    {icon}  {BOLD}Stage {sid}{RESET}: {stage['icon']}  {stage['name']}  [{label}]")
        print(f"       {DIM}{stage['description']}{RESET}")

        # Details
        detail_text = det["details"]
        if saved_status == "failed" and saved_stage.get("details"):
            detail_text = saved_stage["details"]
        if saved_status == "running" and saved_stage.get("timestamp"):
            detail_text = f"Started at {saved_stage['timestamp']}"
        if detail_text:
            print(f"       {DIM}\u2514\u2500 {detail_text}{RESET}")
        print()

    _print_divider()

    # Prerequisites summary
    prereqs_ok = True
    prereq_issues = []
    if not shutil.which("needle"):
        prereq_issues.append("EMBOSS needle not installed")
        prereqs_ok = False
    if not shutil.which("cd-hit"):
        prereq_issues.append("cd-hit not installed")
        prereqs_ok = False
    if not shutil.which("docker"):
        prereq_issues.append("Docker not installed")
    elif subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode != 0:
        prereq_issues.append("Docker daemon not running")

    if prereq_issues:
        print(f"\n    {YELLOW}\u26a0  Prereqs:{RESET} {', '.join(prereq_issues)}")
    print()


def print_menu():
    """Print the interactive menu."""
    print(f"    {BOLD}What would you like to do?{RESET}")
    _print_divider()
    print()
    print(f"    {WHITE}[1]{RESET}  {STAGES[0]['icon']}  Run MCMC Simulation")
    print(f"    {WHITE}[2]{RESET}  {STAGES[1]['icon']}  Prepare Filtering Data")
    print(f"    {WHITE}[3]{RESET}  {STAGES[2]['icon']}  Run Filtering Pipeline")
    print(f"    {WHITE}[4]{RESET}  {STAGES[3]['icon']}  Run Self-Similarity Analysis")
    print()
    _print_divider()
    print(f"    {WHITE}[a]{RESET}  \U0001f680  Run ALL stages sequentially")
    print(f"    {WHITE}[v]{RESET}  \U0001f50d  Validate setup (prerequisites check)")
    print(f"    {WHITE}[s]{RESET}  \U0001f4ca  Show status dashboard")
    print(f"    {WHITE}[r]{RESET}  \U0001f504  Reset pipeline state")
    print(f"    {WHITE}[q]{RESET}  \U0001f6aa  Quit")
    print()
    _print_divider()


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------
def _print_stage_header(stage: dict, extra: str = ""):
    print()
    print(f"    {BOLD}\u2550\u2550\u2550 Stage {stage['id']}: {stage['icon']}  {stage['name']} \u2550\u2550\u2550{RESET}")
    if extra:
        print(f"    {DIM}{extra}{RESET}")
    print()


def _print_stage_done(stage: dict, elapsed: float, summary: str = ""):
    print()
    print(f"    {DONE}  {BOLD}Stage {stage['id']} complete{RESET}  {DIM}({elapsed:.1f}s){RESET}")
    if summary:
        print(f"    {DIM}\u2514\u2500 {summary}{RESET}")
    print()


def _print_stage_failed(stage: dict, error: str):
    print()
    print(f"    {FAILED}  {BOLD}Stage {stage['id']} failed{RESET}")
    for line in str(error).split("\n"):
        print(f"    {RED}{line}{RESET}")
    print()


def run_stage_1(seeds: list = None, accepted: int = 100):
    """Run MCMC simulation for one or more seeds."""
    stage = STAGES[0]
    if seeds is None:
        seeds = [1]

    _print_stage_header(stage, f"Seeds: {seeds}, accepted target: {accepted}")
    _update_stage_state(1, "running")

    try:
        # We need to be in the mcmc directory context
        mcmc_main = os.path.join(PROJECT_ROOT, "mcmc", "main.py")
        interpreter = VENV_PYTHON if os.path.isfile(VENV_PYTHON) else sys.executable

        t_start = time.time()

        for i, seed in enumerate(seeds):
            print(f"    {RUNNING}  Seed {seed} ({i+1}/{len(seeds)})...")

            result = subprocess.run(
                [interpreter, mcmc_main, "--mode", "random",
                 "--seed", str(seed), "--accepted", str(accepted)],
                capture_output=True, text=True, timeout=3600,
            )

            if result.returncode != 0:
                stderr = result.stderr.strip().split("\n")[-1] if result.stderr else "Unknown error"
                raise RuntimeError(f"Seed {seed} failed: {stderr}")

            csv_path = os.path.join(MCMC_OUTPUT_DIR, f"{seed}.csv")
            if os.path.isfile(csv_path):
                print(f"    {DONE}  Seed {seed} \u2192 {os.path.basename(csv_path)}")
            else:
                print(f"    {DONE}  Seed {seed} completed")

        elapsed = time.time() - t_start
        _update_stage_state(1, "done", f"{len(seeds)} seed(s) completed")
        _print_stage_done(stage, elapsed, f"{len(seeds)} seed(s) completed")
        return True

    except Exception as e:
        _update_stage_state(1, "failed", str(e))
        _print_stage_failed(stage, str(e))
        return False


def run_stage_2():
    """Run prepare_filtering_data.py."""
    stage = STAGES[1]
    _print_stage_header(stage)
    _update_stage_state(2, "running")

    try:
        t_start = time.time()

        prep_script = os.path.join(PROJECT_ROOT, "prepare_filtering_data.py")
        interpreter = VENV_PYTHON if os.path.isfile(VENV_PYTHON) else sys.executable

        result = subprocess.run(
            [interpreter, prep_script],
            capture_output=True, text=True, timeout=300,
        )

        if result.returncode != 0:
            error_output = result.stderr.strip() if result.stderr else ""
            if not error_output:
                error_output = result.stdout.strip() if result.stdout else "Unknown error (no output)"
            raise RuntimeError(error_output)

        # Print captured output indented
        for line in result.stdout.strip().split("\n"):
            print(f"    {DIM}{line}{RESET}")

        elapsed = time.time() - t_start

        # Get details
        robust_csv = os.path.join(DATA_DIR, "robust_df.csv")
        details = ""
        if os.path.isfile(robust_csv):
            row_count = sum(1 for _ in open(robust_csv)) - 1
            details = f"{row_count} unique peptides prepared"

        _update_stage_state(2, "done", details)
        _print_stage_done(stage, elapsed, details)
        return True

    except Exception as e:
        _update_stage_state(2, "failed", str(e))
        _print_stage_failed(stage, str(e))
        return False


def run_stage_3():
    """Run the filtering pipeline."""
    stage = STAGES[2]
    _print_stage_header(stage, "Stages: load \u2192 CD-HIT \u2192 synthesis filter \u2192 MHC cross-validation")
    _update_stage_state(3, "running")

    try:
        t_start = time.time()

        interpreter = VENV_PYTHON if os.path.isfile(VENV_PYTHON) else sys.executable

        result = subprocess.run(
            [interpreter, "-m", "filtering.main"],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=7200,
        )

        if result.returncode != 0:
            error_output = result.stderr.strip() if result.stderr else ""
            if not error_output:
                error_output = result.stdout.strip() if result.stdout else "Unknown error (no output)"
            raise RuntimeError(error_output)

        # Show output, highlighting key lines
        for line in result.stdout.strip().split("\n"):
            if line.startswith("=") or "Pipeline Complete" in line:
                print(f"    {BOLD}{line}{RESET}")
            elif "Stage" in line and "]" in line:
                print(f"    {CYAN}{line}{RESET}")
            else:
                print(f"    {DIM}{line}{RESET}")

        elapsed = time.time() - t_start
        _update_stage_state(3, "done")
        _print_stage_done(stage, elapsed)
        return True

    except Exception as e:
        _update_stage_state(3, "failed", str(e))
        _print_stage_failed(stage, str(e))
        return False


def run_stage_4():
    """Run self-similarity analysis."""
    stage = STAGES[3]
    _print_stage_header(stage)
    _update_stage_state(4, "running")

    try:
        t_start = time.time()

        interpreter = VENV_PYTHON if os.path.isfile(VENV_PYTHON) else sys.executable

        result = subprocess.run(
            [interpreter, "-m", "self_similarity.main"],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=86400,  # can be very long
        )

        if result.returncode != 0:
            error_output = result.stderr.strip() if result.stderr else ""
            if not error_output:
                error_output = result.stdout.strip() if result.stdout else "Unknown error (no output)"
            raise RuntimeError(error_output)

        for line in result.stdout.strip().split("\n"):
            if "Results:" in line or "==" in line:
                print(f"    {BOLD}{line}{RESET}")
            elif "Safe peptides" in line or "Removed" in line or "written to" in line:
                print(f"    {GREEN}{line}{RESET}")
            else:
                print(f"    {DIM}{line}{RESET}")

        elapsed = time.time() - t_start

        # Get summary details
        summary_path = os.path.join(DATA_DIR, "needle", "self_similarity_summary.json")
        details = ""
        if os.path.isfile(summary_path):
            with open(summary_path) as f:
                summary = json.load(f)
            details = f"{summary['safe_count']} safe, {summary['removed_count']} removed"

        _update_stage_state(4, "done", details)
        _print_stage_done(stage, elapsed, details)
        return True

    except Exception as e:
        _update_stage_state(4, "failed", str(e))
        _print_stage_failed(stage, str(e))
        return False


def run_validation():
    """Run validate_setup.py and show results."""
    print()
    print(f"    {BOLD}\u2550\u2550\u2550 \U0001f50d  Setup Validation \u2550\u2550\u2550{RESET}")
    print()

    venv_python = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    interpreter = venv_python if os.path.isfile(venv_python) else sys.executable

    result = subprocess.run(
        [interpreter, os.path.join(PROJECT_ROOT, "validate_setup.py")],
        capture_output=True, text=True, timeout=120,
    )
    print(result.stdout)
    if result.stderr:
        print(f"    {RED}{result.stderr}{RESET}")


def run_all():
    """Run all stages sequentially."""
    print()
    print(f"    {BOLD}\U0001f680 Running full pipeline...{RESET}")
    print()

    detected = _detect_stage_status()

    # Stage 1: MCMC — skip if already has data
    if detected.get(1, {}).get("complete"):
        print(f"    {SKIP}  Stage 1 (MCMC): Already has data \u2014 skipping")
        print(f"       {DIM}\u2514\u2500 {detected[1]['details']}{RESET}")
    else:
        print(f"    {RUNNING}  Stage 1: Running MCMC with default settings (seed=1, accepted=100)...")
        if not run_stage_1(seeds=[1], accepted=100):
            print(f"\n    {RED}Pipeline stopped at Stage 1.{RESET}")
            return

    # Stage 2: Prepare
    if detected.get(2, {}).get("complete"):
        print(f"    {SKIP}  Stage 2 (Prepare): Already prepared \u2014 skipping")
        print(f"       {DIM}\u2514\u2500 {detected[2]['details']}{RESET}")
    else:
        if not run_stage_2():
            print(f"\n    {RED}Pipeline stopped at Stage 2.{RESET}")
            return

    # Stage 3: Filtering
    if detected.get(3, {}).get("complete"):
        print(f"    {SKIP}  Stage 3 (Filtering): Already completed \u2014 skipping")
        print(f"       {DIM}\u2514\u2500 {detected[3]['details']}{RESET}")
    else:
        if not run_stage_3():
            print(f"\n    {RED}Pipeline stopped at Stage 3.{RESET}")
            return

    # Stage 4: Self-similarity
    if detected.get(4, {}).get("complete"):
        print(f"    {SKIP}  Stage 4 (Self-similarity): Already completed \u2014 skipping")
        print(f"       {DIM}\u2514\u2500 {detected[4]['details']}{RESET}")
    else:
        if not run_stage_4():
            print(f"\n    {RED}Pipeline stopped at Stage 4.{RESET}")
            return

    print()
    print(f"    {BOLD}{GREEN}\U0001f389 Full pipeline completed successfully!{RESET}")
    print()


def reset_state():
    """Reset the pipeline state tracking."""
    if os.path.isfile(STATE_FILE):
        os.remove(STATE_FILE)
    print(f"\n    {DONE}  Pipeline state reset.\n")
    print(f"    {DIM}Note: This only clears the state tracker, not the data files.")
    print(f"    To re-run a stage, its output data is still on disk (use it or delete it).{RESET}\n")


# ---------------------------------------------------------------------------
# MCMC seed prompt
# ---------------------------------------------------------------------------
def _prompt_mcmc_params() -> tuple:
    """Ask the user for MCMC parameters."""
    print()
    print(f"    {BOLD}MCMC Configuration{RESET}")
    _print_divider()

    seeds_input = input(f"    Seeds (comma-separated, e.g. 1,2,3) [{CYAN}1{RESET}]: ").strip()
    if not seeds_input:
        seeds = [1]
    else:
        try:
            seeds = [int(s.strip()) for s in seeds_input.split(",")]
        except ValueError:
            print(f"    {RED}Invalid input. Using seed=1.{RESET}")
            seeds = [1]

    accepted_input = input(f"    Accepted peptides per seed [{CYAN}100{RESET}]: ").strip()
    if not accepted_input:
        accepted = 100
    else:
        try:
            accepted = int(accepted_input)
        except ValueError:
            print(f"    {RED}Invalid input. Using accepted=100.{RESET}")
            accepted = 100

    return seeds, accepted


# ---------------------------------------------------------------------------
# Interactive main loop
# ---------------------------------------------------------------------------
def interactive():
    """Run the interactive menu loop."""
    print_status()

    while True:
        print_menu()
        choice = input(f"    {BOLD}\u276f{RESET} ").strip().lower()

        if choice == "1":
            seeds, accepted = _prompt_mcmc_params()
            run_stage_1(seeds=seeds, accepted=accepted)
        elif choice == "2":
            run_stage_2()
        elif choice == "3":
            run_stage_3()
        elif choice == "4":
            run_stage_4()
        elif choice == "a":
            run_all()
        elif choice == "v":
            run_validation()
        elif choice == "s":
            print_status()
        elif choice == "r":
            reset_state()
        elif choice in ("q", "quit", "exit"):
            print(f"\n    {DIM}Goodbye! \U0001f44b{RESET}\n")
            break
        else:
            print(f"\n    {RED}Unknown option: '{choice}'{RESET}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Super-HLA Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run without arguments for interactive mode.",
    )
    parser.add_argument("--status", action="store_true", help="Show pipeline status and exit")
    parser.add_argument("--run-all", action="store_true", help="Run all stages sequentially")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3, 4], help="Run a specific stage")
    parser.add_argument("--seeds", type=str, default="1", help="MCMC seeds (comma-separated, for stage 1)")
    parser.add_argument("--accepted", type=int, default=100, help="MCMC accepted count (for stage 1)")
    parser.add_argument("--reset", action="store_true", help="Reset pipeline state tracker")

    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.reset:
        reset_state()
    elif args.run_all:
        print(HEADER_ART)
        run_all()
    elif args.stage:
        print(HEADER_ART)
        if args.stage == 1:
            seeds = [int(s.strip()) for s in args.seeds.split(",")]
            run_stage_1(seeds=seeds, accepted=args.accepted)
        elif args.stage == 2:
            run_stage_2()
        elif args.stage == 3:
            run_stage_3()
        elif args.stage == 4:
            run_stage_4()
    else:
        interactive()


if __name__ == "__main__":
    main()
