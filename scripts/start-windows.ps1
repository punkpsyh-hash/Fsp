[CmdletBinding()]
param(
    [switch]$BuildOnly,
    [switch]$Isolated,
    [ValidateSet('Start', 'Verify')]
    [string]$Action = 'Start'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if ($Action -eq 'Verify') { $Isolated = $true }
    if ($BuildOnly -and $Action -ne 'Start') {
        throw '-BuildOnly нельзя сочетать с -Action Verify.'
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install and start Docker Desktop in Linux containers mode.'
    }
    $engineType = & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running.' }
    if ($engineType -ne 'linux') { throw 'Switch Docker Desktop to Linux containers.' }
    & docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges:true `
        --workdir /workspace --mount "type=bind,src=$projectRoot,dst=/workspace" `
        python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e `
        python scripts/init_env.py
    if ($LASTEXITCODE -ne 0) { throw 'Local configuration initialization failed.' }
    $composeFiles = @('-f', 'compose.yaml', '-f', 'compose.runner-tcg.yaml')
    if ($Isolated) {
        $composeFiles += @('-f', 'compose.verify.yaml')
    }
    if ($BuildOnly) {
        & docker compose @composeFiles build app runner
    } elseif ($Action -eq 'Start') {
        & docker compose @composeFiles up -d --build --wait --wait-timeout 240 app runner
    } else {
        & docker compose @composeFiles up -d --build --wait --wait-timeout 240 app runner
        if ($LASTEXITCODE -eq 0) { & docker compose @composeFiles build tools browser }
        if ($LASTEXITCODE -eq 0) { & docker compose @composeFiles run --rm -T --no-deps tools sh scripts/check.sh }
        if ($LASTEXITCODE -eq 0) { & docker compose @composeFiles run --rm -T --no-deps runner python -m runner.probe --smoke }
        if ($LASTEXITCODE -eq 0) {
            & docker compose @composeFiles run --rm -T --no-deps `
                --volume "${projectRoot}/scripts/verify_contest_bank.py:/app/verify_contest_bank.py:ro" `
                --volume "${projectRoot}/requirements/examples/bank-contest.json:/bank.json:ro" `
                --volume "${projectRoot}/docs:/evidence" runner python /app/verify_contest_bank.py `
                --bank /bank.json --output /evidence/contest-bank-results.json
        }
        if ($LASTEXITCODE -eq 0) { & docker compose @composeFiles run --rm -T --no-deps browser npm run test:e2e }
    }
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed; see the output above.' }
    if (-not $BuildOnly -and $Action -eq 'Start') {
        if ($Isolated) { Write-Host 'Изолированный стенд запущен без публикации портов.' }
        else { Write-Host 'FSP: http://127.0.0.1:8470' }
    }
} finally {
    Pop-Location
}
