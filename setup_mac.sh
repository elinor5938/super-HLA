#!/bin/bash
# =============================================================================
# setup_mac.sh — One-shot macOS setup for the Super-HLA pipeline
#
# Installs and configures all prerequisites:
#   - Homebrew, Python 3.10, cd-hit, EMBOSS (needle)
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

set -uo pipefail
# NOTE: we do NOT use set -e because many commands are expected to fail
# (searches, optional tools, smoke tests). We handle errors explicitly.

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# Error trap — show what went wrong if the script exits unexpectedly
# ---------------------------------------------------------------------------
_last_command=""
trap '_last_command=$BASH_COMMAND' DEBUG
trap '
    exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "" >&2
        echo -e "\033[0;31m❌ Script exited unexpectedly (exit code $exit_code)\033[0m" >&2
        echo -e "\033[0;31m   Last command: $_last_command\033[0m" >&2
        echo -e "\033[2m   If this looks like a bug, re-run with: bash -x setup_mac.sh\033[0m" >&2
        [ -n "${_spinner_pid:-}" ] && kill "$_spinner_pid" 2>/dev/null || true
    fi
' EXIT
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
# Progress helpers — spinner for async ops, progress bar for downloads
# ---------------------------------------------------------------------------
_spinner_pid=""

# Start a background spinner with a message
spin_start() {
    local msg="$1"
    printf "  ${BLUE}⏳ %s ...${NC} " "$msg" >&2
    (
        local chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        local i=0
        while true; do
            printf "\b${CYAN}%s${NC}" "${chars:i%${#chars}:1}" >&2
            i=$((i + 1))
            sleep 0.1
        done
    ) &
    _spinner_pid=$!
}

# Stop the spinner and print result
spin_stop() {
    local result="${1:-done}"
    if [ -n "$_spinner_pid" ] && kill -0 "$_spinner_pid" 2>/dev/null; then
        kill "$_spinner_pid" 2>/dev/null
        wait "$_spinner_pid" 2>/dev/null || true
    fi
    _spinner_pid=""
    printf "\b \n" >&2
    if [ "$result" = "ok" ]; then
        true  # caller prints ok/skip
    elif [ "$result" = "fail" ]; then
        true  # caller prints fail
    fi
}

# Run a command with a spinner — usage: run_with_spinner "message" command args...
run_with_spinner() {
    local msg="$1"
    shift
    spin_start "$msg"
    local rc=0
    "$@" >/dev/null 2>&1 || rc=$?
    spin_stop
    return $rc
}

# Download with progress bar — usage: download_with_progress URL OUTPUT_FILE
download_with_progress() {
    local url="$1"
    local output="$2"
    local filename
    filename=$(basename "$output")
    echo -e "  ${BLUE}⬇️  Downloading ${filename}...${NC}" >&2
    if ! curl --progress-bar -fL -o "$output" "$url" 2>&1; then
        fail "Download failed: $url"
        return 1
    fi
}

# Run find with a scanning animation — usage: search_with_progress "label" find_args...
search_with_progress() {
    local label="$1"
    shift
    spin_start "Searching ${label}"
    local result
    result=$(find "$@" 2>/dev/null | head -1)
    spin_stop
    echo "$result"
}

# ---------------------------------------------------------------------------
# Helper: load a single variable from .env
# ---------------------------------------------------------------------------
_load_env_var() {
    local var_name="$1"
    local env_file="$PROJECT_ROOT/.env"
    if [ -f "$env_file" ]; then
        grep -m1 "^${var_name}=" "$env_file" 2>/dev/null | cut -d= -f2- || true
    fi
}

