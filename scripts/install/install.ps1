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
if (Test-Path $destination) {
    $existing = Get-Item -LiteralPath $destination -Force
    if ($existing.PSIsContainer -or ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to replace a directory or link at $destination. Remove the previous tool installation first."
    }
}
$work = Join-Path ([IO.Path]::GetTempPath()) ('yosoi-' + [Guid]::NewGuid().ToString('N'))
$staged = $null
New-Item -ItemType Directory -Path $work | Out-Null
try {
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
    Move-Item -LiteralPath $staged -Destination $destination -Force
    $staged = $null
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @($userPath -split ';' | Where-Object { $_ })
    if ($entries -notcontains $InstallDir) {
        [Environment]::SetEnvironmentVariable('Path', (($entries + $InstallDir) -join ';'), 'User')
    }
    if (@($env:PATH -split ';') -notcontains $InstallDir) { $env:PATH = "$InstallDir;$env:PATH" }
    Write-Output "Installed Yosoi $Version to $destination"
    Write-Output 'Run: yosoi --help. Open a new terminal to refresh PATH in other sessions.'
} finally {
    if ($staged -and (Test-Path -LiteralPath $staged)) { Remove-Item -LiteralPath $staged -Force }
    Remove-Item -LiteralPath $work -Recurse -Force
}
