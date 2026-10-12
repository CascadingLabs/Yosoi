# Install a verified prebuilt CLI. Supports Windows x86-64 only.
[CmdletBinding()]
param(
    [string]$Version = $env:YOSOI_VERSION,
    [string]$InstallDir = $env:YOSOI_INSTALL_DIR
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Use install.sh on Linux and macOS.'
}
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne [System.Runtime.InteropServices.Architecture]::X64) {
    throw 'The Windows CLI currently supports x86-64 only.'
}
if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA 'Yosoi\bin' }
if (-not [IO.Path]::IsPathRooted($InstallDir)) { throw 'InstallDir must be an absolute path.' }
$destination = Join-Path $InstallDir 'yosoi.exe'
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$root = Split-Path -Parent $InstallDir
if ((Test-Path (Join-Path $root 'pyvenv.cfg')) -or (Test-Path (Join-Path $root '.crates2.json')) -or (Test-Path (Join-Path $root '.crates.toml'))) {
    throw 'Destination is package-managed. Uninstall through UV/Python or Cargo before changing installation methods.'
}
$receiptPath = Join-Path $InstallDir '.yosoi-install.json'
$previousPathAdded = $false
if (Test-Path -LiteralPath $receiptPath) {
    $item = Get-Item -LiteralPath $receiptPath -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid installation receipt destination.' }
    $previous = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    if ((Test-Path -LiteralPath $destination) -and $previous.schema -eq 1 -and $previous.method -ceq 'standalone' -and $previous.sha256 -ceq (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()) {
        $previousPathAdded = [bool]$previous.path_added
    }
}
if (Test-Path $destination) {
    $existing = Get-Item -LiteralPath $destination -Force
    if ($existing.PSIsContainer -or ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to replace a directory or link at $destination. Remove the previous tool installation first."
    }
}
$work = Join-Path ([IO.Path]::GetTempPath()) ('yosoi-' + [Guid]::NewGuid().ToString('N'))
$staged = $null
$receiptStaged = $null
$lockStream = $null
$backup = $null
$replaced = $false
New-Item -ItemType Directory -Path $work | Out-Null
try {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $lock = Join-Path $InstallDir '.yosoi-maintenance.lock'
    $lockStream = [IO.File]::Open($lock, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $base = 'https://github.com/CascadingLabs/Yosoi/releases'
    if (-not $Version) {
        $plan = Invoke-RestMethod -Uri "$base/latest/download/release-plan.json" -TimeoutSec 60
        $Version = $plan.version
    }
    if ($Version -cnotmatch '^0\.[1-9][0-9]*\.(0|[1-9][0-9]*)(-rc\.[1-9][0-9]*)?$') {
        throw 'Invalid release version.'
    }
    $asset = "yosoi-v$Version-windows-x86_64.tar.gz"
    $url = "$base/download/v$Version"
    $checksums = Join-Path $work 'SHA256SUMS'
    $archive = Join-Path $work $asset
    Invoke-WebRequest -UseBasicParsing -Uri "$url/SHA256SUMS" -OutFile $checksums -TimeoutSec 60
    Invoke-WebRequest -UseBasicParsing -Uri "$url/$asset" -OutFile $archive -TimeoutSec 300
    $entries = @(Get-Content $checksums | Where-Object { $_ -cmatch ('^[0-9a-f]{64}  ' + [regex]::Escape($asset) + '$') })
    if ($entries.Count -ne 1) { throw 'Missing or duplicate archive checksum.' }
    $expected = $entries[0].Substring(0, 64)
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant() -cne $expected) {
        throw 'Archive checksum mismatch.'
    }
    $members = @(& tar -tzf $archive)
    if ($LASTEXITCODE -ne 0 -or $members.Count -ne 1 -or $members[0] -cne 'yosoi.exe') {
        throw 'Unexpected archive contents.'
    }
    & tar -xzf $archive -C $work
    if ($LASTEXITCODE -ne 0) { throw 'Archive extraction failed.' }
    $binary = Join-Path $work 'yosoi.exe'
    $item = Get-Item -LiteralPath $binary -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Archive must contain a regular executable.'
    }
    $identity = & $binary --version
    if ($LASTEXITCODE -ne 0 -or $identity -cne "yosoi $Version") { throw 'CLI version does not match the release.' }
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $staged = Join-Path $InstallDir ('.yosoi-' + [Guid]::NewGuid().ToString('N') + '.exe')
    Copy-Item -LiteralPath $binary -Destination $staged
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @($userPath -split ';' | Where-Object { $_ })
    $pathAdded = $previousPathAdded -or ($entries -notcontains $InstallDir)
    $receiptStaged = Join-Path $InstallDir ('.yosoi-receipt-' + [Guid]::NewGuid().ToString('N') + '.json')
    @{ schema = 1; method = 'standalone'; version = $Version; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $staged).Hash.ToLowerInvariant(); path_added = $pathAdded } | ConvertTo-Json | Set-Content -LiteralPath $receiptStaged -Encoding ASCII
    if (Test-Path -LiteralPath $destination) {
        $backup = Join-Path $InstallDir ('.yosoi-backup-' + [Guid]::NewGuid().ToString('N') + '.exe')
        Copy-Item -LiteralPath $destination -Destination $backup
    }
    Move-Item -LiteralPath $staged -Destination $destination -Force
    $staged = $null
    $replaced = $true
    Move-Item -LiteralPath $receiptStaged -Destination $receiptPath -Force
    $receiptStaged = $null
    $replaced = $false
    if ($entries -notcontains $InstallDir) {
        [Environment]::SetEnvironmentVariable('Path', (($entries + $InstallDir) -join ';'), 'User')
    }
    if (@($env:PATH -split ';') -notcontains $InstallDir) { $env:PATH = "$InstallDir;$env:PATH" }
    Write-Output "Installed Yosoi $Version to $destination"
    Write-Output 'Run: yosoi --help. Open a new terminal to refresh PATH in other sessions.'
} finally {
    if ($replaced) {
        if ($backup) { Move-Item -LiteralPath $backup -Destination $destination -Force; $backup = $null }
        else { Remove-Item -LiteralPath $destination -Force }
    }
    if ($staged -and (Test-Path -LiteralPath $staged)) { Remove-Item -LiteralPath $staged -Force }
    if ($receiptStaged -and (Test-Path -LiteralPath $receiptStaged)) { Remove-Item -LiteralPath $receiptStaged -Force }
    if ($backup -and (Test-Path -LiteralPath $backup)) { Remove-Item -LiteralPath $backup -Force }
    if ($lockStream) { $lockStream.Dispose(); Remove-Item -LiteralPath $lock -Force }
    Remove-Item -LiteralPath $work -Recurse -Force
}
