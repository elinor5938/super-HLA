# =============================================================================
# setup_windows.ps1 — One-shot Windows setup for the Super-HLA pipeline
#
# Installs and configures all prerequisites using WSL (Windows Subsystem
# for Linux) for tools that need a Linux environment (netMHCpan, needle).
#
# Prerequisites:
#   - Windows 10 version 2004+ or Windows 11
#   - Run PowerShell as Administrator for the WSL installation step
#
# Usage:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\setup_windows.ps1
#
# You can pass netMHCpan paths as environment variables:
#   $env:NETMHCPAN_41_DIR = "C:\path\to\netMHCpan-4.1"
#   .\setup_windows.ps1
#
# The script is idempotent — safe to re-run.
# =============================================================================

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------------------------------------------------------------------------
# Colors and formatting
# ---------------------------------------------------------------------------
function Write-Ok($msg) { Write-Host "  ✅ $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "  ⏭️  $msg (already done)" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "  ⚠️  $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  ❌ $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "  ℹ️  $msg" -ForegroundColor Blue }
function Write-Step($msg) { Write-Host "`n═══ $msg ═══" -ForegroundColor White }

$Failures = [System.Collections.ArrayList]::new()

function Add-Failure($msg) { $null = $Failures.Add($msg) }

# ---------------------------------------------------------------------------
# Helper: find netMHCpan directory
# ---------------------------------------------------------------------------
function Find-NetMHCpanDir {
    param(
        [string]$Version,
        [string]$EnvVarName,
        [string]$EnvConfigKey
    )

    # 1. Check environment variable
    $dir = [Environment]::GetEnvironmentVariable($EnvVarName)
    if ($dir -and (Test-Path $dir -PathType Container)) { return $dir }

    # 2. Check existing .env
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $envFile) {
        $match = Select-String -Path $envFile -Pattern "^${EnvConfigKey}=(.+)$" | Select-Object -First 1
        if ($match) {
            $dir = $match.Matches[0].Groups[1].Value.Trim()
            if (Test-Path $dir -PathType Container) { return $dir }
        }
    }

    # 3. Search common locations
    $searchDirs = @(
        $env:USERPROFILE,
        (Join-Path $env:USERPROFILE "Documents"),
        (Join-Path $env:USERPROFILE "Downloads"),
        (Join-Path $env:USERPROFILE "Desktop")
    )
    foreach ($base in $searchDirs) {
        if (-not (Test-Path $base)) { continue }
        $found = Get-ChildItem -Path $base -Recurse -Directory -Filter "netMHCpan-$Version" -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.FullName }
    }

    # 4. Prompt user
    Write-Warn "Could not auto-detect netMHCpan $Version directory."
    Write-Info "Download from: https://services.healthtech.dtu.dk/"
    $userPath = Read-Host "  Enter path to netMHCpan-$Version directory (or press Enter to skip)"
    if ($userPath -and (Test-Path $userPath -PathType Container)) { return $userPath }

    return $null
}

