[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Remote = "origin",

    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Branch = "main",

    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$BaseRef = "v0.1.0",

    [string]$OutputDirectory = "",

    [switch]$SkipFetch,

    [switch]$FullHistory,

    [switch]$OpenFolder
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$BundleStage = "检查 Git 和打包参数"
trap {
    $message = $_.Exception.Message -replace '(https?://)[^/@\s]+:[^/@\s]+@', '$1[REDACTED]@'
    Write-Host ""
    Write-Host "生成升级包失败 [E_BUNDLE_BUILD]" -ForegroundColor Red
    Write-Host "阶段：$BundleStage"
    Write-Host "原因：$message"
    Write-Host "当前状态：没有切换本地工作分支，也没有修改项目文件；失败产物不会作为可用包发布。"
    Write-Host "下一步：核对 -Branch；本地缺少分支时去掉 -SkipFetch 重新同步；缺少基线请使用 -FullHistory；磁盘错误请检查输出目录空间与权限。"
    exit 1
}

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
    throw "没有找到 Git，请安装 Git for Windows 并重新打开终端。"
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory "..")).Path
$actualRoot = Invoke-Git -Repository $repositoryRoot -Arguments @("rev-parse", "--show-toplevel") -Capture
$actualRoot = (Resolve-Path -LiteralPath $actualRoot).Path
if ($actualRoot -ne $repositoryRoot) {
    throw "This script must stay inside the Solution Workspace repository."
}
if ($Remote.StartsWith('-') -or $BaseRef.StartsWith('-') -or $Branch.StartsWith('-')) {
    throw "远程、分支和基线名称不能以短横线开头。"
}
Invoke-Git -Repository $repositoryRoot -Arguments @("check-ref-format", "--branch", $Branch)

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repositoryRoot "outputs\offline-updates"
} elseif (-not [IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $repositoryRoot $OutputDirectory
}

$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

if (-not $SkipFetch) {
    $BundleStage = "同步 $Remote/$Branch"
    Write-Host "[1/4] Syncing $Remote/$Branch from GitHub..."
    Invoke-Git -Repository $repositoryRoot -Arguments @(
        "fetch", "--prune", "--tags", $Remote, $Branch
    )
} else {
    Write-Host "[1/4] Using the locally cached $Remote/$Branch ref."
}

$remoteRef = "refs/remotes/$Remote/$Branch"
$BundleStage = "检查目标版本与历史基线"
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
$timestamp = (Get-Date -Format "yyyyMMdd-HHmmss-fff") + "-" + [guid]::NewGuid().ToString('N').Substring(0, 6)
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
    $BundleStage = "生成 bundle 文件"
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

    $BundleStage = "校验生成的文件和目标提交"
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

2. On a server with the new operations command, run:
   sudo solution-workspace update --offline /tmp/$bundleName --branch $Branch

   It verifies the companion checksum, imports the bundle, backs up, upgrades,
   and checks services and the backup timer. Repeating the same version does nothing.
   Optional read-only deployment check:
   sudo solution-workspace doctor

   If help does not list --offline, follow the one-time updater bootstrap in
   docs/UBUNTU_DEPLOYMENT.md first. Both ops.sh and diagnostics.sh are required.


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

    Write-Host "[4/4] 升级包生成并校验完成。" -ForegroundColor Green
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
    try {
        Remove-StagingRepository -StagingPath $stagingRepository -StagingRoot $stagingRoot
    } catch {
        Write-Warning "临时打包仓库清理失败，可稍后清理 $stagingRepository；原因：$($_.Exception.Message)"
    }
}