# ---------------------------------------------------------------------------
# Helper: resolve a netMHCpan directory
#   1. Use env var if already set and valid
#   2. Check existing .env for a previously configured path
#   3. Search common locations on disk
#   4. Offer to install from tarball, OR ask for existing path
# ---------------------------------------------------------------------------
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

    # 3. Search common locations for an existing installation
    local search_dirs=("$HOME" "$HOME/Documents" "$HOME/Downloads" "$HOME/Desktop" "$HOME/software" "$HOME/tools")
    spin_start "Scanning for netMHCpan ${version}" >&2
    for base in "${search_dirs[@]}"; do
        [ -d "$base" ] || continue
        local found
        found=$(find "$base" -maxdepth 4 -type d -name "netMHCpan-${version}" 2>/dev/null | head -1)
        if [ -n "$found" ]; then
            spin_stop >&2
            echo "$found"
            return
        fi
    done
    spin_stop >&2

    # 4. Not found — offer to install or ask for path
    echo "" >&2
    echo -e "  ${YELLOW}netMHCpan ${version} not found on this machine.${NC}" >&2
    echo "" >&2
    echo -e "  ${BOLD}Would you like to install netMHCpan ${version}?${NC}" >&2
    echo -e "    ${CYAN}[y]${NC} Yes — I have the tarball downloaded (or will download it now)" >&2
    echo -e "    ${CYAN}[p]${NC} I already have it installed — let me provide the path" >&2
    echo -e "    ${CYAN}[n]${NC} Skip" >&2
    echo "" >&2
    read -rp "  Choice [y/p/n]: " choice

    case "$choice" in
        [Yy]*)
            _install_netmhcpan_from_tarball "$version"
            return
            ;;
        [Pp]*)
            read -rp "  Enter the path to your netMHCpan-${version} directory: " user_path
            if [ -n "$user_path" ] && [ -d "$user_path" ]; then
                echo "$user_path"
                return
            fi
            echo -e "  ${RED}Directory not found: ${user_path}${NC}" >&2
            echo ""
            ;;
        *)
            echo ""
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Helper: register for netMHCpan download at DTU Health Tech
# Submits the academic license form and opens the browser as fallback
# ---------------------------------------------------------------------------
_register_netmhcpan_download() {
    local version="$1"
    local platform="Linux"

    echo "" >&2
    echo -e "  ${BOLD}DTU Academic License Registration${NC}" >&2
    echo -e "  ${DIM}(Your info is sent only to DTU Health Tech — required for their license)${NC}" >&2
    echo "" >&2

    read -rp "  Your full name: " reg_name
    read -rp "  Your email: " reg_email
    read -rp "  Your institution/university: " reg_affiliation

    if [ -z "$reg_name" ] || [ -z "$reg_email" ]; then
        echo -e "  ${YELLOW}Name and email are required. Opening browser instead...${NC}" >&2
        _open_browser "https://services.healthtech.dtu.dk/cgi-bin/sw_request?software=netMHCpan&version=${version}&packageversion=${version}b&platform=${platform}"
        return
    fi

    echo -e "  ${BLUE}ℹ️  Submitting registration to DTU...${NC}" >&2

    local response
    response=$(curl -sS -X POST "https://services.healthtech.dtu.dk/cgi-bin/sw_ship" \
        -d "software=netMHCpan&version=${version}&packageversion=${version}b&platform=${platform}" \
        --data-urlencode "name=${reg_name}" \
        --data-urlencode "mail=${reg_email}" \
        --data-urlencode "affiliation=${reg_affiliation}" \
        -d "position=phd_student&accept=yes" 2>&1)

    # Check if the response contains a download link (instant approval)
    local download_url
    download_url=$(echo "$response" | grep -oP 'https?://[^\s"<]+netMHCpan[^\s"<]*\.tar\.gz' | head -1)

    if [ -n "$download_url" ]; then
        echo -e "  ${GREEN}✅ Registration approved instantly!${NC}" >&2
        echo -e "  ${BLUE}ℹ️  Downloading from: ${download_url}${NC}" >&2
        return
    fi

    # Check for success message
    if echo "$response" | grep -qi "has been sent\|will be sent\|check your email\|download link"; then
        echo -e "  ${GREEN}✅ Registration submitted!${NC}" >&2
        echo -e "  ${YELLOW}📧 Check your email (${reg_email}) for the download link.${NC}" >&2
        echo -e "  ${DIM}   It may take a few minutes. Check spam folder too.${NC}" >&2
    elif echo "$response" | grep -qi "manual approval"; then
        echo -e "  ${YELLOW}⏳ Registration submitted — requires manual approval.${NC}" >&2
        echo -e "  ${YELLOW}📧 DTU will email you at ${reg_email} once approved.${NC}" >&2
        echo -e "  ${DIM}   This usually takes a few hours for academic emails.${NC}" >&2
    else
        echo -e "  ${YELLOW}Registration submitted. Check your email for the download link.${NC}" >&2
    fi

    # Also open the browser as backup
    echo "" >&2
    echo -e "  ${DIM}Also opening the DTU download page in your browser...${NC}" >&2
    _open_browser "https://services.healthtech.dtu.dk/cgi-bin/sw_request?software=netMHCpan&version=${version}&packageversion=${version}b&platform=${platform}"
}