# ---------------------------------------------------------------------------
# Helper: convert Windows path to WSL path
# ---------------------------------------------------------------------------
function ConvertTo-WslPath {
    param([string]$WinPath)
    $WinPath = $WinPath.Replace('\', '/')
    if ($WinPath.Length -ge 2 -and $WinPath[1] -eq ':') {
        $drive = $WinPath[0].ToString().ToLower()
        return "/mnt/$drive$($WinPath.Substring(2))"
    }
    return $WinPath
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     🧬 Super-HLA — Windows Setup Script          ║" -ForegroundColor Cyan
Write-Host "║     Using WSL for Linux-based tools               ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════╝" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# Step 0: Locate netMHCpan directories
# ---------------------------------------------------------------------------
Write-Step "Step 0/7: Locating netMHCpan installations"

$NetMHCpan41Dir = Find-NetMHCpanDir -Version "4.1" -EnvVarName "NETMHCPAN_41_DIR" -EnvConfigKey "MHC_DIR_PATH"
if ($NetMHCpan41Dir) {
    Write-Ok "netMHCpan 4.1 found at: $NetMHCpan41Dir"
} else {
    Write-Fail "netMHCpan 4.1 not found (required)"
    Add-Failure "netMHCpan 4.1 not found"
}

$NetMHCpan40Dir = Find-NetMHCpanDir -Version "4.0" -EnvVarName "NETMHCPAN_40_DIR" -EnvConfigKey "NETMHCPAN_40_DIR_PATH"
if ($NetMHCpan40Dir) {
    Write-Ok "netMHCpan 4.0 found at: $NetMHCpan40Dir"
} else {
    Write-Warn "netMHCpan 4.0 not found (optional — cross-validation will be skipped)"
}

# ---------------------------------------------------------------------------
# Step 1: WSL (Windows Subsystem for Linux)
# ---------------------------------------------------------------------------
Write-Step "Step 1/7: Windows Subsystem for Linux (WSL)"

$wslInstalled = $false
try {
    $wslVersion = wsl --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Skip "WSL is installed"
        $wslInstalled = $true
    }
} catch {}

if (-not $wslInstalled) {
    # Check if wsl.exe exists at all
    $wslExe = Get-Command wsl -ErrorAction SilentlyContinue
    if ($wslExe) {
        # WSL exists but might not have a distro
        $distros = wsl --list --quiet 2>&1
        if ($LASTEXITCODE -ne 0 -or -not $distros) {
            Write-Info "WSL is available but no Linux distribution installed."
            Write-Info "Installing Ubuntu (this may take several minutes)..."
            try {
                wsl --install -d Ubuntu --no-launch
                Write-Ok "Ubuntu installed. You may need to restart and set up a user."
                Write-Warn "After restart, run this script again to continue setup."
                $wslInstalled = $true
            } catch {
                Write-Fail "WSL installation failed. Run as Administrator: wsl --install"
                Add-Failure "WSL"
            }
        } else {
            Write-Skip "WSL with distribution found"
            $wslInstalled = $true
        }
    } else {
        Write-Fail "WSL not found. Run as Administrator: wsl --install"
        Write-Info "Requires Windows 10 version 2004+ or Windows 11"
        Add-Failure "WSL"
    }
}

# Install Linux tools inside WSL
if ($wslInstalled) {
    Write-Info "Installing Linux tools in WSL (needle, cd-hit, tcsh)..."
    try {
        wsl bash -c "sudo apt-get update -qq && sudo apt-get install -y -qq emboss cd-hit tcsh gawk 2>/dev/null"
        Write-Ok "WSL packages installed (emboss, cd-hit, tcsh)"
    } catch {
        Write-Warn "Could not install WSL packages. You may need to run manually:"
        Write-Info "  wsl sudo apt install emboss cd-hit tcsh gawk"
    }
}

# ---------------------------------------------------------------------------
# Step 2: Python
# ---------------------------------------------------------------------------
Write-Step "Step 2/7: Python"

$pythonCmd = $null
# Try python3.10 first, then python3, then python
foreach ($cmd in @("python3.10", "python3", "python")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(1[0-9]|[2-9][0-9])") {
            $pythonCmd = $cmd
            Write-Skip "$ver"
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    # Check Windows Store python
    try {
        $ver = & py -3.10 --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = "py -3.10"
            Write-Skip "$ver"
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Fail "Python 3.10+ not found."
    Write-Info "Install from: https://www.python.org/downloads/"
    Write-Info "Make sure to check 'Add Python to PATH' during installation."
    Add-Failure "Python 3.10+"
    # Default to python for subsequent steps
    $pythonCmd = "python"
}

# ---------------------------------------------------------------------------
# Step 3: Virtual environment + packages
# ---------------------------------------------------------------------------
Write-Step "Step 3/7: Python virtual environment"

$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

if (Test-Path $VenvPython) {
    Write-Skip "Virtual environment at .venv\"
} else {
    Write-Info "Creating virtual environment..."
    try {
        if ($pythonCmd -eq "py -3.10") {
            & py -3.10 -m venv $VenvDir
        } else {
            & $pythonCmd -m venv $VenvDir
        }
        Write-Ok "Virtual environment created"
    } catch {
        Write-Fail "Failed to create virtual environment"
        Add-Failure "Virtual environment"
    }
}

if (Test-Path $VenvPip) {
    Write-Info "Installing/upgrading pip packages..."
    & $VenvPip install -U pip --quiet 2>$null
    & $VenvPip install -r (Join-Path $ProjectRoot "requirements.txt") --quiet 2>$null
    Write-Ok "Core pip packages installed"

    # MHCflurry
    $mhcflurryCheck = & $VenvPython -c "import mhcflurry" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Skip "MHCflurry already installed"
    } else {
        Write-Info "Installing MHCflurry (this may take a minute)..."
        & $VenvPip install mhcflurry --quiet 2>$null
        Write-Ok "MHCflurry installed"
    }

    $mhcflurryModelCheck = & $VenvPython -c "from mhcflurry import Class1AffinityPredictor; Class1AffinityPredictor.load()" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Skip "MHCflurry models already downloaded"
    } else {
        Write-Info "Downloading MHCflurry models..."
        $mhcflurryDownloads = Join-Path $VenvDir "Scripts\mhcflurry-downloads.exe"
        if (Test-Path $mhcflurryDownloads) {
            & $mhcflurryDownloads fetch 2>$null
        } else {
            & $VenvPython -m mhcflurry.downloads fetch 2>$null
        }
        Write-Ok "MHCflurry models downloaded"
    }
} else {
    Write-Fail "Cannot install packages — venv pip not found"
    Add-Failure "Pip packages"
}

