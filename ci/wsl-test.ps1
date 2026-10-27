# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: measured Windows WSL2 runtime validation.
$ErrorActionPreference = 'Stop'
$outDir = Join-Path $env:RUNNER_TEMP 'ase-wsl-report'
New-Item -ItemType Directory -Force $outDir | Out-Null
$timer = [Diagnostics.Stopwatch]::StartNew()
$artifact = Join-Path $env:GITHUB_WORKSPACE 'artifact'
$report = @{
    schema_version = 1
    target = @{ id = 'windows-wsl2-x86_64'; runner = 'windows-2025'; experimental = $true }
    started_at = [DateTime]::UtcNow.ToString('o')
    finished_at = $null
    status = 'running'
    stages = @()
    artifacts = @()
    notes = @('Runtime validation of the Ubuntu 24.04 artifact; no native Windows compilation.')
}
function Save-Report {
    $report | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 (Join-Path $outDir 'report.json')
}
function Stage([string]$name, [scriptblock]$action) {
    $step = @{ name = $name; started_at = [DateTime]::UtcNow.ToString('o'); status = 'running' }
    $report.stages += $step
    Save-Report
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        & $action *> (Join-Path $outDir "$name.log")
        $step.status = 'succeeded'
        $step.exit_code = 0
    } catch {
        $step.status = 'failed'
        $step.error = $_.ToString()
        throw
    } finally {
        $step.finished_at = [DateTime]::UtcNow.ToString('o')
        $step.wall_seconds = $clock.Elapsed.TotalSeconds
        Save-Report
    }
}
function Wsl {
    & wsl.exe @args
    if ($LASTEXITCODE -ne 0) { throw "wsl.exe failed: $LASTEXITCODE" }
}
Save-Report
try {
    Stage 'install-wsl-distribution' {
        Wsl --set-default-version 2
        Wsl --install --distribution Ubuntu-24.04 --no-launch --web-download
        Wsl --distribution Ubuntu-24.04 --user root -- uname -r
    }
    Stage 'verify-package' {
        $sourceReport = Get-Content (Join-Path $artifact 'report.json') | ConvertFrom-Json
        if ($sourceReport.status -ne 'succeeded') { throw 'Ubuntu build failed or was incomplete' }
        foreach ($file in $sourceReport.artifacts) {
            $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $artifact $file.name)).Hash.ToLower()
            if ($actual -ne $file.sha256) { throw "Checksum mismatch: $($file.name)" }
        }
        $report.source_artifact = $sourceReport
    }
    Stage 'dependencies-and-relocated-smoke' {
        $linuxArtifact = (& wsl.exe -d Ubuntu-24.04 -u root -- wslpath -u $artifact).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot translate artifact path' }
        $script = @'
# SPDX-License-Identifier: GPL-2.0-only
# Generated from ci/wsl-test.ps1, created on 2026-10-27.
set -euo pipefail
uname -r | grep -Ei 'microsoft.*WSL2|microsoft-standard'
export DEBIAN_FRONTEND=noninteractive
apt-get update
# Match installed package names from the build image. This conservative validation
# environment includes development packages; it does not measure minimal install size.
cut -f1 "$1/packages.txt" | xargs apt-get install -y
mkdir -p /tmp/ase-wsl-test
cd /tmp/ase-wsl-test
tar -xf "$1/ase-engine-ubuntu-24.04-x86_64.tar.gz"
bundle=/tmp/ase-wsl-test/ase-engine-ubuntu-24.04-x86_64
ASE_REPO=. ASE_WORK=unused ASE_OUTPUT=/tmp/ase-wsl-test/results ASE_TARGET=unused python3 "$bundle/tests/package.py" test-bundle "$bundle"
'@
        $scriptPath = Join-Path $outDir 'wsl-smoke.sh'
        [IO.File]::WriteAllText($scriptPath, ($script -replace "`r", ''), [Text.UTF8Encoding]::new($false))
        $linuxScript = (& wsl.exe -d Ubuntu-24.04 -u root -- wslpath -u $scriptPath).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot translate smoke script path' }
        Wsl -d Ubuntu-24.04 -u root -- bash $linuxScript $linuxArtifact
    }
    $report.status = 'succeeded'
} catch {
    $report.status = 'failed'
    $report.error = $_.ToString()
} finally {
    $report.finished_at = [DateTime]::UtcNow.ToString('o')
    $report.wall_seconds = $timer.Elapsed.TotalSeconds
    Save-Report
}
if ($report.status -ne 'succeeded') { exit 1 }
