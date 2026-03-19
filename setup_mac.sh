#!/bin/bash
# =============================================================================
# setup_mac.sh — One-shot macOS setup for the Super-HLA pipeline
#
# Installs and configures all prerequisites:
#   - Homebrew, Python 3.10, cd-hit
#   - Python virtual environment + pip packages + MHCflurry
#   - Docker images for netMHCpan 4.1 and 4.0
#   - .env configuration
#
# Usage:
#   chmod +x setup_mac.sh
#   ./setup_mac.sh
#
# You can also pass netMHCpan paths as env vars to skip the prompts:
#   NETMHCPAN_41_DIR=/path/to/netMHCpan-4.1 NETMHCPAN_40_DIR=/path/to/netMHCpan-4.0 ./setup_mac.sh
#
# The script is idempotent — safe to re-run. Already-completed steps are
# detected and skipped.
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
NETMHCPAN_40_DATA_URL="https://services.healthtech.dtu.dk/services/NetMHCpan-4.0/data.Linux.tar.gz"

# ---------------------------------------------------------------------------
# Colors and formatting
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✅ $1${NC}"; }
skip() { echo -e "  ${CYAN}⏭️  $1${NC} (already done)"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "  ${RED}❌ $1${NC}"; }
info() { echo -e "  ${BLUE}ℹ️  $1${NC}"; }
step() { echo -e "\n${BOLD}═══ $1 ═══${NC}"; }

FAILURES=()
record_failure() { FAILURES+=("$1"); }

# ---------------------------------------------------------------------------
# Helper: resolve a netMHCpan directory
#   1. Use env var if already set and valid
#   2. Check existing .env for a previously configured path
#   3. Search common locations on disk
#   4. Prompt the user
# ---------------------------------------------------------------------------
_load_env_var() {
    # Read a single variable from .env if it exists
    local var_name="$1"
    local env_file="$PROJECT_ROOT/.env"
    if [ -f "$env_file" ]; then
        grep -m1 "^${var_name}=" "$env_file" 2>/dev/null | cut -d= -f2- || true
    fi
}

