"""
validate_setup.py -- Check that all prerequisites for the super-HLA pipeline are met.

Usage (from project root):
    python validate_setup.py

Can also be imported and called programmatically:
    from validate_setup import validate
    report = validate()
    if not report["all_ok"]:
        print("Setup incomplete — see report['checks'] for details.")
"""
import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# Resolve project root and load .env (same logic as the pipeline itself)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

def _load_env(env_path: str) -> None:
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

_load_env(os.path.join(PROJECT_ROOT, ".env"))


# ---------------------------------------------------------------------------
# Individual check functions — each returns (ok: bool, message: str)
# ---------------------------------------------------------------------------

def _check_python_version():
    v = sys.version_info
    ok = v >= (3, 10)
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    if ok:
        return True, f"Python {ver_str}"
    return False, f"Python {ver_str} (need 3.10+)"


def _check_venv():
    venv_python = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    if os.path.isfile(venv_python):
        return True, f"Found at .venv/"
    return False, "Virtual environment not found. Run: python3.10 -m venv .venv"


def _check_pip_packages():
    missing = []
    # Package name -> import name (when they differ)
    required = ["pandas", "numpy", "Bio", "matplotlib", "seaborn"]
    venv_python = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    interpreter = venv_python if os.path.isfile(venv_python) else sys.executable
    for pkg in required:
        try:
            subprocess.run(
                [interpreter, "-c", f"import {pkg}"],
                capture_output=True, check=True, timeout=10,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            missing.append(pkg)
    if not missing:
        return True, "All core packages installed"
    return False, f"Missing: {', '.join(missing)}. Run: pip install -r requirements.txt"


def _check_env_file():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.isfile(env_path):
        return True, env_path
    return False, "No .env file found at project root"


def _check_env_var(var_name: str, must_exist_on_disk: bool = True, is_dir: bool = False):
    """Returns (ok, message) for a single .env variable."""
    val = os.environ.get(var_name, "")
    if not val:
        return False, f"Not set in .env"
    if val.startswith("/path/to"):
        return False, f"Still has placeholder value: {val}"
    if must_exist_on_disk:
        if is_dir and not os.path.isdir(val):
            return False, f"Directory not found: {val}"
        elif not is_dir and not os.path.isfile(val):
            return False, f"File not found: {val}"
    return True, val


def _check_netmhcpan_executable(install_dir: str, label: str):
    """Check that a netMHCpan installation has a working executable."""
    if not install_dir or install_dir.startswith("/path/to"):
        return False, "Not configured"
    if not os.path.isdir(install_dir):
        return False, f"Directory not found: {install_dir}"

    # Find the best executable (same logic as the pipeline)
    for wrapper in ("netMHCpan_docker", "netMHCpan_darwin_arm64", "netMHCpan"):
        path = os.path.join(install_dir, wrapper)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return True, f"Using {wrapper} in {install_dir}"

    return False, f"No executable found in {install_dir}"


def _check_cdhit():
    if shutil.which("cd-hit"):
        return True, shutil.which("cd-hit")
    return False, "Not found on PATH. Install: brew install cd-hit"


def _check_needle():
    if shutil.which("needle"):
        return True, shutil.which("needle")
    return False, "Not found on PATH. Install: brew install emboss"


def _check_docker_installed():
    if shutil.which("docker"):
        return True, shutil.which("docker")
    return False, "Not found. Install Docker Desktop from https://www.docker.com/"


def _check_docker_daemon():
    if not shutil.which("docker"):
        return False, "Docker not installed"
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "ERROR" not in result.stderr:
            return True, "Docker daemon is running"
        return False, "Docker daemon is not running. Start Docker Desktop."
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "Could not connect to Docker daemon"


def _check_docker_image(image_name: str):
    try:
        result = subprocess.run(
            ["docker", "images", "-q", image_name],
            capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip():
            return True, f"Image '{image_name}' exists"
        return False, (
            f"Image '{image_name}' not found. "
            f"Build it: cd <netMHCpan-4.0-dir> && docker build --platform linux/amd64 -t {image_name} ."
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "Could not query Docker images (daemon not running?)"


def _check_mhcflurry():
    venv_python = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    interpreter = venv_python if os.path.isfile(venv_python) else sys.executable
    try:
        subprocess.run(
            [interpreter, "-c", "import mhcflurry"],
            capture_output=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False, "Not installed. Run: pip install mhcflurry && mhcflurry-downloads fetch"

    # Check if models are downloaded
    try:
        result = subprocess.run(
            [interpreter, "-c", "from mhcflurry import Class1AffinityPredictor; Class1AffinityPredictor.load()"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, "Installed with models"
        return False, "Installed but models missing. Run: mhcflurry-downloads fetch"
    except subprocess.TimeoutExpired:
        return False, "Installed but model loading timed out"


def _needs_docker(install_dir: str) -> bool:
    """Returns True if the netMHCpan installation uses a Docker wrapper."""
    if not install_dir or not os.path.isdir(install_dir):
        return False
    return os.path.isfile(os.path.join(install_dir, "netMHCpan_docker"))


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------

def validate() -> dict:
    """Run all prerequisite checks and return a structured report.

    Returns:
        A dict with the following keys:

        - ``"all_ok"`` (bool): True if every required check passed.
        - ``"mcmc_ok"`` (bool): True if MCMC stage can run.
        - ``"filtering_ok"`` (bool): True if filtering stage can run.
        - ``"checks"`` (list[dict]): One entry per check, each with keys:
            - ``"category"`` (str): Group name (e.g. "Python", "MCMC", "Filtering").
            - ``"name"`` (str): Human-readable check name.
            - ``"ok"`` (bool): Whether the check passed.
            - ``"message"`` (str): Detail / path / error description.
            - ``"required"`` (bool): Whether this check must pass for the pipeline.
    """
    checks = []

    def add(category, name, ok, message, required=True):
        checks.append({
            "category": category,
            "name": name,
            "ok": ok,
            "message": message,
            "required": required,
        })

    # ── Python & environment ──────────────────────────────────────────────
    ok, msg = _check_python_version()
    add("Python", "Python version", ok, msg)

    ok, msg = _check_venv()
    add("Python", "Virtual environment", ok, msg)

    ok, msg = _check_pip_packages()
    add("Python", "Core pip packages", ok, msg)

    ok, msg = _check_env_file()
    add("Python", ".env file", ok, msg)

    # ── MCMC prerequisites ────────────────────────────────────────────────
    mhc_dir = os.environ.get("MHC_DIR_PATH", "")
    ok, msg = _check_netmhcpan_executable(mhc_dir, "primary")
    add("MCMC", "netMHCpan (primary, MHC_DIR_PATH)", ok, msg)

    # ── Filtering prerequisites ───────────────────────────────────────────
    ok, msg = _check_cdhit()
    add("Filtering", "cd-hit", ok, msg)

    # Filtering .env paths
    for var, is_dir in [
        ("ROBUST_DF_CSV_PATH", False),
        ("SIMULATION_CSV_DIR", True),
        ("HLA_COMBINATIONS_PICKLE", False),
        ("MEMOIZATION_DIR", True),
    ]:
        ok, msg = _check_env_var(var, must_exist_on_disk=True, is_dir=is_dir)
        add("Filtering", var, ok, msg)

    for var in [
        "CDHIT_CLUSTER1_INPUT_DIR", "CDHIT_CLUSTER1_OUTPUT_DIR",
        "CDHIT_CLUSTER2_INPUT_DIR", "CDHIT_CLUSTER2_OUTPUT_DIR",
        "STAGE2_OUTPUT_DIR",
    ]:
        ok, msg = _check_env_var(var, must_exist_on_disk=False)
        add("Filtering", var, ok, msg)

    # ── Stage 3 predictors ────────────────────────────────────────────────
    net40_dir = os.environ.get("NETMHCPAN_40_DIR_PATH", "")
    ok, msg = _check_netmhcpan_executable(net40_dir, "secondary")
    add("Stage 3", "netMHCpan 4.0 (NETMHCPAN_40_DIR_PATH)", ok, msg)

    # Docker checks — required if any netMHCpan installation uses a Docker wrapper
    docker_needed_primary = _needs_docker(mhc_dir)
    docker_needed_secondary = _needs_docker(net40_dir)
    docker_required = docker_needed_primary or docker_needed_secondary

    ok_inst, msg_inst = _check_docker_installed()
    add("Docker", "Docker installed", ok_inst, msg_inst, required=docker_required)

    ok_daemon = False
    if ok_inst:
        ok_daemon, msg_daemon = _check_docker_daemon()
        add("Docker", "Docker daemon running", ok_daemon, msg_daemon, required=docker_required)
    elif docker_required:
        add("Docker", "Docker daemon running", False, "Docker not installed", required=True)

    # Check Docker images for whichever installations need them
    if docker_needed_primary:
        if ok_inst and ok_daemon:
            ok_img, msg_img = _check_docker_image("netmhcpan41")
            add("Docker", "Docker image 'netmhcpan41'", ok_img, msg_img)
        else:
            add("Docker", "Docker image 'netmhcpan41'", False, "Docker not available", required=True)

    if docker_needed_secondary:
        if ok_inst and ok_daemon:
            ok_img, msg_img = _check_docker_image("netmhcpan40")
            add("Docker", "Docker image 'netmhcpan40'", ok_img, msg_img)
        else:
            add("Docker", "Docker image 'netmhcpan40'", False, "Docker not available", required=True)

    ok, msg = _check_mhcflurry()
    add("Stage 3", "MHCflurry", ok, msg)

    # ── Self-similarity prerequisites ──────────────────────────────────────
    ok, msg = _check_needle()
    add("Self-similarity", "EMBOSS needle", ok, msg)

    # Check for pre-computed alignment results (not required — can run fresh)
    alignment_json = os.environ.get("ALIGNMENT_RESULTS_JSON", "")
    if alignment_json and os.path.isfile(alignment_json):
        add("Self-similarity", "Pre-computed alignments", True, alignment_json, required=False)
    else:
        default_json = os.path.join(PROJECT_ROOT, "data", "needle", "alignment_results.json")
        if os.path.isfile(default_json):
            add("Self-similarity", "Pre-computed alignments", True, default_json, required=False)
        else:
            add("Self-similarity", "Pre-computed alignments", False,
                "Not found (will need to run needle — very slow)", required=False)

    # Check for human 9-mer peptidome (not required if pre-computed results exist)
    human_9mers = os.environ.get("HUMAN_9MERS_FASTA", "")
    if human_9mers and os.path.isfile(human_9mers):
        add("Self-similarity", "Human 9-mer peptidome", True, human_9mers, required=False)
    else:
        add("Self-similarity", "Human 9-mer peptidome", False,
            "Not set (needed only for fresh needle runs)", required=False)

    # ── Compute summary flags ─────────────────────────────────────────────
    def _all_ok(categories):
        return all(
            c["ok"] for c in checks
            if c["category"] in categories and c["required"]
        )

    mcmc_ok = _all_ok(["Python", "MCMC", "Docker"])
    filtering_ok = _all_ok(["Python", "MCMC", "Filtering", "Stage 3", "Docker"])
    self_sim_ok = _all_ok(["Python", "Self-similarity"])
    all_ok = all(c["ok"] for c in checks if c["required"])

    return {
        "all_ok": all_ok,
        "mcmc_ok": mcmc_ok,
        "filtering_ok": filtering_ok,
        "self_similarity_ok": self_sim_ok,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# CLI entry point — pretty-print the report
# ---------------------------------------------------------------------------

def print_report(report: dict) -> None:
    """Prints the validation report with emoji status indicators."""
    current_category = None

    for check in report["checks"]:
        if check["category"] != current_category:
            current_category = check["category"]
            print(f"\n  [{current_category}]")

        icon = "\U00002705" if check["ok"] else ("\U0000274C" if check["required"] else "\U000026A0\U0000FE0F")
        req_tag = "" if check["required"] else " (optional)"
        print(f"    {icon} {check['name']}{req_tag}")
        print(f"       {check['message']}")

    print()
    yes = "YES \u2705"
    no = "NO \u274C"
    print("  " + "=" * 50)
    mcmc_status = yes if report["mcmc_ok"] else no
    filt_status = yes if report["filtering_ok"] else no
    self_sim_status = yes if report["self_similarity_ok"] else no
    print(f"    MCMC stage ready:            {mcmc_status}")
    print(f"    Filtering stage ready:       {filt_status}")
    print(f"    Self-similarity stage ready: {self_sim_status}")
    print("  " + "=" * 50)

    if report["all_ok"]:
        print("\n  \U0001F389 All checks passed! Pipeline is ready to run.")
    else:
        failed = [c for c in report["checks"] if not c["ok"] and c["required"]]
        print(f"\n  \U0001F6A8 {len(failed)} required check(s) failed. See above for details.")


if __name__ == "__main__":
    print("\n  Super-HLA Setup Validation")
    print("  " + "=" * 50)
    report = validate()
    print_report(report)
