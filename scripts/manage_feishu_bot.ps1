param(
    [ValidateSet("start", "preflight", "status", "stop")]
    [string]$Action = "status",
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$resolvedRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$runner = Join-Path $resolvedRoot "scripts\run_feishu_bot.py"

if (-not $PythonPath) {
    $candidates = @(
        (Join-Path $resolvedRoot ".venv312\Scripts\python.exe"),
        (Join-Path $resolvedRoot ".venv\Scripts\python.exe")
    )
    $worktreeContainer = Split-Path -Parent $resolvedRoot
    if ((Split-Path -Leaf $worktreeContainer) -eq ".worktrees") {
        $worktreeHostRoot = Split-Path -Parent $worktreeContainer
        $candidates += Join-Path $worktreeHostRoot ".venv312\Scripts\python.exe"
        $candidates += Join-Path $worktreeHostRoot ".venv\Scripts\python.exe"
    }
    $PythonPath = $candidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $PythonPath) {
        $PythonPath = "python"
    }
}
if (-not (Test-Path -LiteralPath $runner)) {
    throw "run_feishu_bot.py not found under $resolvedRoot"
}
if ($Action -in @("start", "preflight")) {
    $env:FEISHU_BOT_ENABLED = "true"
    $env:FEISHU_BOT_RUNTIME_CONTROL_ENABLED = "true"
}

switch ($Action) {
    "preflight" {
        & $PythonPath $runner preflight
        exit $LASTEXITCODE
    }
    "status" {
        & $PythonPath $runner status
        exit $LASTEXITCODE
    }
    "stop" {
        & $PythonPath $runner stop
        exit $LASTEXITCODE
    }
    "start" {
        & $PythonPath $runner start
        exit $LASTEXITCODE
    }
}
