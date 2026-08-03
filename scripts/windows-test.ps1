[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status",

    [ValidateRange(1, 65535)]
    [int]$BackendPort = 0,

    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 0,

    [switch]$AutoSelectPorts
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$RunRoot = Join-Path $ProjectRoot ".run\windows-test"
$DefaultBackendPort = 8787
$DefaultFrontendPort = 5174

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

function Get-EnvironmentFileValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $pattern = "^\s*$([regex]::Escape($Key))\s*=\s*(?<value>.*)\s*$"
    foreach ($line in Get-Content -LiteralPath $Path) {
        $match = [regex]::Match($line, $pattern)
        if ($match.Success) {
            return $match.Groups["value"].Value.Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Initialize-Ports {
    if ($BackendPort -eq 0) {
        $configuredPort = Get-EnvironmentFileValue `
            -Path (Join-Path $ProjectRoot ".env") `
            -Key "MVP_SERVER_PORT"
        [int]$parsedPort = 0
        if ($null -ne $configuredPort -and
            [int]::TryParse($configuredPort, [ref]$parsedPort) -and
            $parsedPort -ge 1 -and
            $parsedPort -le 65535) {
            $script:BackendPort = $parsedPort
        }
        else {
            $script:BackendPort = $DefaultBackendPort
        }
    }

    if ($FrontendPort -eq 0) {
        $script:FrontendPort = $DefaultFrontendPort
    }
}

function Get-BackendReadyUrl {
    return "http://127.0.0.1:$BackendPort/api/v1/health/ready"
}

function Get-FrontendReadyUrl {
    return "http://127.0.0.1:$FrontendPort/"
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
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$ListenerPid = 0
    )

    $record = [ordered]@{
        name = $Name
        pid = $Process.Id
        start_time_ticks = $Process.StartTime.ToUniversalTime().Ticks
        port = $Port
        listener_pid = $ListenerPid
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
        if ($record.PSObject.Properties.Name -contains "port") {
            $process | Add-Member -NotePropertyName ManagedPort -NotePropertyValue ([int]$record.port) -Force
        }
        if ($record.PSObject.Properties.Name -contains "listener_pid") {
            $process | Add-Member -NotePropertyName ManagedListenerPid -NotePropertyValue ([int]$record.listener_pid) -Force
        }
        return $process
    }
    catch {
        Remove-PidFile -Name $Name
        return $null
    }
}

function Get-ListenerInfo {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listenerPids = @{}
    $listeners = @(Get-NetTCPConnection `
        -State Listen `
        -LocalPort $Port `
        -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $listenerPids[[int]$listener.OwningProcess] = $true
    }

    # Get-NetTCPConnection can hide listeners in restricted terminal sessions.
    # netstat still exposes their PID, so use it as a fallback (and deduplicate).
    $escapedPort = [regex]::Escape([string]$Port)
    foreach ($line in netstat.exe -ano -p tcp) {
        $match = [regex]::Match(
            $line,
            "^\s*TCP\s+(?<local>\S+)\s+\S+\s+LISTENING\s+(?<pid>\d+)\s*$"
        )
        if ($match.Success -and $match.Groups["local"].Value -match "(?:\]|:)$escapedPort$") {
            $listenerPids[[int]$match.Groups["pid"].Value] = $true
        }
    }

    foreach ($listenerPid in $listenerPids.Keys | Sort-Object) {
        $process = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
        [pscustomobject]@{
            Pid = [int]$listenerPid
            ProcessName = if ($null -ne $process) { $process.ProcessName } else { "unknown" }
            Path = if ($null -ne $process) { $process.Path } else { $null }
        }
    }
}

function Format-ListenerInfo {
    param([Parameter(Mandatory = $true)]$Listener)

    $pathText = if ([string]::IsNullOrWhiteSpace($Listener.Path)) {
        ""
    }
    else {
        " ($($Listener.Path))"
    }
    return "PID $($Listener.Pid) [$($Listener.ProcessName)]$pathText"
}

function Find-AvailablePort {
    param([Parameter(Mandatory = $true)][int]$StartingPort)

    for ($candidate = $StartingPort; $candidate -le 65535; $candidate++) {
        if (@(Get-ListenerInfo -Port $candidate).Count -eq 0) {
            return $candidate
        }
    }
    throw "No available TCP port was found from $StartingPort through 65535."
}

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $listeners = @(Get-ListenerInfo -Port $Port)
    if ($listeners.Count -gt 0) {
        $owners = $listeners | ForEach-Object { Format-ListenerInfo -Listener $_ }
        throw "$Name cannot start: port $Port is already used by $($owners -join '; '). Use a different port or pass -AutoSelectPorts."
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
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "$Name exited before becoming ready."
        }
        $listeners = @(Get-ListenerInfo -Port $Port)
        if ($listeners.Count -gt 0 -and (Test-Endpoint -Url $Url)) {
            return $listeners[0]
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

    if ($AutoSelectPorts) {
        $selectedPort = Find-AvailablePort -StartingPort $BackendPort
        if ($selectedPort -ne $BackendPort) {
            Write-Host "Backend port $BackendPort is in use; using $selectedPort."
            $script:BackendPort = $selectedPort
        }
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
    Save-ProcessRecord -Name "backend" -Process $process -Port $BackendPort

    try {
        $listener = Wait-Endpoint `
            -Name "Backend" `
            -Url (Get-BackendReadyUrl) `
            -Process $process `
            -Port $BackendPort
        Save-ProcessRecord `
            -Name "backend" `
            -Process $process `
            -Port $BackendPort `
            -ListenerPid $listener.Pid
        Write-Host "Backend ready: $(Get-BackendReadyUrl) (launcher PID $($process.Id), listener $(Format-ListenerInfo -Listener $listener))"
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

    if ($AutoSelectPorts) {
        $selectedPort = Find-AvailablePort -StartingPort $FrontendPort
        if ($selectedPort -ne $FrontendPort) {
            Write-Host "Frontend port $FrontendPort is in use; using $selectedPort."
            $script:FrontendPort = $selectedPort
        }
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
    $previousApiBase = [Environment]::GetEnvironmentVariable(
        "MVP_INTERNAL_API_BASE_URL",
        [System.EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "MVP_INTERNAL_API_BASE_URL",
        "http://127.0.0.1:$BackendPort",
        [System.EnvironmentVariableTarget]::Process
    )
    try {
        $process = Start-Process `
            -FilePath $npm.Source `
            -ArgumentList @("run", "dev", "--", "--port", "$FrontendPort", "--strictPort") `
            -WorkingDirectory $FrontendRoot `
            -RedirectStandardOutput (Join-Path $RunRoot "frontend.out.log") `
            -RedirectStandardError (Join-Path $RunRoot "frontend.err.log") `
            -WindowStyle Hidden `
            -PassThru
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            "MVP_INTERNAL_API_BASE_URL",
            $previousApiBase,
            [System.EnvironmentVariableTarget]::Process
        )
    }
    Save-ProcessRecord -Name "frontend" -Process $process -Port $FrontendPort

    try {
        $listener = Wait-Endpoint `
            -Name "Frontend" `
            -Url (Get-FrontendReadyUrl) `
            -Process $process `
            -Port $FrontendPort
        Save-ProcessRecord `
            -Name "frontend" `
            -Process $process `
            -Port $FrontendPort `
            -ListenerPid $listener.Pid
        Write-Host "Frontend ready: $(Get-FrontendReadyUrl) (launcher PID $($process.Id), listener $(Format-ListenerInfo -Listener $listener))"
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
    Write-Host "Workspace is ready: $(Get-FrontendReadyUrl)" -ForegroundColor Green
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
    if ($null -ne $managed -and $managed.PSObject.Properties.Name -contains "ManagedPort") {
        $Port = [int]$managed.ManagedPort
        if ($Name -eq "backend") {
            $Url = "http://127.0.0.1:$Port/api/v1/health/ready"
        }
        else {
            $Url = "http://127.0.0.1:$Port/"
        }
    }
    $listeners = @(Get-ListenerInfo -Port $Port)
    $healthy = Test-Endpoint -Url $Url

    if ($null -ne $managed) {
        $healthText = if ($healthy) { "ready" } else { "not ready" }
        $listenerText = if ($listeners.Count -gt 0) {
            $listeners | ForEach-Object { Format-ListenerInfo -Listener $_ }
        }
        else {
            "none"
        }
        Write-Host "$Name`: managed launcher PID $($managed.Id), port $Port, $healthText, listener $($listenerText -join '; ')"
    }
    elseif ($listeners.Count -gt 0) {
        $listenerText = $listeners | ForEach-Object { Format-ListenerInfo -Listener $_ }
        Write-Host "$Name`: unmanaged listener on port ${Port}: $($listenerText -join '; ')"
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
        -Url (Get-BackendReadyUrl)
    Show-ServiceStatus `
        -Name "frontend" `
        -Port $FrontendPort `
        -Url (Get-FrontendReadyUrl)
}

Normalize-PathEnvironment
Initialize-Ports

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