# ---------------------------------------------------------------------------
# Helper: open a URL in the default browser (cross-platform)
# ---------------------------------------------------------------------------
_open_browser() {
    local url="$1"
    if command -v open &>/dev/null; then
        open "$url" 2>/dev/null  # macOS
    elif command -v wslview &>/dev/null; then
        wslview "$url" 2>/dev/null  # WSL with wslu
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$url" 2>/dev/null  # Linux desktop
    elif command -v sensible-browser &>/dev/null; then
        sensible-browser "$url" 2>/dev/null
    elif [ -f "/mnt/c/Windows/explorer.exe" ]; then
        /mnt/c/Windows/explorer.exe "$url" 2>/dev/null  # WSL fallback
    else
        echo -e "  ${CYAN}Open this URL in your browser: ${url}${NC}" >&2
    fi
}

# ---------------------------------------------------------------------------
# Helper: install netMHCpan from a tarball
# ---------------------------------------------------------------------------
_install_netmhcpan_from_tarball() {
    local version="$1"
    local install_parent="$HOME"

    # Ask where to install
    echo "" >&2
    read -rp "  Install directory [${install_parent}]: " custom_parent
    install_parent="${custom_parent:-$install_parent}"
    mkdir -p "$install_parent" 2>/dev/null || true

    local target_dir="$install_parent/netMHCpan-${version}"

    # Search for existing tarball in common download locations
    local tarball=""
    local search_for_tar=("$HOME/Downloads" "$HOME/Desktop" "$HOME/Documents" "$HOME" "$(dirname "$install_parent")")
    spin_start "Scanning for netMHCpan ${version} tarball" >&2
    for loc in "${search_for_tar[@]}"; do
        [ -d "$loc" ] || continue
        local found
        found=$(find "$loc" -maxdepth 2 -name "netMHCpan-${version}*.tar.gz" -type f 2>/dev/null | head -1)
        if [ -n "$found" ]; then
            tarball="$found"
            break
        fi
    done
    spin_stop >&2

    if [ -n "$tarball" ]; then
        echo -e "  ${GREEN}Found tarball: ${tarball}${NC}" >&2
        read -rp "  Use this tarball? [Y/n]: " use_it
        if [[ "$use_it" =~ ^[Nn] ]]; then
            tarball=""
        fi
    fi

    if [ -z "$tarball" ]; then
        # Offer to register and download from DTU
        echo "" >&2
        echo -e "  ${BOLD}netMHCpan ${version} requires a free academic license from DTU Health Tech.${NC}" >&2
        echo -e "  ${DIM}The download link will be emailed to you after registration.${NC}" >&2
        echo "" >&2
        echo -e "  ${CYAN}[r]${NC} Register now (opens browser + submits form)" >&2
        echo -e "  ${CYAN}[t]${NC} I already have the .tar.gz — let me provide the path" >&2
        echo -e "  ${CYAN}[n]${NC} Skip" >&2
        echo "" >&2
        read -rp "  Choice [r/t/n]: " dl_choice

        case "$dl_choice" in
            [Rr]*)
                _register_netmhcpan_download "$version"
                # After registration, wait for user to download and provide path
                echo "" >&2
                echo -e "  ${BOLD}Once you receive the download link by email:${NC}" >&2
                echo -e "  ${DIM}1. Download the Linux .tar.gz file${NC}" >&2
                echo -e "  ${DIM}2. Save it to your Downloads folder${NC}" >&2
                echo -e "  ${DIM}3. Come back here and provide the path${NC}" >&2
                echo "" >&2
                read -rp "  Path to downloaded .tar.gz file (or leave empty to skip): " tarball
                ;;
            [Tt]*)
                read -rp "  Path to .tar.gz file: " tarball
                ;;
            *)
                echo ""
                return
                ;;
        esac

        if [ -z "$tarball" ] || [ ! -f "$tarball" ]; then
            echo -e "  ${RED}Tarball not found. Skipping netMHCpan ${version}.${NC}" >&2
            echo ""
            return
        fi
    fi

    # Extract
    run_with_spinner "Extracting to ${install_parent}" tar -xzf "$tarball" -C "$install_parent"

    # The tarball may extract to a slightly different name (e.g. netMHCpan-4.1b)
    # Find the actual extracted directory
    if [ ! -d "$target_dir" ]; then
        local extracted
        extracted=$(find "$install_parent" -maxdepth 1 -type d -name "netMHCpan-${version}*" 2>/dev/null | head -1)
        if [ -n "$extracted" ] && [ "$extracted" != "$target_dir" ]; then
            mv "$extracted" "$target_dir"
        fi
    fi

    if [ -d "$target_dir" ]; then
        echo -e "  ${GREEN}✅ netMHCpan ${version} installed at: ${target_dir}${NC}" >&2

        # Also look for data tarball and extract if needed
        local data_count
        data_count=$(find "$target_dir/data" -type f 2>/dev/null | wc -l | tr -d ' ')
        if [ "$data_count" -lt 100 ]; then
            # Look for data tarball
            local data_tar=""
            for dt in "$target_dir/data.tar.gz" "$target_dir/data.Linux.tar.gz"; do
                if [ -f "$dt" ]; then data_tar="$dt"; break; fi
            done
            # Also search near the main tarball
            if [ -z "$data_tar" ]; then
                local tarball_dir
                tarball_dir=$(dirname "$tarball")
                data_tar=$(find "$tarball_dir" -maxdepth 1 -name "*data*${version}*.tar.gz" -o -name "data.Linux.tar.gz" -o -name "data.tar.gz" 2>/dev/null | head -1)
                if [ -n "$data_tar" ]; then
                    cp "$data_tar" "$target_dir/"
                    data_tar="$target_dir/$(basename "$data_tar")"
                fi
            fi
            if [ -n "$data_tar" ]; then
                run_with_spinner "Extracting data files" bash -c "cd '$target_dir' && tar -xzf '$(basename "$data_tar")'"
                ok "Data files extracted"
            elif [ "$version" = "4.0" ]; then
                download_with_progress "$NETMHCPAN_40_DATA_URL" "$target_dir/data.Linux.tar.gz"
                run_with_spinner "Extracting data files" bash -c "cd '$target_dir' && tar -xzf data.Linux.tar.gz"
                ok "Data files downloaded and extracted"
            fi
        fi

        echo "$target_dir"
    else
        echo -e "  ${RED}Extraction failed — directory not found at ${target_dir}${NC}" >&2
        echo ""
    fi
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
step "Step 0/8: Locating netMHCpan installations"

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
step "Step 1/8: Homebrew"

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
step "Step 2/8: System packages (Python 3.10, cd-hit, EMBOSS)"

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

