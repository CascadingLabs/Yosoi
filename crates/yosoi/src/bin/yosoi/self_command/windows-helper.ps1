# Embedded in the CLI. Owns the maintenance lock after the parent acknowledges READY.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][int]$ParentId,
    [Parameter(Mandatory=$true)][string]$Executable,
    [Parameter(Mandatory=$true)][string]$ExpectedHash,
    [Parameter(Mandatory=$true)][string]$Staging,
    [Parameter(Mandatory=$true)][string]$Outcome,
    [string]$Candidate
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$directory = Split-Path -Parent $Executable
$receiptPath = Join-Path $directory '.yosoi-install.json'
$lock = Join-Path $directory '.yosoi-maintenance.lock'
$backup = Join-Path $Staging 'previous.exe'
$replaced = $false
$removed = $false
$committed = $false
function Assert-Regular([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing non-regular file: $Path"
    }
}
function Get-Digest([string]$Path) {
    Assert-Regular $Path
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}
try {
    # Capture the process object before acknowledging readiness, avoiding PID reuse.
    $parent = Get-Process -Id $ParentId
    Assert-Regular $Executable
    Assert-Regular $receiptPath
    if (-not (Test-Path -LiteralPath $lock -PathType Leaf)) { throw 'Maintenance lock missing.' }
    [Console]::WriteLine('READY')
    [Console]::Out.Flush()
    Wait-Process -InputObject $parent -Timeout 60 -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $lock -PathType Leaf) -or -not (Test-Path -LiteralPath $Staging -PathType Container)) {
        throw 'Maintenance handoff was cancelled.'
    }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    if ($receipt.schema -ne 1 -or $receipt.method -cne 'standalone' -or $receipt.sha256 -cne $ExpectedHash -or (Get-Digest $Executable) -cne $ExpectedHash) {
        throw 'Installation changed after scheduling maintenance.'
    }
    $root = Split-Path -Parent $directory
    if ((Test-Path (Join-Path $root 'pyvenv.cfg')) -or (Test-Path (Join-Path $root '.crates2.json')) -or (Test-Path (Join-Path $root '.crates.toml'))) {
        throw 'Package-manager metadata appeared after scheduling maintenance.'
    }
    if ($Candidate) {
        $nextReceiptPath = Join-Path $Staging '.yosoi-install.json'
        Assert-Regular $nextReceiptPath
        $next = Get-Content -LiteralPath $nextReceiptPath -Raw | ConvertFrom-Json
        if ($next.schema -ne 1 -or $next.method -cne 'standalone' -or (Get-Digest $Candidate) -cne $next.sha256) { throw 'Staged update does not match its receipt.' }
        Copy-Item -LiteralPath $Executable -Destination $backup
        # File.Replace is atomic on the same volume and fails without deleting the target.
        [IO.File]::Replace($Candidate, $Executable, [NullString]::Value)
        $replaced = $true
        try { [IO.File]::Replace($nextReceiptPath, $receiptPath, [NullString]::Value) }
        catch {
            [IO.File]::Replace($backup, $Executable, [NullString]::Value)
            $replaced = $false
            throw
        }
        $committed = $true
        $result = @{ status = 'success'; action = 'update'; version = $next.version; executable = $Executable }
    } else {
        Remove-Item -LiteralPath $Executable -Force
        $removed = $true
        Remove-Item -LiteralPath $receiptPath -Force
        # Only remove a PATH entry added by our installer, and only from a dedicated
        # directory with no other files. Never delete shared install directories.
        $other = @(Get-ChildItem -LiteralPath $directory -Force | Where-Object { $_.FullName -ne $Staging -and $_.FullName -ne $lock })
        if ($receipt.path_added -and $other.Count -eq 0) {
            $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
            $entries = @($userPath -split ';' | Where-Object { $_ })
            $remaining = @($entries | Where-Object { $_.TrimEnd('\') -ine $directory.TrimEnd('\') })
            [Environment]::SetEnvironmentVariable('Path', ($remaining -join ';'), 'User')
        }
        $result = @{ status = 'success'; action = 'uninstall'; executable = $Executable }
    }
} catch {
    $result = @{ status = 'failed'; error = $_.Exception.Message; executable = $Executable; binary_replaced = $replaced; binary_removed = $removed }
} finally {
    $preserveBackup = $replaced -and -not $committed -and (Test-Path -LiteralPath $backup)
    if ($preserveBackup) { $result.recovery_backup = $backup }
    try {
        if (Test-Path -LiteralPath $lock) { Remove-Item -LiteralPath $lock -Force }
        if (-not $preserveBackup -and (Test-Path -LiteralPath $Staging)) { Remove-Item -LiteralPath $Staging -Recurse -Force }
    } catch {
        $result.status = 'failed'
        $result.cleanup_error = $_.Exception.Message
    } finally {
        $nextOutcome = $Outcome + '.next'
        $result | ConvertTo-Json | Set-Content -LiteralPath $nextOutcome -Encoding UTF8
        [IO.File]::Replace($nextOutcome, $Outcome, [NullString]::Value)
    }
}