# ---------------------------------------------------------------------------
# Step 4: netMHCpan WSL wrappers
# ---------------------------------------------------------------------------
Write-Step "Step 4/7: netMHCpan WSL wrappers"

function Setup-NetMHCpanWsl {
    param(
        [string]$Version,
        [string]$Dir,
        [string]$Label
    )

    if (-not $Dir -or -not (Test-Path $Dir -PathType Container)) {
        Write-Fail "Skipping $Label — directory not available"
        return
    }

    # Check for Linux binaries
    $linuxBin = Join-Path $Dir "Linux_x86_64\bin\netMHCpan"
    if (-not (Test-Path $linuxBin)) {
        Write-Warn "$Label: Linux binaries not found at Linux_x86_64\bin\"
        Write-Info "Download the Linux tarball from DTU and extract into: $Dir"
        Add-Failure "$Label Linux binaries"
        return
    }
    Write-Ok "$Label Linux binaries found"

    # Check for data directory
    $dataDir = Join-Path $Dir "data"
    $dataCount = 0
    if (Test-Path $dataDir) {
        $dataCount = (Get-ChildItem -Path $dataDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
    }
    if ($dataCount -lt 100) {
        $dataTar = Join-Path $Dir "data.Linux.tar.gz"
        if (Test-Path $dataTar) {
            Write-Info "Extracting data files..."
            $wslDir = ConvertTo-WslPath $Dir
            $extractCmd = "cd $wslDir && tar -xzf data.Linux.tar.gz"
            wsl bash -c $extractCmd
            Write-Ok "Data files extracted"
        } else {
            if ($Version -eq "4.0") {
                Write-Info "Downloading netMHCpan 4.0 data files..."
                $dataUrl = "https://services.healthtech.dtu.dk/services/NetMHCpan-4.0/data.Linux.tar.gz"
                $wslDir = ConvertTo-WslPath $Dir
                $dlCmd = "cd $wslDir && curl -sS -o data.Linux.tar.gz $dataUrl && tar -xzf data.Linux.tar.gz"
                wsl bash -c $dlCmd
                Write-Ok "Data files downloaded and extracted"
            } else {
                Write-Warn "Data directory incomplete ($dataCount files) and no data tarball found"
                Add-Failure "$Label data"
                return
            }
        }
    } else {
        Write-Skip "Data directory complete ($dataCount files)"
    }

    # Create data symlink inside Linux_x86_64
    $wslDir = ConvertTo-WslPath $Dir
    $symlinkCmd = "ln -sf $wslDir/data $wslDir/Linux_x86_64/data 2>/dev/null"
    wsl bash -c $symlinkCmd 2>$null

    # Create WSL wrapper batch file
    $wrapperPath = Join-Path $Dir "netMHCpan_wsl.bat"
    if (Test-Path $wrapperPath) {
        Write-Skip "WSL wrapper script exists"
    } else {
        Write-Info "Creating WSL wrapper script..."

        $wslNetMHCpanDir = ConvertTo-WslPath $Dir

        # Use single-quoted here-string to avoid PowerShell variable expansion
        # then replace the placeholder with the actual WSL path
        $wrapperContent = @'
@echo off
REM WSL wrapper for netMHCpan
REM Translates Windows paths to WSL paths and runs inside WSL

setlocal EnableDelayedExpansion

set NMHOME=__WSL_DIR__
set ARGS=

:parse_args
if "%~1"=="" goto run
if "%~1"=="-f" (
    shift
    set "FASTA_WIN=%~f1"
    set "FASTA_WIN=!FASTA_WIN:\=/!"
    for /f "tokens=1 delims=:" %%d in ("!FASTA_WIN!") do (
        set "DRIVE=%%d"
        call :lowercase DRIVE
    )
    set "FASTA_WSL=/mnt/!DRIVE!!FASTA_WIN:~2!"
    set "ARGS=!ARGS! -f !FASTA_WSL!"
    shift
    goto parse_args
)
if "%~1"=="-p" (
    shift
    set "PEP_WIN=%~f1"
    set "PEP_WIN=!PEP_WIN:\=/!"
    for /f "tokens=1 delims=:" %%d in ("!PEP_WIN!") do (
        set "DRIVE=%%d"
        call :lowercase DRIVE
    )
    set "PEP_WSL=/mnt/!DRIVE!!PEP_WIN:~2!"
    set "ARGS=!ARGS! -p !PEP_WSL!"
    shift
    goto parse_args
)
set "ARGS=!ARGS! %~1"
shift
goto parse_args

:run
set "NETMHCpan=%NMHOME%/Linux_x86_64"
wsl bash -c "export NMHOME=%NMHOME% && export TMPDIR=/tmp && %NETMHCpan%/bin/netMHCpan !ARGS!"
goto :eof

:lowercase
for %%a in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do (
    set "%~1=!%~1:%%a=%%a!"
)
goto :eof
'@
        $wrapperContent = $wrapperContent.Replace('__WSL_DIR__', $wslNetMHCpanDir)
        $wrapperContent | Out-File -FilePath $wrapperPath -Encoding ASCII
        Write-Ok "WSL wrapper created: $wrapperPath"
    }

    # Smoke test
    if ($wslInstalled) {
        Write-Info "Running smoke test..."
        $testFasta = Join-Path $env:TEMP "superhla_test.fasta"
        ">test`nAYFKGVLAA" | Out-File -FilePath $testFasta -Encoding ASCII
        try {
            $testResult = & $wrapperPath -f $testFasta -l 9 -a HLA-A01:01 2>&1
            if ($testResult -match "HLA-A") {
                Write-Ok "$Label smoke test passed"
            } else {
                Write-Warn "$Label smoke test did not produce expected output"
            }
        } catch {
            Write-Warn "$Label smoke test failed: $_"
        } finally {
            Remove-Item -Path $testFasta -ErrorAction SilentlyContinue
        }
    }
}

if ($NetMHCpan41Dir) {
    Setup-NetMHCpanWsl -Version "4.1" -Dir $NetMHCpan41Dir -Label "netMHCpan 4.1"
}

# ---------------------------------------------------------------------------
# Step 5: netMHCpan 4.0
# ---------------------------------------------------------------------------
Write-Step "Step 5/7: netMHCpan 4.0 (cross-validation predictor)"

if ($NetMHCpan40Dir) {
    Setup-NetMHCpanWsl -Version "4.0" -Dir $NetMHCpan40Dir -Label "netMHCpan 4.0"
} else {
    Write-Warn "Skipping netMHCpan 4.0 — not found."
}

# ---------------------------------------------------------------------------
# Step 6: Self-similarity data directories
# ---------------------------------------------------------------------------
Write-Step "Step 6/7: Self-similarity data"

$NeedleDir = Join-Path $ProjectRoot "data\needle"
New-Item -ItemType Directory -Force -Path (Join-Path $NeedleDir "chunks") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $NeedleDir "output") | Out-Null

