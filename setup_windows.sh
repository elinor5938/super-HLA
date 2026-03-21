#!/bin/bash
# =============================================================================
# setup_windows.sh — Windows setup for the Super-HLA pipeline (runs inside WSL)
#
# This script runs inside WSL (Windows Subsystem for Linux) and installs
# all prerequisites using apt. No Docker needed — Linux binaries run
# natively in WSL.
#
# Prerequisites:
#   1. Install WSL:  wsl --install  (run in PowerShell as Administrator)
#   2. Open WSL terminal and navigate to the project directory:
#        cd /mnt/c/Users/<you>/code/super-HLA
#   3. Run this script:
#        chmod +x setup_windows.sh
#        ./setup_windows.sh
#
# You can pass netMHCpan paths as env vars to skip prompts:
#   NETMHCPAN_41_DIR=/mnt/c/path/to/netMHCpan-4.1 ./setup_windows.sh
#
# The script is idempotent — safe to re-run.
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
        echo -e "\033[2m   If this looks like a bug, re-run with: bash -x setup_windows.sh\033[0m" >&2
        # Clean up spinner if running
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
# Progress helpers
# ---------------------------------------------------------------------------
_spinner_pid=""

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

spin_stop() {
    if [ -n "$_spinner_pid" ] && kill -0 "$_spinner_pid" 2>/dev/null; then
        kill "$_spinner_pid" 2>/dev/null
        wait "$_spinner_pid" 2>/dev/null || true
    fi
    _spinner_pid=""
    printf "\b \n" >&2
}

run_with_spinner() {
    local msg="$1"; shift
    spin_start "$msg"
    local rc=0
    "$@" >/dev/null 2>&1 || rc=$?
    spin_stop
    return $rc
}