_find_netmhcpan_dir() {
    local version="$1"        # e.g. "4.1" or "4.0"
    local env_var_name="$2"   # e.g. "NETMHCPAN_41_DIR" or "NETMHCPAN_40_DIR"
    local env_config_key="$3" # e.g. "MHC_DIR_PATH" or "NETMHCPAN_40_DIR_PATH"

    # 1. Already set via environment variable (e.g. passed on command line)
    local dir="${!env_var_name:-}"
    if [ -n "$dir" ] && [ -d "$dir" ]; then
        echo "$dir"
        return
    fi

    # 2. Check existing .env
    dir=$(_load_env_var "$env_config_key")
    if [ -n "$dir" ] && [ -d "$dir" ]; then
        echo "$dir"
        return
    fi

    # 3. Search common locations
    local search_dirs=("$HOME" "$HOME/Documents" "$HOME/Downloads" "$HOME/Desktop" "$HOME/software" "$HOME/tools")
    for base in "${search_dirs[@]}"; do
        # Look up to 4 levels deep for a directory named netMHCpan-<version>
        local found
        found=$(find "$base" -maxdepth 4 -type d -name "netMHCpan-${version}" 2>/dev/null | head -1)
        if [ -n "$found" ]; then
            echo "$found"
            return
        fi
    done

    # 4. Prompt the user
    echo "" >&2
    echo -e "  ${YELLOW}Could not auto-detect netMHCpan ${version} directory.${NC}" >&2
    echo -e "  ${DIM}Download from: https://services.healthtech.dtu.dk/${NC}" >&2
    echo "" >&2
    read -rp "  Enter the path to your netMHCpan-${version} directory (or leave empty to skip): " user_path
    if [ -n "$user_path" ] && [ -d "$user_path" ]; then
        echo "$user_path"
        return
    fi

    # Not found
    echo ""
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║        🧬 Super-HLA — macOS Setup Script         ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════╝${NC}"

# ---------------------------------------------------------------------------
# Locate netMHCpan directories early so we can fail fast
# ---------------------------------------------------------------------------
step "Step 0/7: Locating netMHCpan installations"

NETMHCPAN_41_DIR=$(_find_netmhcpan_dir "4.1" "NETMHCPAN_41_DIR" "MHC_DIR_PATH")
if [ -n "$NETMHCPAN_41_DIR" ]; then
    ok "netMHCpan 4.1 found at: $NETMHCPAN_41_DIR"
else
    fail "netMHCpan 4.1 not found (required)"
    record_failure "netMHCpan 4.1 not found"
fi

NETMHCPAN_40_DIR=$(_find_netmhcpan_dir "4.0" "NETMHCPAN_40_DIR" "NETMHCPAN_40_DIR_PATH")
if [ -n "$NETMHCPAN_40_DIR" ]; then
    ok "netMHCpan 4.0 found at: $NETMHCPAN_40_DIR"
else
    warn "netMHCpan 4.0 not found (optional — cross-validation will be skipped)"
fi

# ---------------------------------------------------------------------------
# Step 1: Homebrew
# ---------------------------------------------------------------------------
step "Step 1/7: Homebrew"

if command -v brew &>/dev/null; then
    skip "Homebrew $(brew --version 2>/dev/null | head -1 | awk '{print $2}')"
else
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if command -v brew &>/dev/null; then
        ok "Homebrew installed"
    else
        fail "Homebrew installation failed"
        record_failure "Homebrew"
    fi
fi

# ---------------------------------------------------------------------------
# Step 2: Python 3.10 + cd-hit
# ---------------------------------------------------------------------------
step "Step 2/7: System packages (Python 3.10, cd-hit)"

if command -v python3.10 &>/dev/null; then
    skip "Python $(python3.10 --version 2>&1 | awk '{print $2}')"
else
    info "Installing Python 3.10..."
    brew install python@3.10 2>/dev/null || true
    if command -v python3.10 &>/dev/null; then
        ok "Python 3.10 installed"
    else
        fail "Python 3.10 not found after install attempt"
        record_failure "Python 3.10"
    fi
fi

if command -v cd-hit &>/dev/null; then
    skip "cd-hit found at $(which cd-hit)"
else
    info "Installing cd-hit..."
    brew install cd-hit 2>/dev/null || true
    if command -v cd-hit &>/dev/null; then
        ok "cd-hit installed"
    else
        fail "cd-hit installation failed"
        record_failure "cd-hit"
    fi
fi

# ---------------------------------------------------------------------------
# Step 3: Python virtual environment + packages
# ---------------------------------------------------------------------------
step "Step 3/7: Python virtual environment"

VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PIP="$VENV_DIR/bin/pip"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ -f "$VENV_PYTHON" ]; then
    skip "Virtual environment at .venv/"
else
    info "Creating virtual environment..."
    python3.10 -m venv "$VENV_DIR"
    ok "Virtual environment created"
fi

info "Installing/upgrading pip packages..."
"$VENV_PIP" install -U pip --quiet 2>/dev/null
"$VENV_PIP" install -r "$PROJECT_ROOT/requirements.txt" --quiet 2>/dev/null
ok "Core pip packages installed"

if "$VENV_PYTHON" -c "import mhcflurry" 2>/dev/null; then
    skip "MHCflurry already installed"
else
    info "Installing MHCflurry (this may take a minute)..."
    "$VENV_PIP" install mhcflurry --quiet 2>/dev/null
    ok "MHCflurry installed"
fi

if "$VENV_PYTHON" -c "from mhcflurry import Class1AffinityPredictor; Class1AffinityPredictor.load()" 2>/dev/null; then
    skip "MHCflurry models already downloaded"
else
    info "Downloading MHCflurry models..."
    "$VENV_DIR/bin/mhcflurry-downloads" fetch 2>/dev/null
    ok "MHCflurry models downloaded"
fi

# ---------------------------------------------------------------------------
# Step 4: Docker
# ---------------------------------------------------------------------------
step "Step 4/7: Docker"

if command -v docker &>/dev/null; then
    skip "Docker installed at $(which docker)"
else
    fail "Docker is not installed."
    info "Install Docker Desktop from https://www.docker.com/ and re-run this script."
    record_failure "Docker"
fi

if command -v docker &>/dev/null; then
    if docker info &>/dev/null; then
        skip "Docker daemon is running"
    else
        fail "Docker daemon is not running. Start Docker Desktop and re-run this script."
        record_failure "Docker daemon"
    fi