if command -v needle &>/dev/null; then
    skip "EMBOSS needle found at $(which needle)"
else
    info "Installing EMBOSS (provides needle for self-similarity analysis)..."
    brew install emboss 2>/dev/null || true
    if command -v needle &>/dev/null; then
        ok "EMBOSS needle installed"
    else
        fail "EMBOSS installation failed"
        record_failure "EMBOSS (needle)"
    fi
fi

# ---------------------------------------------------------------------------
# Step 3: Python virtual environment + packages
# ---------------------------------------------------------------------------
step "Step 3/8: Python virtual environment"

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

run_with_spinner "Upgrading pip" "$VENV_PIP" install -U pip --quiet
run_with_spinner "Installing pip packages from requirements.txt" "$VENV_PIP" install -r "$PROJECT_ROOT/requirements.txt" --quiet
ok "Core pip packages installed"

if "$VENV_PYTHON" -c "import mhcflurry" 2>/dev/null; then
    skip "MHCflurry already installed"
else
    run_with_spinner "Installing MHCflurry (may take a minute)" "$VENV_PIP" install mhcflurry --quiet
    ok "MHCflurry installed"
fi

if "$VENV_PYTHON" -c "from mhcflurry import Class1AffinityPredictor; Class1AffinityPredictor.load()" 2>/dev/null; then
    skip "MHCflurry models already downloaded"
