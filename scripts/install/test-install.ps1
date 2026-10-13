# Run on the Windows release runner using the exact release executable.
param([Parameter(Mandatory)][string]$Executable, [Parameter(Mandatory)][string]$Version)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$work = Join-Path ([IO.Path]::GetTempPath()) ('yosoi-test-' + [Guid]::NewGuid().ToString('N'))
$savedUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$savedPath = $env:PATH
$savedVersion = $env:YOSOI_VERSION
$savedInstallDir = $env:YOSOI_INSTALL_DIR
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $env:YOSOI_VERSION = ''
    $env:YOSOI_INSTALL_DIR = ''
    $fixtureDir = Join-Path $work 'fixtures'
    New-Item -ItemType Directory -Path $fixtureDir | Out-Null
    Copy-Item -LiteralPath $Executable -Destination (Join-Path $fixtureDir 'yosoi.exe')
    $asset = "yosoi-v$Version-windows-x86_64.tar.gz"
    & tar -czf (Join-Path $fixtureDir $asset) -C $fixtureDir yosoi.exe
    if ($LASTEXITCODE -ne 0) { throw 'Fixture archive failed.' }
    $digest = (Get-FileHash (Join-Path $fixtureDir $asset)).Hash.ToLowerInvariant()
    Set-Content -LiteralPath (Join-Path $fixtureDir 'SHA256SUMS') -Value "$digest  $asset"
    $fixtureVersion = $Version
    function Invoke-RestMethod { param($Uri, $TimeoutSec); return @{ version = $fixtureVersion } }
    function Invoke-WebRequest { param([switch]$UseBasicParsing, $Uri, $OutFile, $TimeoutSec); Copy-Item -LiteralPath (Join-Path $fixtureDir ([IO.Path]::GetFileName($Uri))) -Destination $OutFile }
    $installDir = Join-Path $work 'install with spaces'
    $installer = Join-Path $PSScriptRoot 'install.ps1'
    # Latest selection and pinned upgrade both install the actual release binary.
    & $installer -InstallDir $installDir
    & $installer -Version $Version -InstallDir $installDir
    $installed = Join-Path $installDir 'yosoi.exe'
    $receipt = Get-Content -LiteralPath (Join-Path $installDir '.yosoi-install.json') -Raw | ConvertFrom-Json
    if ($receipt.method -cne 'standalone' -or $receipt.version -cne $Version -or $receipt.sha256 -cne (Get-FileHash $installed).Hash.ToLowerInvariant() -or -not $receipt.path_added) { throw 'Standalone installation receipt mismatch.' }
    if ((& $installed --version) -cne "yosoi $Version") { throw 'Installed version mismatch.' }
    & $installed request --help
    if ($LASTEXITCODE -ne 0) { throw 'Installed command failed.' }
    $before = (Get-FileHash $installed).Hash
    Set-Content -LiteralPath (Join-Path $fixtureDir 'SHA256SUMS') -Value ((('0' * 64) + '  ') + $asset)
    $rejected = $false
    try { & $installer -Version $Version -InstallDir $installDir } catch { $rejected = $_.Exception.Message -like '*checksum mismatch*' }
    if (-not $rejected -or (Get-FileHash $installed).Hash -cne $before) { throw 'Corrupt download was not safely rejected.' }
    Write-Output 'PowerShell latest install, pinned upgrade, command execution, and corruption preservation passed.'
} finally {
    [Environment]::SetEnvironmentVariable('Path', $savedUserPath, 'User')
    $env:PATH = $savedPath
    $env:YOSOI_VERSION = $savedVersion
    $env:YOSOI_INSTALL_DIR = $savedInstallDir
    Remove-Item -LiteralPath $work -Recurse -Force
}