fi

# ---------------------------------------------------------------------------
# Helper: set up a netMHCpan version for Docker
# ---------------------------------------------------------------------------
_setup_netmhcpan_docker() {
    local version="$1"       # "4.1" or "4.0"
    local dir="$2"           # absolute path to the installation
    local image_name="$3"    # Docker image name
    local label="$4"         # human-readable label for output

    if [ -z "$dir" ] || [ ! -d "$dir" ]; then
        fail "Skipping $label — directory not available"
        return
    fi

    ok "$label directory found at: $dir"

    # --- Linux binaries ---
    if [ ! -f "$dir/Linux_x86_64/bin/netMHCpan" ]; then
        local linux_tar
        linux_tar=$(find "$(dirname "$dir")" -maxdepth 1 -name "netMHCpan-${version}*.Linux*.tar.gz" 2>/dev/null | head -1)
        if [ -n "$linux_tar" ]; then
            info "Extracting Linux binaries from $(basename "$linux_tar")..."
            tar -xzf "$linux_tar" -C "$(dirname "$dir")" --keep-old-files 2>/dev/null || true
            ok "Linux binaries extracted"
        else
            fail "No Linux binaries found and no Linux tarball in $(dirname "$dir")"
            record_failure "$label Linux binaries"
            return
        fi
    else
        skip "Linux binaries present"
    fi

    # --- Data files ---
    local data_count
    data_count=$(find "$dir/data" -type f 2>/dev/null | wc -l | tr -d ' ')
    if [ "$data_count" -lt 100 ]; then
        if [ -f "$dir/data.tar.gz" ]; then
            info "Extracting data files ($data_count found, need more)..."
            (cd "$dir" && tar -xzf data.tar.gz)
            ok "Data files extracted"
        elif [ -f "$dir/data.Linux.tar.gz" ]; then
            info "Extracting data files..."
            (cd "$dir" && tar -xzf data.Linux.tar.gz)
            ok "Data files extracted"
        elif [ "$version" = "4.0" ]; then
            info "Downloading netMHCpan 4.0 data files (~25 MB)..."
            curl -sS -o "$dir/data.Linux.tar.gz" "$NETMHCPAN_40_DATA_URL"
            (cd "$dir" && tar -xzf data.Linux.tar.gz)
            ok "Data files downloaded and extracted"
        else
            fail "Data directory incomplete and no data tarball found"
            record_failure "$label data"
            return
        fi
    else
        skip "Data directory complete ($data_count files)"
    fi

    # --- Dockerfile ---
    if [ ! -f "$dir/Dockerfile" ]; then
        info "Creating Dockerfile..."
        cat > "$dir/Dockerfile" << DOCKERFILE
FROM --platform=linux/amd64 debian:bullseye-slim
RUN apt-get update && apt-get install -y --no-install-recommends tcsh gawk && rm -rf /var/lib/apt/lists/*
COPY Linux_x86_64 /opt/netMHCpan-${version}/Linux_x86_64
COPY data /opt/netMHCpan-${version}/data
RUN ln -sf /opt/netMHCpan-${version}/data /opt/netMHCpan-${version}/Linux_x86_64/data
RUN echo '#!/bin/tcsh -f' > /opt/netMHCpan-${version}/netMHCpan && \\
    echo 'setenv NMHOME /opt/netMHCpan-${version}' >> /opt/netMHCpan-${version}/netMHCpan && \\
    echo 'setenv TMPDIR /tmp' >> /opt/netMHCpan-${version}/netMHCpan && \\
    echo 'setenv NETMHCpan \$NMHOME/Linux_x86_64' >> /opt/netMHCpan-${version}/netMHCpan && \\
    echo '\$NETMHCpan/bin/netMHCpan \$*' >> /opt/netMHCpan-${version}/netMHCpan && \\
    chmod +x /opt/netMHCpan-${version}/netMHCpan
ENTRYPOINT ["/opt/netMHCpan-${version}/netMHCpan"]
DOCKERFILE
        ok "Dockerfile created"
    else
        skip "Dockerfile exists"
    fi

    # --- Docker wrapper script ---
    if [ ! -f "$dir/netMHCpan_docker" ]; then
        info "Creating Docker wrapper script..."
        cat > "$dir/netMHCpan_docker" << WRAPPER
#!/bin/bash
DOCKER_IMAGE="${image_name}"
ARGS=()
MOUNTS=()
while [ \$# -gt 0 ]; do
    case "\$1" in
        -f) shift
            FASTA_PATH="\$(cd "\$(dirname "\$1")" && pwd)/\$(basename "\$1")"
            CONTAINER_PATH="/input/\$(basename "\$1")"
            MOUNTS+=(-v "\${FASTA_PATH}:\${CONTAINER_PATH}:ro")
            ARGS+=(-f "\$CONTAINER_PATH") ;;
        -p) shift
            PEP_PATH="\$(cd "\$(dirname "\$1")" && pwd)/\$(basename "\$1")"
            CONTAINER_PATH="/input/\$(basename "\$1")"
            MOUNTS+=(-v "\${PEP_PATH}:\${CONTAINER_PATH}:ro")
            ARGS+=(-p "\$CONTAINER_PATH") ;;
        *)  ARGS+=("\$1") ;;
    esac
    shift
done
exec docker run --rm --platform linux/amd64 "\${MOUNTS[@]}" "\$DOCKER_IMAGE" "\${ARGS[@]}"
WRAPPER
        chmod +x "$dir/netMHCpan_docker"
        ok "Docker wrapper created"
    else
        skip "Docker wrapper exists"
    fi

    # --- Build Docker image ---
    if docker image inspect "$image_name" &>/dev/null; then
        skip "Docker image '$image_name' already built"
    else
        if docker info &>/dev/null; then
            info "Building Docker image '$image_name' (this may take a minute)..."
            (cd "$dir" && docker build --platform linux/amd64 -t "$image_name" . --quiet 2>/dev/null)
            ok "Docker image '$image_name' built"
        else
            fail "Cannot build image — Docker daemon not running"
            record_failure "$label Docker image"
            return
        fi
    fi

    # --- Smoke test ---
    if docker image inspect "$image_name" &>/dev/null && docker info &>/dev/null; then
        info "Running smoke test..."
        local test_fasta
        test_fasta=$(mktemp /tmp/superhla_test_XXXXXX.fasta)
        echo -e ">test\nAYFKGVLAA" > "$test_fasta"
        if "$dir/netMHCpan_docker" -f "$test_fasta" -l 9 -a HLA-A01:01 2>/dev/null | grep -q "HLA-A"; then
            ok "$label smoke test passed"
        else
            fail "$label smoke test failed"
            record_failure "$label smoke test"
        fi
        rm -f "$test_fasta"
    fi
}

# ---------------------------------------------------------------------------
# Step 5: netMHCpan 4.1
# ---------------------------------------------------------------------------
step "Step 5/7: netMHCpan 4.1 (primary predictor)"
_setup_netmhcpan_docker "4.1" "$NETMHCPAN_41_DIR" "netmhcpan41" "netMHCpan 4.1"

# ---------------------------------------------------------------------------
# Step 6: netMHCpan 4.0
# ---------------------------------------------------------------------------
step "Step 6/7: netMHCpan 4.0 (cross-validation predictor)"

if [ -z "$NETMHCPAN_40_DIR" ]; then
    # One more attempt: check for tarball next to 4.1
    if [ -n "$NETMHCPAN_41_DIR" ]; then
        TARBALL_40=$(find "$(dirname "$NETMHCPAN_41_DIR")" -maxdepth 1 -name "netMHCpan-4.0*.tar.gz" 2>/dev/null | head -1)
        if [ -n "$TARBALL_40" ]; then
            info "Found tarball: $(basename "$TARBALL_40"). Extracting..."
            tar -xzf "$TARBALL_40" -C "$(dirname "$NETMHCPAN_41_DIR")"
            NETMHCPAN_40_DIR="$(dirname "$NETMHCPAN_41_DIR")/netMHCpan-4.0"
            ok "netMHCpan 4.0 extracted"
        fi
    fi
fi

if [ -n "$NETMHCPAN_40_DIR" ]; then
    _setup_netmhcpan_docker "4.0" "$NETMHCPAN_40_DIR" "netmhcpan40" "netMHCpan 4.0"
else
    warn "Skipping netMHCpan 4.0 — not found. Stage 3 cross-validation will use only MHCflurry."
fi

# ---------------------------------------------------------------------------
# Step 7: Configure .env
# ---------------------------------------------------------------------------
step "Step 7/7: Project configuration (.env)"

ENV_FILE="$PROJECT_ROOT/.env"
DATA_DIR="$PROJECT_ROOT/data"

mkdir -p "$DATA_DIR/memoization"
mkdir -p "$DATA_DIR/cd-hit/cluster1/input"
mkdir -p "$DATA_DIR/cd-hit/cluster1/output"
mkdir -p "$DATA_DIR/cd-hit/cluster2/input"
mkdir -p "$DATA_DIR/cd-hit/cluster2/output"
mkdir -p "$DATA_DIR/stage2-files"

{
    echo "# Generated by setup_mac.sh — $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "# Primary netMHCpan (4.1) — used by MCMC and filtering stage 3"
    if [ -n "$NETMHCPAN_41_DIR" ]; then
        echo "MHC_DIR_PATH=${NETMHCPAN_41_DIR}"
    else
        echo "# MHC_DIR_PATH=  # NOT CONFIGURED — set this to your netMHCpan-4.1 directory"
    fi
    echo ""
    echo "# Secondary netMHCpan (4.0) — cross-validation in filtering stage 3"
    if [ -n "$NETMHCPAN_40_DIR" ]; then
        echo "NETMHCPAN_40_DIR_PATH=${NETMHCPAN_40_DIR}"
    else
        echo "# NETMHCPAN_40_DIR_PATH=  # NOT CONFIGURED (optional)"
    fi
    echo ""
    echo "# Filtering data paths (populated by prepare_filtering_data.py after MCMC runs)"
    echo "ROBUST_DF_CSV_PATH=${DATA_DIR}/robust_df.csv"
    echo "SIMULATION_CSV_DIR=${PROJECT_ROOT}/mcmc/output"
    echo "HLA_COMBINATIONS_PICKLE=${DATA_DIR}/all_hla_combinations.pickle"
    echo ""
    echo "# Memoization and working directories"
    echo "MEMOIZATION_DIR=${DATA_DIR}/memoization"
    echo "CDHIT_CLUSTER1_INPUT_DIR=${DATA_DIR}/cd-hit/cluster1/input"
    echo "CDHIT_CLUSTER1_OUTPUT_DIR=${DATA_DIR}/cd-hit/cluster1/output"
    echo "CDHIT_CLUSTER2_INPUT_DIR=${DATA_DIR}/cd-hit/cluster2/input"
    echo "CDHIT_CLUSTER2_OUTPUT_DIR=${DATA_DIR}/cd-hit/cluster2/output"
    echo "STAGE2_OUTPUT_DIR=${DATA_DIR}/stage2-files"
} > "$ENV_FILE"

ok ".env configured"
[ -n "$NETMHCPAN_41_DIR" ] && info "MHC_DIR_PATH         = $NETMHCPAN_41_DIR"
[ -n "$NETMHCPAN_40_DIR" ] && info "NETMHCPAN_40_DIR_PATH = $NETMHCPAN_40_DIR"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Setup Summary${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"

if [ ${#FAILURES[@]} -eq 0 ]; then
    echo -e "  ${GREEN}🎉 All steps completed successfully!${NC}"
    echo ""
    echo -e "  ${BOLD}Next steps:${NC}"
    echo -e "    1. Activate the venv:  ${CYAN}source .venv/bin/activate${NC}"
    echo -e "    2. Validate setup:     ${CYAN}python validate_setup.py${NC}"
    echo -e "    3. Run MCMC:           ${CYAN}python mcmc/main.py --mode random --seed 1 --accepted 100${NC}"
    echo -e "    4. Prepare filtering:  ${CYAN}python prepare_filtering_data.py${NC}"
    echo -e "    5. Run filtering:      ${CYAN}python -m filtering.main${NC}"
else
    echo -e "  ${RED}🚨 ${#FAILURES[@]} step(s) had issues:${NC}"
    for f in "${FAILURES[@]}"; do
        echo -e "    ${RED}• $f${NC}"
    done
    echo ""
    echo -e "  Fix the issues above and re-run this script."
fi
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