else
    run_with_spinner "Downloading MHCflurry models (may take a few minutes)" "$VENV_DIR/bin/mhcflurry-downloads" fetch
    ok "MHCflurry models downloaded"
fi

# ---------------------------------------------------------------------------
# Step 4: Docker
# ---------------------------------------------------------------------------
step "Step 4/8: Docker"

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
            run_with_spinner "Extracting Linux binaries from $(basename "$linux_tar")" tar -xzf "$linux_tar" -C "$(dirname "$dir")" --keep-old-files
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
            run_with_spinner "Extracting data files ($data_count found, need more)" bash -c "cd '$dir' && tar -xzf data.tar.gz"
            ok "Data files extracted"
        elif [ -f "$dir/data.Linux.tar.gz" ]; then
            run_with_spinner "Extracting data files" bash -c "cd '$dir' && tar -xzf data.Linux.tar.gz"
            ok "Data files extracted"
        elif [ "$version" = "4.0" ]; then
            download_with_progress "$NETMHCPAN_40_DATA_URL" "$dir/data.Linux.tar.gz"
            run_with_spinner "Extracting data files" bash -c "cd '$dir' && tar -xzf data.Linux.tar.gz"
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
            run_with_spinner "Building Docker image '$image_name' (may take a few minutes)" bash -c "cd '$dir' && docker build --platform linux/amd64 -t '$image_name' . --quiet"
            ok "Docker image '$image_name' built"
        else
            fail "Cannot build image — Docker daemon not running"
            record_failure "$label Docker image"
            return
        fi
    fi

    # --- Smoke test ---
    if docker image inspect "$image_name" &>/dev/null && docker info &>/dev/null; then
        local test_fasta smoke_output_file
        test_fasta=$(mktemp /tmp/superhla_test_XXXXXX.fasta)
        smoke_output_file=$(mktemp /tmp/superhla_smoke_XXXXXX.txt)
        echo -e ">test\nAYFKGVLAA" > "$test_fasta"

        spin_start "$label smoke test (may take up to 60s on first run)"
        # Run with background process + wait (macOS has no timeout command)
        "$dir/netMHCpan_docker" -f "$test_fasta" -l 9 -a HLA-A01:01 > "$smoke_output_file" 2>/dev/null &
        local smoke_pid=$!
        local waited=0
        while kill -0 "$smoke_pid" 2>/dev/null && [ $waited -lt 120 ]; do
            sleep 1
            waited=$((waited + 1))
        done
        kill "$smoke_pid" 2>/dev/null || true
        wait "$smoke_pid" 2>/dev/null || true
        spin_stop

        if grep -q "HLA-A" "$smoke_output_file" 2>/dev/null; then
            ok "$label smoke test passed"
        else
            fail "$label smoke test failed (timed out or no output)"
            record_failure "$label smoke test"
        fi
        rm -f "$test_fasta" "$smoke_output_file"
    fi
}

# ---------------------------------------------------------------------------
# Step 5: netMHCpan 4.1
# ---------------------------------------------------------------------------
step "Step 5/8: netMHCpan 4.1 (primary predictor)"
_setup_netmhcpan_docker "4.1" "$NETMHCPAN_41_DIR" "netmhcpan41" "netMHCpan 4.1" || true

# ---------------------------------------------------------------------------
# Step 6: netMHCpan 4.0
# ---------------------------------------------------------------------------
step "Step 6/8: netMHCpan 4.0 (cross-validation predictor)"

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
    _setup_netmhcpan_docker "4.0" "$NETMHCPAN_40_DIR" "netmhcpan40" "netMHCpan 4.0" || true
else
    warn "Skipping netMHCpan 4.0 — not found. Stage 3 cross-validation will use only MHCflurry."
fi

# ---------------------------------------------------------------------------
# Step 7: Configure .env
# ---------------------------------------------------------------------------
step "Step 7/8: Self-similarity data"