$AlignmentJson = Join-Path $NeedleDir "alignment_results.json"
if (Test-Path $AlignmentJson) {
    Write-Skip "alignment_results.json already present"
} else {
    Write-Info "No pre-computed alignment_results.json found."
    Write-Info "Place it at: $AlignmentJson"
}

# ---------------------------------------------------------------------------
# Step 7: Configure .env
# ---------------------------------------------------------------------------
Write-Step "Step 7/7: Project configuration (.env)"

$DataDir = Join-Path $ProjectRoot "data"
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "memoization") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "cd-hit\cluster1\input") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "cd-hit\cluster1\output") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "cd-hit\cluster2\input") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "cd-hit\cluster2\output") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "stage2-files") | Out-Null

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$envContent = @"
# Generated by setup_windows.ps1 — $timestamp

# Primary netMHCpan (4.1) — used by MCMC and filtering stage 3
$(if ($NetMHCpan41Dir) { "MHC_DIR_PATH=$NetMHCpan41Dir" } else { "# MHC_DIR_PATH=  # NOT CONFIGURED" })

# Secondary netMHCpan (4.0) — cross-validation in filtering stage 3
$(if ($NetMHCpan40Dir) { "NETMHCPAN_40_DIR_PATH=$NetMHCpan40Dir" } else { "# NETMHCPAN_40_DIR_PATH=  # NOT CONFIGURED (optional)" })

