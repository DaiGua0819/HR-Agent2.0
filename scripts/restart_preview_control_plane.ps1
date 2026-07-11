param(
    [switch]$Apply,
    [int]$Port = 18080,
    [string]$ProjectRoot = "C:\RecruitAgent2Preview\hr-agent",
    [string]$PythonPath = "C:\RecruitAgent2Preview\.venv\Scripts\python.exe",
    [string]$TaskName = "RecruitAgent2PreviewControlPlane",
    [string]$HealthUrl = "http://127.0.0.1:18080/api/health"
)

$ErrorActionPreference = "Stop"

if ($Port -eq 8080) {
    throw "Refusing to operate on legacy port 8080."
}
if ($Port -ne 18080) {
    throw "This helper is restricted to preview port 18080."
}

$resolvedProjectRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
$listenerProcess = $null
if ($listener) {
    $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    $commandLine = [string]$listenerProcess.CommandLine
    if (-not $commandLine.Contains($resolvedProjectRoot) -or -not $commandLine.Contains("run_control_plane.py")) {
        throw "Port $Port is owned by an unexpected process: $commandLine"
    }
}

$report = [ordered]@{
    apply = [bool]$Apply
    port = $Port
    taskName = $TaskName
    projectRoot = $resolvedProjectRoot
    listenerPid = if ($listenerProcess) { [int]$listenerProcess.ProcessId } else { 0 }
    listenerCommandLine = if ($listenerProcess) { [string]$listenerProcess.CommandLine } else { "" }
    startedPid = 0
    healthy = $false
}

if (-not $Apply) {
    $report | ConvertTo-Json -Compress
    exit 0
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $resolvedProjectRoot "run_control_plane.py"))) {
    throw "run_control_plane.py not found under $resolvedProjectRoot"
}

$startedAt = Get-Date
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($listenerProcess) {
    Stop-Process -Id $listenerProcess.ProcessId -Force
}

$stopDeadline = (Get-Date).AddSeconds(20)
do {
    Start-Sleep -Milliseconds 250
    $remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} while ($remaining -and (Get-Date) -lt $stopDeadline)
if ($remaining) {
    throw "Port $Port did not close after stopping the previous listener."
}

$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "run_control_plane.py" `
    -WorkingDirectory $resolvedProjectRoot
Set-ScheduledTask -TaskName $TaskName -Action $action | Out-Null
Start-ScheduledTask -TaskName $TaskName

$healthDeadline = (Get-Date).AddSeconds(45)
do {
    Start-Sleep -Milliseconds 500
    $newListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $newListener) {
        continue
    }
    $newProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($newListener.OwningProcess)"
    $newCommandLine = [string]$newProcess.CommandLine
    if (-not $newCommandLine.Contains($resolvedProjectRoot) -or -not $newCommandLine.Contains("run_control_plane.py")) {
        throw "New listener does not belong to the preview project: $newCommandLine"
    }
    $creationTime = [Management.ManagementDateTimeConverter]::ToDateTime($newProcess.CreationDate)
    if ($creationTime -lt $startedAt.AddSeconds(-2)) {
        throw "Listener PID $($newProcess.ProcessId) predates this restart."
    }
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            $report.startedPid = [int]$newProcess.ProcessId
            $report.healthy = $true
            break
        }
    } catch {
        # Continue polling until the service is ready or the deadline expires.
    }
} while ((Get-Date) -lt $healthDeadline)

if (-not $report.healthy) {
    throw "Preview service did not become healthy at $HealthUrl."
}

$report | ConvertTo-Json -Compress
