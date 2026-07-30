[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$RunRoot = Join-Path $ProjectRoot ".run\windows-test"
$BackendPort = 8787
$FrontendPort = 5174
$BackendReadyUrl = "http://127.0.0.1:$BackendPort/api/v1/health/ready"
$FrontendReadyUrl = "http://127.0.0.1:$FrontendPort/"

function Normalize-PathEnvironment {
    # Some terminal hosts inject both Path and PATH. Windows PowerShell's
    # Start-Process rejects that duplicate pair, so keep one canonical entry.
    $variables = [System.Environment]::GetEnvironmentVariables()
    $pathKeys = @(
        $variables.Keys |
            Where-Object { [string]$_ -imatch "^path$" }
    )
    if ($pathKeys.Count -le 1) {
        return
    }

    $preferredKey = $pathKeys |
        Where-Object { [string]$_ -ceq "Path" } |
        Select-Object -First 1
    if ($null -eq $preferredKey) {
        $preferredKey = $pathKeys[0]
    }
    $pathValue = [string]$variables[$preferredKey]

    foreach ($key in $pathKeys) {
        [System.Environment]::SetEnvironmentVariable(
            [string]$key,
            $null,
            [System.EnvironmentVariableTarget]::Process
        )
    }
    [System.Environment]::SetEnvironmentVariable(
        "Path",
        $pathValue,
        [System.EnvironmentVariableTarget]::Process
    )
}

function Ensure-RunDirectory {
    if (-not (Test-Path -LiteralPath $RunRoot)) {
        New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
    }
}

function Get-PidFile {
    param([Parameter(Mandatory = $true)][string]$Name)
    return Join-Path $RunRoot "$Name.pid.json"
}

function Remove-PidFile {
    param([Parameter(Mandatory = $true)][string]$Name)
    $pidFile = Get-PidFile -Name $Name
    if (Test-Path -LiteralPath $pidFile) {
        Remove-Item -LiteralPath $pidFile -Force
    }
}

function Save-ProcessRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process
    )

    $record = [ordered]@{
        name = $Name
        pid = $Process.Id
        start_time_ticks = $Process.StartTime.ToUniversalTime().Ticks
    }
    $record |
        ConvertTo-Json |
        Set-Content -LiteralPath (Get-PidFile -Name $Name) -Encoding UTF8
}

function Get-ManagedProcess {
    param([Parameter(Mandatory = $true)][string]$Name)

    $pidFile = Get-PidFile -Name $Name
    if (-not (Test-Path -LiteralPath $pidFile)) {
        return $null
    }

    try {
        $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$record.pid) -ErrorAction Stop
        $actualTicks = $process.StartTime.ToUniversalTime().Ticks
        if ($actualTicks -ne [long]$record.start_time_ticks) {
            Remove-PidFile -Name $Name
            return $null
        }
        return $process
    }
    catch {
        Remove-PidFile -Name $Name
        return $null
    }
}

