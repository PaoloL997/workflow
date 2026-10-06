# Install SeaweedFS as the S3 storage of Workflow (user avatars and signatures)
# as a Windows service. NSSM required, same as WorkflowWaitress.
# Run as Administrator from the project root.
#
# Prerequisites:
#   - weed.exe from https://github.com/seaweedfs/seaweedfs/releases
#     (windows_amd64.zip), unzipped e.g. to C:\SeaweedFS\weed.exe
#   - NSSM: https://nssm.cc/download (or: winget install NSSM.NSSM)
#   - S3_BUCKET, S3_ACCESS_KEY and S3_SECRET_KEY in .env (see README)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\deploy\install-seaweedfs-service.ps1
#   powershell -ExecutionPolicy Bypass -File .\deploy\install-seaweedfs-service.ps1 -WeedPath D:\SeaweedFS\weed.exe -DataDir D:\SeaweedFS\data
#   powershell -ExecutionPolicy Bypass -File .\deploy\install-seaweedfs-service.ps1 -DryRun
#
# Re-running the script reinstalls the service with the current .env keys
# (e.g. after changing them). The data in -DataDir is kept.

param(
    [string]$WeedPath = "C:\SeaweedFS\weed.exe",
    [string]$DataDir = "C:\SeaweedFS\data",
    [string]$NssmPath = "",
    [string]$AppRoot = "",
    [string]$EnvFile = "",
    [string]$ServiceName = "WorkflowStorage",
    [int]$S3Port = 3900,
    [int]$MasterPort = 3901,
    [int]$VolumePort = 3902,
    [int]$FilerPort = 3903,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $AppRoot) {
    $AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $EnvFile) {
    $EnvFile = Join-Path $AppRoot ".env"
}
$DataDir = $DataDir.TrimEnd("\")

function Find-Nssm {
    param([string]$ExplicitPath)
    if ($ExplicitPath -and (Test-Path $ExplicitPath)) { return (Resolve-Path $ExplicitPath).Path }
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $PSScriptRoot "nssm.exe"),
        "C:\Tools\nssm.exe",
        "C:\nssm\nssm.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return (Resolve-Path $c).Path }
    }
    return $null
}

function Read-DotEnv {
    # KEY=VALUE lines of the .env file, as python-dotenv reads them for these keys.
    param([string]$Path)
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith("#")) { continue }
        $eq = $text.IndexOf("=")
        if ($eq -lt 1) { continue }
        $key = $text.Substring(0, $eq).Trim()
        $value = $text.Substring($eq + 1).Trim()
        if ($value.Length -ge 2 -and ($value[0] -eq '"' -or $value[0] -eq "'") -and $value[-1] -eq $value[0]) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

# --- Checks ---------------------------------------------------------------

if (-not (Test-Path -LiteralPath $WeedPath)) {
    throw @"
weed.exe not found at $WeedPath.
Download windows_amd64.zip from https://github.com/seaweedfs/seaweedfs/releases,
unzip it there, or pass -WeedPath C:\path\to\weed.exe
"@
}
$WeedPath = (Resolve-Path -LiteralPath $WeedPath).Path

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing $EnvFile"
}
$envValues = Read-DotEnv $EnvFile
foreach ($name in "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY") {
    if (-not $envValues[$name]) {
        throw "$name is missing in $EnvFile (see README)."
    }
}
$bucket = $envValues["S3_BUCKET"]
$endpoint = "http://127.0.0.1:$S3Port"
$configuredEndpoint = $envValues["S3_ENDPOINT_URL"]
if ($configuredEndpoint -and $configuredEndpoint.TrimEnd("/") -ne $endpoint) {
    Write-Warning "S3_ENDPOINT_URL in .env is '$configuredEndpoint' but the service will listen on $endpoint."
}

$nssm = Find-Nssm -ExplicitPath $NssmPath
if (-not $nssm) {
    if (-not $DryRun) {
        throw @"
NSSM not found. Download from https://nssm.cc/download or run:
  winget install NSSM.NSSM
Then re-run with: -NssmPath C:\path\to\nssm.exe
"@
    }
    $nssm = "nssm"
}

$logsDir = Join-Path $AppRoot "logs"
$logFile = Join-Path $logsDir "seaweedfs-service.log"