# Filtering data paths (populated by prepare_filtering_data.py after MCMC runs)
ROBUST_DF_CSV_PATH=$DataDir\robust_df.csv
SIMULATION_CSV_DIR=$ProjectRoot\mcmc\output
HLA_COMBINATIONS_PICKLE=$DataDir\all_hla_combinations.pickle

# Memoization and working directories
MEMOIZATION_DIR=$DataDir\memoization
CDHIT_CLUSTER1_INPUT_DIR=$DataDir\cd-hit\cluster1\input
CDHIT_CLUSTER1_OUTPUT_DIR=$DataDir\cd-hit\cluster1\output
CDHIT_CLUSTER2_INPUT_DIR=$DataDir\cd-hit\cluster2\input
CDHIT_CLUSTER2_OUTPUT_DIR=$DataDir\cd-hit\cluster2\output
STAGE2_OUTPUT_DIR=$DataDir\stage2-files

# Self-similarity analysis (needle alignments)
NEEDLE_CHUNKS_DIR=$NeedleDir\chunks
NEEDLE_OUTPUT_DIR=$NeedleDir\output
ALIGNMENT_RESULTS_JSON=$NeedleDir\alignment_results.json
CANDIDATE_PEPTIDES_FASTA=$DataDir\candidate_peptides.fasta
# HUMAN_9MERS_FASTA=  # Path to pre-chopped human proteome 9-mers FASTA
# HUMAN_PROTEOME_FASTA=  # Path to full human proteome FASTA
"@

$envFile = Join-Path $ProjectRoot ".env"
# Use .NET to write without BOM (PowerShell's UTF8 encoding adds BOM which breaks .env parsing)
[System.IO.File]::WriteAllText($envFile, $envContent, [System.Text.UTF8Encoding]::new($false))
Write-Ok ".env configured"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor White
Write-Host "  Setup Summary" -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor White

if ($Failures.Count -eq 0) {
    Write-Host "  🎉 All steps completed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor White
    Write-Host "    1. Activate the venv:       " -NoNewline; Write-Host ".venv\Scripts\Activate.ps1" -ForegroundColor Cyan
    Write-Host "    2. Validate setup:          " -NoNewline; Write-Host "python validate_setup.py" -ForegroundColor Cyan
    Write-Host "    3. Run pipeline:            " -NoNewline; Write-Host "python run.py" -ForegroundColor Cyan
} else {
    Write-Host "  🚨 $($Failures.Count) step(s) had issues:" -ForegroundColor Red
    foreach ($f in $Failures) {
        Write-Host "    • $f" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "  Fix the issues above and re-run this script."
}
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor White