function Get-ListenerPid {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listener = Get-NetTCPConnection `
        -State Listen `
        -LocalPort $Port `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) {
        return $null
    }
    return [int]$listener.OwningProcess
}

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $listenerPid = Get-ListenerPid -Port $Port
    if ($null -ne $listenerPid) {
        throw "$Name cannot start: port $Port is already used by unmanaged PID $listenerPid."
    }
}

function Test-Endpoint {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-Endpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "$Name exited before becoming ready."
        }
        if (Test-Endpoint -Url $Url) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become ready within $TimeoutSeconds seconds."
}

function Reset-LogFiles {
    param([Parameter(Mandatory = $true)][string]$Name)

    foreach ($suffix in @("out.log", "err.log")) {
        $path = Join-Path $RunRoot "$Name.$suffix"
        if (Test-Path -LiteralPath $path) {
            Clear-Content -LiteralPath $path
        }
    }
}

function Show-ErrorLog {
    param([Parameter(Mandatory = $true)][string]$Name)

    $path = Join-Path $RunRoot "$Name.err.log"
    if (Test-Path -LiteralPath $path) {
        $lines = Get-Content -LiteralPath $path -Tail 20
        if ($lines) {
            Write-Host ""
            Write-Host "$Name error log:"
            $lines | ForEach-Object { Write-Host $_ }
        }
    }
}

function Start-Backend {
    $managed = Get-ManagedProcess -Name "backend"
    if ($null -ne $managed) {
        Write-Host "Backend is already managed (PID $($managed.Id))."
        return
    }

    Assert-PortAvailable -Name "Backend" -Port $BackendPort
    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Python environment is missing. Run: uv sync --all-groups"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") `
            -Destination (Join-Path $ProjectRoot ".env")
        Write-Host "Created .env from .env.example."
    }

    Write-Host "Applying database migrations..."
    Push-Location $ProjectRoot
    try {
        & $python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "Database migration failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    Reset-LogFiles -Name "backend"
    $process = Start-Process `
        -FilePath $python `
        -ArgumentList @("server.py", "--host", "127.0.0.1", "--port", "$BackendPort") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput (Join-Path $RunRoot "backend.out.log") `
        -RedirectStandardError (Join-Path $RunRoot "backend.err.log") `
        -WindowStyle Hidden `
        -PassThru
    Save-ProcessRecord -Name "backend" -Process $process

    try {
        Wait-Endpoint -Name "Backend" -Url $BackendReadyUrl -Process $process
        Write-Host "Backend ready: $BackendReadyUrl (PID $($process.Id))"
    }
    catch {
        Show-ErrorLog -Name "backend"
        Stop-ManagedService -Name "backend"
        throw
    }
}

function Start-Frontend {
    $managed = Get-ManagedProcess -Name "frontend"
    if ($null -ne $managed) {
        Write-Host "Frontend is already managed (PID $($managed.Id))."
        return
    }

    Assert-PortAvailable -Name "Frontend" -Port $FrontendPort
    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($null -eq $npm) {
        throw "npm.cmd was not found. Install Node.js 22.13 or newer."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendRoot "node_modules\vinext"))) {
        throw "Frontend dependencies are missing. Run: cd frontend; npm.cmd ci"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendRoot ".env.local"))) {
        Copy-Item -LiteralPath (Join-Path $FrontendRoot ".env.example") `
            -Destination (Join-Path $FrontendRoot ".env.local")
        Write-Host "Created frontend/.env.local from .env.example."
    }

    Reset-LogFiles -Name "frontend"
    $process = Start-Process `
        -FilePath $npm.Source `
        -ArgumentList @("run", "dev") `
        -WorkingDirectory $FrontendRoot `
        -RedirectStandardOutput (Join-Path $RunRoot "frontend.out.log") `
        -RedirectStandardError (Join-Path $RunRoot "frontend.err.log") `
        -WindowStyle Hidden `
        -PassThru
    Save-ProcessRecord -Name "frontend" -Process $process

    try {
        Wait-Endpoint -Name "Frontend" -Url $FrontendReadyUrl -Process $process
        Write-Host "Frontend ready: $FrontendReadyUrl (PID $($process.Id))"
    }
    catch {
        Show-ErrorLog -Name "frontend"
        Stop-ManagedService -Name "frontend"
        throw
    }
}

function Stop-ManagedService {
    param([Parameter(Mandatory = $true)][string]$Name)

    $process = Get-ManagedProcess -Name $Name
    if ($null -eq $process) {
        Write-Host "$Name is not managed by this script."
        return
    }

    $pidToStop = $process.Id
    & taskkill.exe /PID $pidToStop /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stop $Name process tree (PID $pidToStop)."
    }
    Remove-PidFile -Name $Name
    Write-Host "Stopped $Name (PID $pidToStop)."
}

function Start-All {
    Ensure-RunDirectory
    try {
        Start-Backend
        Start-Frontend
    }
    catch {
        Write-Host ""
        Write-Host "Start failed: $($_.Exception.Message)" -ForegroundColor Red
        Stop-ManagedService -Name "frontend"
        Stop-ManagedService -Name "backend"
        throw
    }

    Write-Host ""
    Write-Host "Workspace is ready: $FrontendReadyUrl" -ForegroundColor Green
    Write-Host "Logs: $RunRoot"
}

function Stop-All {
    Ensure-RunDirectory
    Stop-ManagedService -Name "frontend"
    Stop-ManagedService -Name "backend"
}

function Show-ServiceStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $managed = Get-ManagedProcess -Name $Name
    $listenerPid = Get-ListenerPid -Port $Port
    $healthy = Test-Endpoint -Url $Url

    if ($null -ne $managed) {
        $healthText = if ($healthy) { "ready" } else { "not ready" }
        Write-Host "$Name`: managed, PID $($managed.Id), port $Port, $healthText"
    }
    elseif ($null -ne $listenerPid) {
        Write-Host "$Name`: unmanaged listener, PID $listenerPid, port $Port"
    }
    else {
        Write-Host "$Name`: stopped"
    }
}

function Show-Status {
    Ensure-RunDirectory
    Show-ServiceStatus `
        -Name "backend" `
        -Port $BackendPort `
        -Url $BackendReadyUrl
    Show-ServiceStatus `
        -Name "frontend" `
        -Port $FrontendPort `
        -Url $FrontendReadyUrl
}

Normalize-PathEnvironment

switch ($Action) {
    "start" {
        Start-All
    }
    "stop" {
        Stop-All
    }
    "restart" {
        Stop-All
        Start-All
    }
    "status" {
        Show-Status
    }
}
