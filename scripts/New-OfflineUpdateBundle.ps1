[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Remote = "origin",

    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Branch = "mvp",

    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$BaseRef = "v0.1.0",

    [string]$OutputDirectory = "",

    [switch]$SkipFetch,

    [switch]$FullHistory,

    [switch]$OpenFolder
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Repository,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [switch]$Capture
    )

    if ($Capture) {
        $result = & git.exe -C $Repository @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
        }
        return ($result -join "`n").Trim()
    }

    & git.exe -C $Repository @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Remove-StagingRepository {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StagingPath,

        [Parameter(Mandatory = $true)]
        [string]$StagingRoot
    )

    if (-not (Test-Path -LiteralPath $StagingPath)) {
        return
    }

    $resolvedPath = (Resolve-Path -LiteralPath $StagingPath).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $StagingRoot).Path
    $rootPrefix = $resolvedRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
        [IO.Path]::DirectorySeparatorChar
    $leafName = [IO.Path]::GetFileName($resolvedPath)

    if (-not $resolvedPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $leafName.StartsWith("bundle-stage-", [StringComparison]::Ordinal)) {
        throw "Refusing to remove unexpected staging path: $resolvedPath"
    }

    Remove-Item -LiteralPath $resolvedPath -Recurse -Force
}

if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    throw "Git was not found. Install Git for Windows and try again."
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory "..")).Path
$actualRoot = Invoke-Git -Repository $repositoryRoot -Arguments @("rev-parse", "--show-toplevel") -Capture
$actualRoot = (Resolve-Path -LiteralPath $actualRoot).Path
if ($actualRoot -ne $repositoryRoot) {
    throw "This script must stay inside the Solution Workspace repository."
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repositoryRoot "outputs\offline-updates"
} elseif (-not [IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $repositoryRoot $OutputDirectory
}

$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

if (-not $SkipFetch) {
    Write-Host "[1/4] Syncing $Remote/$Branch from GitHub..."
    Invoke-Git -Repository $repositoryRoot -Arguments @(
        "fetch", "--prune", "--tags", $Remote, $Branch
    )
} else {
    Write-Host "[1/4] Using the locally cached $Remote/$Branch ref."
}

$remoteRef = "refs/remotes/$Remote/$Branch"
$targetCommit = Invoke-Git -Repository $repositoryRoot -Arguments @(
    "rev-parse", "--verify", "$remoteRef^{commit}"
) -Capture
$shortCommit = Invoke-Git -Repository $repositoryRoot -Arguments @(
    "rev-parse", "--short=8", $targetCommit
) -Capture
$baseCommit = ""
$bundleRevision = "refs/heads/$Branch"
$baseLabel = "full-history"
if (-not $FullHistory) {
    $baseCommit = Invoke-Git -Repository $repositoryRoot -Arguments @(
        "rev-parse", "--verify", "$BaseRef^{commit}"
    ) -Capture
    Invoke-Git -Repository $repositoryRoot -Arguments @(
        "merge-base", "--is-ancestor", $baseCommit, $targetCommit
    )
    $bundleRevision = "$baseCommit..refs/heads/$Branch"
    $baseLabel = $BaseRef -replace '[^A-Za-z0-9._-]', '-'
}
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$artifactBase = "solution-workspace-update-$timestamp-from-$baseLabel-to-$shortCommit"
$bundlePath = Join-Path $OutputDirectory "$artifactBase.bundle"
$checksumPath = "$bundlePath.sha256"
$guidePath = Join-Path $OutputDirectory "$artifactBase-upgrade.txt"

$stagingRoot = Join-Path $repositoryRoot ".run"
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
$stagingRepository = Join-Path $stagingRoot (
    "bundle-stage-" + [guid]::NewGuid().ToString("N") + ".git"
)
New-Item -ItemType Directory -Path $stagingRepository | Out-Null

try {
    Write-Host "[2/4] Creating the offline Git bundle..."
    Invoke-Git -Repository $stagingRepository -Arguments @("init", "--bare")
    Invoke-Git -Repository $stagingRepository -Arguments @(
        "fetch",
        $repositoryRoot,
        "${remoteRef}:refs/heads/$Branch"
    )
    Invoke-Git -Repository $stagingRepository -Arguments @(
        "bundle", "create", $bundlePath, $bundleRevision
    )

    Write-Host "[3/4] Verifying the bundle and calculating SHA-256..."
    Invoke-Git -Repository $repositoryRoot -Arguments @("bundle", "verify", $bundlePath)
    $bundleHead = (& git.exe bundle list-heads $bundlePath | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read the generated bundle head: $bundleHead"
    }
    $expectedHead = "$targetCommit refs/heads/$Branch"
    if ($bundleHead -ne $expectedHead) {
        throw "Generated bundle head is unexpected. Expected '$expectedHead', got '$bundleHead'."
    }

    $checksum = (Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $bundleName = [IO.Path]::GetFileName($bundlePath)
    $checksumName = [IO.Path]::GetFileName($checksumPath)
    [IO.File]::WriteAllText(
        $checksumPath,
        "$checksum  $bundleName`n",
        [Text.Encoding]::ASCII
    )

    $minimumServerText = if ($FullHistory) {
        "No Git history prerequisite (full-history package)."
    } else {
        "The server must already contain $BaseRef ($baseCommit) or a later descendant."
    }
    $guide = @"
Solution Workspace offline update package

Target branch: $Branch
Target commit: $targetCommit
SHA-256: $checksum
Compatibility: $minimumServerText

1. Upload both files to the Ubuntu server's /tmp directory:
   $bundleName
   $checksumName

2. On the server, run from /tmp:
   sha256sum -c $checksumName
   sudo install -d -m 0700 -o root -g root /var/lib/solution-workspace/releases
   sudo install -m 0600 -o root -g root $bundleName /var/lib/solution-workspace/releases/solution-workspace-update.bundle
   sudo git -C /opt/solution-workspace bundle verify /var/lib/solution-workspace/releases/solution-workspace-update.bundle
   sudo solution-workspace update /var/lib/solution-workspace/releases/solution-workspace-update.bundle $Branch
   sudo solution-workspace health
   sudo systemctl is-enabled solution-workspace-backup.timer
   sudo systemctl is-active solution-workspace-backup.timer
   sudo git -C /opt/solution-workspace rev-parse HEAD


The final commit must be:
   $targetCommit

Important: the bundle contains Git code and history, but not npm or Python dependencies.
The server can update without GitHub, but it still needs its dependency cache or access to
the configured npm/Python package source if dependencies changed.

If bundle verification reports a missing prerequisite on an unusually old server, create
a one-time full-history package with:
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/New-OfflineUpdateBundle.ps1 -FullHistory
"@
    [IO.File]::WriteAllText($guidePath, $guide, [Text.UTF8Encoding]::new($true))

    Write-Host "[4/4] Package completed." -ForegroundColor Green
    Write-Host "Bundle:   $bundlePath"
    Write-Host "Checksum: $checksumPath"
    Write-Host "Guide:    $guidePath"
    Write-Host "Commit:   $targetCommit"
    Write-Host "SHA-256:  $checksum"

    if ($OpenFolder) {
        try {
            Start-Process explorer.exe -ArgumentList @($OutputDirectory)
        } catch {
            Write-Warning "The package is ready, but its folder could not be opened automatically."
        }
    }
} catch {
    foreach ($generatedPath in @($bundlePath, $checksumPath, $guidePath)) {
        if (Test-Path -LiteralPath $generatedPath) {
            Remove-Item -LiteralPath $generatedPath -Force
        }
    }
    throw
} finally {
    Remove-StagingRepository -StagingPath $stagingRepository -StagingRoot $stagingRoot
}
