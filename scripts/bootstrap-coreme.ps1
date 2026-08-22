# Bootstrap CoreMe on a fresh Windows PC: installer tool -> coreme wheel ->
# agent docs into the current folder -> doctor gate.
#
# Detection chain (check first, install only what is missing):
#   1. uv exists?                 use it (uv fetches its own managed CPython)
#   2. pipx + Python >= 3.11?     use pipx
#   3. neither?                   install uv via the official installer
#
# Usage (any agent or human):
#   irm https://raw.githubusercontent.com/omerlefaruk/coreme/main/scripts/bootstrap-coreme.ps1 -OutFile bootstrap-coreme.ps1
#   powershell -ExecutionPolicy Bypass -File .\bootstrap-coreme.ps1
#   powershell -ExecutionPolicy Bypass -File .\bootstrap-coreme.ps1 -CoreMeVersion 0.6.0
#
# Compatible with Windows PowerShell 5.1 (no PS7-only syntax).
#Requires -Version 5.1
param(
    [string]$CoreMeVersion = "latest",
    [string]$WheelPath = ""
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "omerlefaruk/coreme"
$UvBin = Join-Path $env:USERPROFILE ".local\bin"

function Test-Cmd([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-LatestCoreMeVersion {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" `
        -Headers @{ "User-Agent" = "coreme-bootstrap" } -UseBasicParsing
    return $release.tag_name.TrimStart("v")
}

function Install-Uv {
    Write-Host "[bootstrap] installing uv (single exe, no admin)..."
    $script = Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing
    Invoke-Expression $script
    if (-not (Test-Cmd uv)) {
        # Fresh shim dir may not be on this session's PATH yet.
        if (Test-Path (Join-Path $UvBin "uv.exe")) {
            $env:Path += ";$UvBin"
        }
    }
    if (-not (Test-Cmd uv)) {
        throw "uv installation did not produce a usable uv on PATH"
    }
}

function Get-PythonOk {
    try {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-CoreMeExe {
    $candidate = Join-Path $UvBin "coreme.exe"
    if (Test-Path $candidate) { return $candidate }
    $cmd = Get-Command coreme -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# --- 1. pick / install the tool engine -------------------------------------
$engine = $null
if (Test-Cmd uv) {
    $engine = "uv"
    Write-Host "[bootstrap] using existing uv"
} elseif ((Test-Cmd pipx) -and (Get-PythonOk)) {
    $engine = "pipx"
    Write-Host "[bootstrap] using existing pipx + Python"
} else {
    Install-Uv
    $engine = "uv"
}

if ($WheelPath) {
    $wheelUrl = (Resolve-Path $WheelPath).Path
    Write-Host "[bootstrap] dev override: wheel from $wheelUrl"
} else {
    if ($CoreMeVersion -eq "latest") {
        $CoreMeVersion = Get-LatestCoreMeVersion
    }
    $wheelUrl = "https://github.com/$Repo/releases/download/v$CoreMeVersion/coreme-$CoreMeVersion-py3-none-any.whl"
}
Write-Host "[bootstrap] installing coreme via $engine"
Write-Host "[bootstrap] wheel: $wheelUrl"

# --- 2. install coreme ------------------------------------------------------
if ($engine -eq "uv") {
    # --force keeps re-runs idempotent (shim dir may be shared with pipx).
    & uv tool install --upgrade --force $wheelUrl
    if ($LASTEXITCODE -ne 0) { throw "uv tool install failed ($LASTEXITCODE)" }
    if (-not (Test-Cmd coreme) -and (Test-Path $UvBin)) { $env:Path += ";$UvBin" }
} else {
    & pipx install --force $wheelUrl
    if ($LASTEXITCODE -ne 0) { throw "pipx install failed ($LASTEXITCODE)" }
}

$coreme = Find-CoreMeExe
if (-not $coreme) { throw "coreme.exe not found after install" }

# --- 3. materialize agent docs into this folder -----------------------------
Write-Host "[bootstrap] installing agent docs into $(Get-Location)"
& $coreme skills install .
if ($LASTEXITCODE -ne 0) { throw "skills install failed ($LASTEXITCODE)" }

# --- 4. sanity gate ----------------------------------------------------------
& $coreme doctor --workspace .
if ($LASTEXITCODE -ne 0) { throw "doctor reported failures ($LASTEXITCODE)" }

# --- 5. hand off to the agent ------------------------------------------------
Write-Host ""
Write-Host "[bootstrap] OK — $(& $coreme --version) ready ($engine)"
Write-Host "[bootstrap] AGENT NEXT STEPS:"
Write-Host "[bootstrap]   1. Read AGENTS.md and START-HERE.md in this folder."
Write-Host "[bootstrap]   2. If .git is missing: git init."
Write-Host "[bootstrap]   3. Ask the operator what to automate; write jobs/<name>/ per skills/build-job/SKILL.md."
Write-Host "[bootstrap]   4. Prove offline (coreme test), run live, ship, commit, report paths."