# Everything on 127.0.0.1: only Waitress on this machine talks to the storage.
# Metadata (master, filer) and data all live in -dir, so backing up DataDir
# is enough. Iceberg and Lance endpoints are not used: disabled.
$weedArgs = @(
    "server",
    "`"-dir=$DataDir`"",
    "-ip=127.0.0.1",
    "-ip.bind=127.0.0.1",
    "-master.port=$MasterPort",
    "-volume.port=$VolumePort",
    "-filer.port=$FilerPort",
    "-s3",
    "-s3.port=$S3Port",
    "-s3.port.iceberg=0",
    "-s3.port.lance=0"
) -join " "

Write-Host "Installing service '$ServiceName'..."
Write-Host "  weed.exe:  $WeedPath"
Write-Host "  Data:      $DataDir"
Write-Host "  S3:        $endpoint (bucket '$bucket')"
Write-Host "  Log:       $logFile"
Write-Host "  Arguments: $weedArgs"

if ($DryRun) {
    Write-Host "[dry-run] $nssm install $ServiceName `"$WeedPath`""
    Write-Host "[dry-run] $nssm set $ServiceName AppParameters $weedArgs"
    Write-Host "[dry-run] $nssm set $ServiceName AppEnvironmentExtra AWS_ACCESS_KEY_ID=*** AWS_SECRET_ACCESS_KEY=***"
    Write-Host "[dry-run] $nssm start $ServiceName, then: s3.bucket.create -name $bucket"
    exit 0
}

# --- Service --------------------------------------------------------------

foreach ($dir in $DataDir, $logsDir) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
}

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing service '$ServiceName'..."
    if ($existing.Status -eq "Running") {
        & $nssm stop $ServiceName confirm
        Start-Sleep -Seconds 2
    }
    & $nssm remove $ServiceName confirm
    Start-Sleep -Seconds 1
}

& $nssm install $ServiceName $WeedPath
& $nssm set $ServiceName AppParameters $weedArgs
& $nssm set $ServiceName AppDirectory $DataDir
& $nssm set $ServiceName DisplayName "Workflow Storage (SeaweedFS S3)"
& $nssm set $ServiceName Description "S3 storage for Workflow user avatars and signatures ($endpoint)"
# Before WorkflowWaitress, which is a delayed auto start.
& $nssm set $ServiceName Start SERVICE_AUTO_START
# With these and no -s3.config, SeaweedFS creates a single admin identity.
& $nssm set $ServiceName AppEnvironmentExtra "AWS_ACCESS_KEY_ID=$($envValues['S3_ACCESS_KEY'])" "AWS_SECRET_ACCESS_KEY=$($envValues['S3_SECRET_KEY'])"
& $nssm set $ServiceName AppStdout $logFile
& $nssm set $ServiceName AppStderr $logFile
& $nssm set $ServiceName AppStdoutCreationDisposition 4
& $nssm set $ServiceName AppStderrCreationDisposition 4
& $nssm set $ServiceName AppRotateFiles 1
& $nssm set $ServiceName AppRotateBytes 10485760

& $nssm start $ServiceName

# --- Wait for S3, then create the bucket ----------------------------------

$ready = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        Invoke-WebRequest -Uri "$endpoint/" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true
    } catch {
        # 403 without credentials means S3 is up.
        if ($_.Exception.Response) { $ready = $true }
    }
    if ($ready) { break }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Write-Warning "S3 is not answering on $endpoint. Check $logFile"
    exit 1
}

function Invoke-WeedShell {
    # Through cmd: piping a string from Windows PowerShell 5.1 can prepend a
    # BOM that weed shell rejects ("unknown command"). weed shell also logs on
    # stderr, which must not become a terminating error.
    param([string]$Command)
    $ErrorActionPreference = "Continue"
    $out = cmd /s /c "echo $Command| `"$WeedPath`" shell -master=127.0.0.1:$MasterPort 2>&1"
    return ($out | Out-String)
}

$created = $false
for ($i = 1; $i -le 10; $i++) {
    $output = Invoke-WeedShell "s3.bucket.create -name $bucket"
    if ($output -match "created bucket|already exists") {
        $created = $true
        break
    }
    # Right after start the master may still be electing its leader.
    Start-Sleep -Seconds 2
}
if (-not $created) {
    Write-Warning "Could not create bucket '$bucket':`n$output"
    exit 1
}

Write-Host "Service '$ServiceName' running, bucket '$bucket' ready on $endpoint."
Write-Host "Next: Restart-Service WorkflowWaitress, then copy the existing files:"
Write-Host "  poetry run python manage.py copia_media_su_storage --dry-run"
Write-Host "  poetry run python manage.py copia_media_su_storage"