DATA_DIR="$PROJECT_ROOT/data"
NEEDLE_DIR="$DATA_DIR/needle"
mkdir -p "$NEEDLE_DIR/chunks"
mkdir -p "$NEEDLE_DIR/output"

# Look for existing alignment_results.json (from old codebase)
ALIGNMENT_JSON=""
if [ -f "$NEEDLE_DIR/alignment_results.json" ]; then
    skip "alignment_results.json already in data/needle/"
    ALIGNMENT_JSON="$NEEDLE_DIR/alignment_results.json"
else
    # Search common locations for pre-computed results
    for candidate in \
        "$HOME/Code/Thesis-project/alignment_results.json" \
        "$HOME/Documents/alignment_results.json"; do
        if [ -f "$candidate" ]; then
            info "Found pre-computed alignment results at: $candidate"
            cp "$candidate" "$NEEDLE_DIR/alignment_results.json"
            ALIGNMENT_JSON="$NEEDLE_DIR/alignment_results.json"
            ok "Copied alignment_results.json to data/needle/"
            break
        fi
    done
fi

if [ -z "$ALIGNMENT_JSON" ]; then
    warn "No pre-computed alignment_results.json found."
    info "You can run the self-similarity analysis fresh, or copy an existing one to:"
    info "  $NEEDLE_DIR/alignment_results.json"
fi

# Look for human 9-mer peptidome FASTA
HUMAN_9MERS=""
for candidate in \
    "$HOME/Code/Thesis-project/input/noncoding_9mers.fasta" \
    "$HOME/Documents/noncoding_9mers.fasta"; do
    if [ -f "$candidate" ]; then
        HUMAN_9MERS="$candidate"
        ok "Human 9-mer peptidome found at: $candidate"
        break
    fi
done
if [ -z "$HUMAN_9MERS" ]; then
    warn "Human 9-mer peptidome (noncoding_9mers.fasta) NOT FOUND"
    info "This file is REQUIRED for stage 4 (self-similarity analysis)."
    info "It contains the full human proteome chopped into 9-mer peptides (~16 GB)."
    printf "    Enter the path to noncoding_9mers.fasta (or press Enter to skip): "
    read -r user_path
    if [ -n "$user_path" ] && [ -f "$user_path" ]; then
        HUMAN_9MERS="$user_path"
        ok "Human 9-mer peptidome set to: $HUMAN_9MERS"
    elif [ -n "$user_path" ]; then
        fail "File not found: $user_path"
        info "You can set HUMAN_9MERS_FASTA manually in .env later."
    else
        info "Skipped. Stage 4 will not be available until HUMAN_9MERS_FASTA is set in .env"
    fi
fi

# ---------------------------------------------------------------------------
# Step 8/8: Configure .env
# ---------------------------------------------------------------------------
step "Step 8/8: Project configuration (.env)"

ENV_FILE="$PROJECT_ROOT/.env"

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
    echo "# Filtering data paths (populated by filtering.prepare_data after MCMC runs)"
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
    echo ""
    echo "# Self-similarity analysis (needle alignments)"
    echo "NEEDLE_CHUNKS_DIR=${NEEDLE_DIR}/chunks"
    echo "NEEDLE_OUTPUT_DIR=${NEEDLE_DIR}/output"
    echo "ALIGNMENT_RESULTS_JSON=${NEEDLE_DIR}/alignment_results.json"
    echo "CANDIDATE_PEPTIDES_FASTA=${DATA_DIR}/candidate_peptides.fasta"
    if [ -n "$HUMAN_9MERS" ]; then
        echo "HUMAN_9MERS_FASTA=${HUMAN_9MERS}"
    else
        echo "# HUMAN_9MERS_FASTA=  # Path to pre-chopped human proteome 9-mers FASTA"
    fi
    echo "# HUMAN_PROTEOME_FASTA=  # Path to full human proteome FASTA (for generating 9-mers)"
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
    echo -e "    2. Run the pipeline:   ${CYAN}python run.py${NC}"
else
    echo -e "  ${RED}🚨 ${#FAILURES[@]} step(s) had issues:${NC}"
    for f in "${FAILURES[@]}"; do
        echo -e "    ${RED}• $f${NC}"
    done
    echo ""
    echo -e "  Fix the issues above and re-run this script."
fi
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