download_with_progress() {
    local url="$1" output="$2"
    echo -e "  ${BLUE}⬇️  Downloading $(basename "$output")...${NC}" >&2
    if ! curl --progress-bar -fL -o "$output" "$url" 2>&1; then
        fail "Download failed: $url"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Check we're running inside WSL
# ---------------------------------------------------------------------------
if ! grep -qi microsoft /proc/version 2>/dev/null; then
    echo -e "${RED}❌ This script must be run inside WSL (Windows Subsystem for Linux).${NC}"
    echo -e "${BLUE}ℹ️  Install WSL from PowerShell (as Administrator): wsl --install${NC}"
    echo -e "${BLUE}ℹ️  Then open WSL and run: cd /mnt/c/Users/<you>/code/super-HLA && ./setup_windows.sh${NC}"
    exit 1
fi

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
#   3. Search common locations (Windows drives + WSL home)
#   4. Offer to install from tarball, OR ask for existing path
# ---------------------------------------------------------------------------
_find_netmhcpan_dir() {
    local version="$1"
    local env_var_name="$2"
    local env_config_key="$3"

    # 1. Check environment variable
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

    # 3. Search Windows user directories via /mnt/c/ and WSL home
    local win_user_dir=""
    for candidate in /mnt/c/Users/*/; do
        local base
        base=$(basename "$candidate")
        if [[ "$base" != "Public" && "$base" != "Default" && "$base" != "Default User" && "$base" != "All Users" ]]; then
            win_user_dir="$candidate"
            break
        fi
    done

    local search_dirs=("$HOME")
    if [ -n "$win_user_dir" ]; then
        search_dirs+=("$win_user_dir" "${win_user_dir}Documents" "${win_user_dir}Downloads" "${win_user_dir}Desktop")
    fi

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
            echo -e "  ${DIM}Use WSL-style paths, e.g.: /mnt/c/Users/you/netMHCpan-${version}${NC}" >&2
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

    if echo "$response" | grep -qi "manual approval"; then
        echo -e "  ${YELLOW}⏳ Registration submitted — requires manual approval.${NC}" >&2
        echo -e "  ${YELLOW}📧 DTU will email you at ${reg_email} once approved.${NC}" >&2
        echo -e "  ${DIM}   This usually takes a few hours for academic emails.${NC}" >&2
    else
        echo -e "  ${GREEN}✅ Registration submitted!${NC}" >&2
        echo -e "  ${YELLOW}📧 Check your email (${reg_email}) for the download link.${NC}" >&2
        echo -e "  ${DIM}   It may take a few minutes. Check spam folder too.${NC}" >&2
    fi

    echo "" >&2
    echo -e "  ${DIM}Also opening the DTU download page in your browser...${NC}" >&2
    _open_browser "https://services.healthtech.dtu.dk/cgi-bin/sw_request?software=netMHCpan&version=${version}&packageversion=${version}b&platform=${platform}"
}

# ---------------------------------------------------------------------------
# Helper: open a URL in the default browser (cross-platform)
# ---------------------------------------------------------------------------
_open_browser() {
    local url="$1"
    if command -v wslview &>/dev/null; then
        wslview "$url" 2>/dev/null
    elif [ -f "/mnt/c/Windows/explorer.exe" ]; then
        /mnt/c/Windows/explorer.exe "$url" 2>/dev/null
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$url" 2>/dev/null
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
    local search_for_tar=("$HOME/Downloads" "$HOME/Desktop" "$HOME")
    # Also search Windows downloads
    for candidate in /mnt/c/Users/*/Downloads /mnt/c/Users/*/Desktop; do
        [ -d "$candidate" ] && search_for_tar+=("$candidate")
    done
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
            local data_tar=""
            for dt in "$target_dir/data.tar.gz" "$target_dir/data.Linux.tar.gz"; do
                if [ -f "$dt" ]; then data_tar="$dt"; break; fi
            done
            if [ -z "$data_tar" ]; then
                local tarball_dir
                tarball_dir=$(dirname "$tarball")
                data_tar=$(find "$tarball_dir" -maxdepth 1 \( -name "*data*${version}*.tar.gz" -o -name "data.Linux.tar.gz" -o -name "data.tar.gz" \) 2>/dev/null | head -1)
                if [ -n "$data_tar" ]; then
                    cp "$data_tar" "$target_dir/"
                    data_tar="$target_dir/$(basename "$data_tar")"
                fi
            fi
            if [ -n "$data_tar" ]; then
                run_with_spinner "Extracting data files" bash -c "cd '$target_dir' && tar -xzf '$(basename "$data_tar")'"
                ok "Data files extracted"
            else
                # Download data from DTU
                local dl_url="" dl_name=""
                for try_url in \
                    "https://services.healthtech.dtu.dk/services/NetMHCpan-${version}/data.tar.gz" \
                    "https://services.healthtech.dtu.dk/services/NetMHCpan-${version}/data.Linux.tar.gz"; do
                    if curl -sfI "$try_url" >/dev/null 2>&1; then
                        dl_url="$try_url"
                        dl_name=$(basename "$try_url")
                        break
                    fi
                done
                if [ -n "$dl_url" ]; then
                    download_with_progress "$dl_url" "$target_dir/$dl_name"
                    run_with_spinner "Extracting data files" bash -c "cd '$target_dir' && tar -xzf '$dl_name'"
                    ok "Data files downloaded and extracted"
                fi
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
echo -e "${BOLD}║     🧬 Super-HLA — Windows/WSL Setup Script      ║${NC}"
echo -e "${BOLD}║     Linux tools run natively — no Docker needed   ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════╝${NC}"

# ---------------------------------------------------------------------------
# Step 0: Locate netMHCpan installations
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
# Step 1: System packages via apt
# ---------------------------------------------------------------------------
step "Step 1/7: System packages (Python, cd-hit, EMBOSS, tcsh)"

run_with_spinner "Updating apt package list" sudo apt-get update -qq

# Python 3.10+
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        skip "Python $PY_VER"
    else
        info "Python $PY_VER found but need 3.10+. Installing..."
        sudo apt-get install -y -qq python3.10 python3.10-venv python3-pip 2>/dev/null || true
    fi
else
    info "Installing Python 3..."
    sudo apt-get install -y -qq python3 python3-venv python3-pip 2>/dev/null || true
fi

# Verify Python
if command -v python3 &>/dev/null; then
    ok "Python $(python3 --version 2>&1 | awk '{print $2}')"
else
    fail "Python 3 not found after install attempt"
    record_failure "Python 3"
fi

# cd-hit
if command -v cd-hit &>/dev/null; then
    skip "cd-hit found at $(which cd-hit)"
else
    info "Installing cd-hit..."
    sudo apt-get install -y -qq cd-hit 2>/dev/null || true
    if command -v cd-hit &>/dev/null; then
        ok "cd-hit installed"
    else
        fail "cd-hit installation failed"
        record_failure "cd-hit"
    fi
fi

# EMBOSS (needle)
if command -v needle &>/dev/null; then
    skip "EMBOSS needle found at $(which needle)"
else
    info "Installing EMBOSS (provides needle)..."
    sudo apt-get install -y -qq emboss 2>/dev/null || true
    if command -v needle &>/dev/null; then
        ok "EMBOSS needle installed"
    else
        fail "EMBOSS installation failed"
        record_failure "EMBOSS (needle)"
    fi
fi

# tcsh + gawk (needed by netMHCpan's wrapper scripts)
if command -v tcsh &>/dev/null; then
    skip "tcsh found"
else
    info "Installing tcsh..."
    sudo apt-get install -y -qq tcsh 2>/dev/null || true
fi

if command -v gawk &>/dev/null; then
    skip "gawk found"
else
    sudo apt-get install -y -qq gawk 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Step 2: Python virtual environment + packages
# ---------------------------------------------------------------------------
step "Step 2/7: Python virtual environment"

VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PIP="$VENV_DIR/bin/pip"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ -f "$VENV_PYTHON" ]; then
    skip "Virtual environment at .venv/"
else
    info "Creating virtual environment..."
    if python3 -m venv "$VENV_DIR"; then
        ok "Virtual environment created"
    else
        fail "Failed to create virtual environment"
        record_failure "Virtual environment"
    fi
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
# Helper: set up a netMHCpan version (native Linux — no Docker needed)
# ---------------------------------------------------------------------------
_setup_netmhcpan_native() {
    local version="$1"
    local dir="$2"
    local label="$3"

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
            fail "No Linux binaries found and no Linux tarball near $dir"
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
        else
            # Try downloading data from DTU (works for both 4.0 and 4.1)
            local data_url=""
            local data_filename=""
            # Try version-specific URLs in order of preference
            for try_url in \
                "https://services.healthtech.dtu.dk/services/NetMHCpan-${version}/data.tar.gz" \
                "https://services.healthtech.dtu.dk/services/NetMHCpan-${version}/data.Linux.tar.gz"; do
                if curl -sfI "$try_url" >/dev/null 2>&1; then
                    data_url="$try_url"
                    data_filename=$(basename "$try_url")
                    break
                fi
            done

            if [ -n "$data_url" ]; then
                download_with_progress "$data_url" "$dir/$data_filename"
                run_with_spinner "Extracting data files" bash -c "cd '$dir' && tar -xzf '$data_filename'"
                ok "Data files downloaded and extracted"
            else
                fail "Data directory incomplete and could not download data from DTU"
                record_failure "$label data"
                return
            fi
        fi
    else
        skip "Data directory complete ($data_count files)"
    fi

    # --- Data symlink inside Linux_x86_64 ---
    ln -sf "$dir/data" "$dir/Linux_x86_64/data" 2>/dev/null || true

    # --- Patch the netMHCpan tcsh script to use local NMHOME ---
    local tcsh_script="$dir/netMHCpan"
    if [ -f "$tcsh_script" ]; then
        if grep -q '/net/sund-nas.win.dtu.dk\|/services/www/packages' "$tcsh_script" 2>/dev/null; then
            info "Patching netMHCpan tcsh script with local installation path..."
            # Replace the hardcoded DTU NMHOME with the actual local directory
            sed -i "s|setenv\tNMHOME.*|setenv\tNMHOME\t$dir|" "$tcsh_script"
            # Also fix any variant with spaces instead of tabs
            sed -i "s|setenv  *NMHOME  *.*|setenv\tNMHOME\t$dir|" "$tcsh_script"
            ok "Patched netMHCpan script NMHOME → $dir"
        else
            skip "netMHCpan tcsh script already patched"
        fi
    fi

    # --- Create a bash wrapper that runs netMHCpan via tcsh ---
    local wrapper_path="$dir/netMHCpan_wsl"
    # Always recreate the wrapper to ensure it's up to date
    info "Creating native WSL wrapper script..."
    cat > "$wrapper_path" << 'WRAPPER'
#!/bin/bash
# Native WSL wrapper for netMHCpan — runs via patched tcsh script
NMHOME="$(cd "$(dirname "$0")" && pwd)"
export TMPDIR="${TMPDIR:-/tmp}"
mkdir -p "$TMPDIR" 2>/dev/null || true

# Use the patched tcsh script (most reliable — handles all env vars)
if command -v tcsh >/dev/null 2>&1 && [ -f "$NMHOME/netMHCpan" ]; then
    exec tcsh "$NMHOME/netMHCpan" "$@"
fi

# Fallback: run Linux binary directly
export NETMHCpan="$NMHOME/Linux_x86_64"
if [ -x "$NETMHCpan/bin/netMHCpan" ]; then
    exec "$NETMHCpan/bin/netMHCpan" "$@"
fi

echo "ERROR: Cannot find netMHCpan binary or tcsh script in $NMHOME" >&2
exit 1
WRAPPER
    chmod +x "$wrapper_path"
    ok "WSL wrapper created"

    # --- Smoke test (with timeout + spinner) ---
    local test_fasta
    test_fasta=$(mktemp /tmp/superhla_test_XXXXXX.fasta)
    echo -e ">test\nAYFKGVLAA" > "$test_fasta"

    spin_start "$label smoke test (may take up to 60s on first run)"
    local smoke_output=""
    smoke_output=$(timeout 120 "$wrapper_path" -f "$test_fasta" -l 9 -a HLA-A01:01 2>/dev/null || true)
    spin_stop

    if echo "$smoke_output" | grep -q "HLA-A"; then
        ok "$label smoke test passed"
    else
        fail "$label smoke test failed (timed out or no output)"
        record_failure "$label smoke test"
    fi
    rm -f "$test_fasta"
}

# ---------------------------------------------------------------------------
# Step 3: netMHCpan 4.1
# ---------------------------------------------------------------------------
step "Step 3/7: netMHCpan 4.1 (primary predictor)"
_setup_netmhcpan_native "4.1" "$NETMHCPAN_41_DIR" "netMHCpan 4.1" || true

# ---------------------------------------------------------------------------
# Step 4: netMHCpan 4.0
# ---------------------------------------------------------------------------
step "Step 4/7: netMHCpan 4.0 (cross-validation predictor)"

if [ -z "$NETMHCPAN_40_DIR" ]; then
    # One more attempt: check for tarball next to 4.1
    if [ -n "$NETMHCPAN_41_DIR" ]; then
        TARBALL_40=$(find "$(dirname "$NETMHCPAN_41_DIR")" -maxdepth 1 -name "netMHCpan-4.0*.tar.gz" 2>/dev/null | head -1)
        if [ -n "$TARBALL_40" ]; then
            info "Found tarball: $(basename "$TARBALL_40"). Extracting..."
            tar -xzf "$TARBALL_40" -C "$(dirname "$NETMHCPAN_41_DIR")" || true
            NETMHCPAN_40_DIR="$(dirname "$NETMHCPAN_41_DIR")/netMHCpan-4.0"
            ok "netMHCpan 4.0 extracted"
        fi
    fi
fi

if [ -n "$NETMHCPAN_40_DIR" ]; then
    _setup_netmhcpan_native "4.0" "$NETMHCPAN_40_DIR" "netMHCpan 4.0" || true
else
    warn "Skipping netMHCpan 4.0 — not found. Stage 3 cross-validation will use only MHCflurry."
fi

# ---------------------------------------------------------------------------
# Step 5: Self-similarity data
# ---------------------------------------------------------------------------
step "Step 5/7: Self-similarity data"

DATA_DIR="$PROJECT_ROOT/data"
NEEDLE_DIR="$DATA_DIR/needle"
mkdir -p "$NEEDLE_DIR/chunks"
mkdir -p "$NEEDLE_DIR/output"

ALIGNMENT_JSON=""
if [ -f "$NEEDLE_DIR/alignment_results.json" ]; then
    skip "alignment_results.json already in data/needle/"
    ALIGNMENT_JSON="$NEEDLE_DIR/alignment_results.json"
fi

HUMAN_9MERS=""
# Search for the peptidome file in common locations
for candidate in \
    "$HOME/noncoding_9mers.fasta" \
    "$PROJECT_ROOT/data/needle/noncoding_9mers.fasta"; do
    if [ -f "$candidate" ]; then
        HUMAN_9MERS="$candidate"
        ok "Human 9-mer peptidome found at: $candidate"
        break
    fi
done
# Also check Windows filesystem
if [ -z "$HUMAN_9MERS" ]; then
    for winhome in /mnt/c/Users/*/; do
        found=$(find "$winhome" -maxdepth 4 -name "noncoding_9mers.fasta" -type f 2>/dev/null | head -1)
        if [ -n "$found" ]; then
            HUMAN_9MERS="$found"
            ok "Human 9-mer peptidome found at: $found"
            break
        fi
    done
fi
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
# Step 6: Configure .env
# ---------------------------------------------------------------------------
step "Step 6/7: Project configuration (.env)"

ENV_FILE="$PROJECT_ROOT/.env"

mkdir -p "$DATA_DIR/memoization"
mkdir -p "$DATA_DIR/cd-hit/cluster1/input"
mkdir -p "$DATA_DIR/cd-hit/cluster1/output"
mkdir -p "$DATA_DIR/cd-hit/cluster2/input"
mkdir -p "$DATA_DIR/cd-hit/cluster2/output"
mkdir -p "$DATA_DIR/stage2-files"

{
    echo "# Generated by setup_windows.sh (WSL) — $(date '+%Y-%m-%d %H:%M:%S')"
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
    echo "ACCEPTED_PEPTIDES_CSV_PATH=${DATA_DIR}/accepted_peptides.csv"
    echo "SIMULATION_CSV_DIR=${PROJECT_ROOT}/mcmc/output"
    echo "HLA_COMBINATIONS_PICKLE=${DATA_DIR}/all_hla_combinations.pickle"
    echo ""
    echo "# Memoization and working directories"
    echo "MEMOIZATION_DIR=${DATA_DIR}/memoization"
    echo "CDHIT_CLUSTER1_INPUT_DIR=${DATA_DIR}/cd-hit/cluster1/input"
    echo "CDHIT_CLUSTER1_OUTPUT_DIR=${DATA_DIR}/cd-hit/cluster1/output"
    echo "CDHIT_CLUSTER2_INPUT_DIR=${DATA_DIR}/cd-hit/cluster2/input"
    echo "CDHIT_CLUSTER2_OUTPUT_DIR=${DATA_DIR}/cd-hit/cluster2/output"
    echo "SYNTHESIS_FILTER_OUTPUT_DIR=${DATA_DIR}/stage2-files"
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
# Step 7: Validate
# ---------------------------------------------------------------------------
step "Step 7/7: Quick validation"

if "$VENV_PYTHON" "$PROJECT_ROOT/validate_setup.py" 2>/dev/null; then
    ok "Validation passed"
else
    warn "Some validation checks may have failed — run 'python validate_setup.py' for details"
fi

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
    echo -e "  ${BOLD}Next steps (run from WSL):${NC}"
    echo -e "    1. Activate the venv:  ${CYAN}source .venv/bin/activate${NC}"
    echo -e "    2. Run the pipeline:   ${CYAN}python run.py${NC}"
    echo ""
    echo -e "  ${DIM}Tip: Always run the pipeline from WSL, not from PowerShell.${NC}"
    echo -e "  ${DIM}Your project files at /mnt/c/... are shared between Windows and WSL.${NC}"
else
    echo -e "  ${RED}🚨 ${#FAILURES[@]} step(s) had issues:${NC}"
    for f in "${FAILURES[@]}"; do
        echo -e "    ${RED}• $f${NC}"
    done
    echo ""
    echo -e "  Fix the issues above and re-run this script."
fi
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
