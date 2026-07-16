param(
    [ValidateSet("start", "preflight", "status", "stop")]
    [string]$Action = "status",
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$resolvedRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$runner = Join-Path $resolvedRoot "scripts\run_feishu_bot.py"
$runtimeDir = Join-Path $resolvedRoot "data\feishu_bot"
$stdoutPath = Join-Path $runtimeDir "bot.out.log"
$stderrPath = Join-Path $runtimeDir "bot.err.log"

if (-not $PythonPath) {
    $candidate = Join-Path $resolvedRoot ".venv312\Scripts\python.exe"
    $PythonPath = if (Test-Path -LiteralPath $candidate) { $candidate } else { "python" }
}
if (-not (Test-Path -LiteralPath $runner)) {
    throw "run_feishu_bot.py not found under $resolvedRoot"
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
        & $PythonPath $runner preflight
        if ($LASTEXITCODE -ne 0) {
            throw "Feishu bot preflight failed."
        }
        New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
        $process = Start-Process `
            -FilePath $PythonPath `
            -ArgumentList @($runner, "serve") `
            -WorkingDirectory $resolvedRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -PassThru
        [ordered]@{
            started = $true
            launcherPid = [int]$process.Id
            runtimeDir = $runtimeDir
        } | ConvertTo-Json -Compress
        exit 0
    }
}
