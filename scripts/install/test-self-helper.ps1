# Focused native Windows proof for deferred replacement and failure preservation.
param([Parameter(Mandatory)][string]$Executable, [Parameter(Mandatory)][string]$Version)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$work = Join-Path ([IO.Path]::GetTempPath()) ('yosoi-self-helper-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$parent = $null
$helper = $null
function Start-Redirected([string]$Script, [string[]]$Arguments) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = 'powershell.exe'
    $info.UseShellExecute = $false
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in (@('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $Script) + $Arguments)) {
        $info.ArgumentList.Add($argument)
    }
    return [Diagnostics.Process]::Start($info)
}
function Wait-Ready($Process) {
    $ready = $Process.StandardOutput.ReadLineAsync()
    if (-not $ready.Wait(15000) -or $ready.Result -cne 'READY') { throw 'Helper fixture did not acknowledge startup.' }
}
try {
    foreach ($failure in @($false, $true)) {
        $directory = Join-Path $work ([Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $directory | Out-Null
        $installed = Join-Path $directory 'yosoi.exe'
        Copy-Item -LiteralPath $Executable -Destination $installed
        $hash = (Get-FileHash $installed).Hash.ToLowerInvariant()
        $receipt = @{schema=1;method='standalone';version=$Version;sha256=$hash;path_added=$false}
        $receipt | ConvertTo-Json | Set-Content (Join-Path $directory '.yosoi-install.json') -Encoding ASCII
        New-Item -ItemType File -Path (Join-Path $directory '.yosoi-maintenance.lock') | Out-Null
        $staging = Join-Path $directory '.yosoi-update-test'
        New-Item -ItemType Directory -Path $staging | Out-Null
        $candidate = Join-Path $staging 'yosoi.exe'
        Copy-Item -LiteralPath $Executable -Destination $candidate
        $stream = [IO.File]::Open($candidate, [IO.FileMode]::Append)
        $stream.WriteByte(0)
        $stream.Dispose()
        $nextHash = (Get-FileHash $candidate).Hash.ToLowerInvariant()
        $next = @{schema=1;method='standalone';version=$Version;sha256=$nextHash;path_added=$false}
        if ($failure) { $next.sha256 = '0' * 64 }
        $next | ConvertTo-Json | Set-Content (Join-Path $staging '.yosoi-install.json') -Encoding ASCII
        $outcome = Join-Path $work ([Guid]::NewGuid().ToString('N') + '.json')
        '{"status":"pending"}' | Set-Content -LiteralPath $outcome -Encoding ASCII
        $parentScript = Join-Path $work 'parent.ps1'
        @'
param([string]$Executable)
$handle = [IO.File]::Open($Executable, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
[Console]::WriteLine('READY')
[Console]::Out.Flush()
[Console]::ReadLine() | Out-Null
$handle.Dispose()
'@ | Set-Content -LiteralPath $parentScript -Encoding ASCII
        $parent = Start-Redirected $parentScript @('-Executable', $installed)
        Wait-Ready $parent
        $helperScript = Join-Path $PSScriptRoot '../../crates/yosoi/src/bin/yosoi/self_command/windows-helper.ps1'
        $helper = Start-Redirected $helperScript @('-ParentId', $parent.Id.ToString(), '-Executable', $installed, '-ExpectedHash', $hash, '-Staging', $staging, '-Outcome', $outcome, '-Candidate', $candidate)
        Wait-Ready $helper
        if ((Get-FileHash $installed).Hash.ToLowerInvariant() -cne $hash) { throw 'Binary changed while parent was still running.' }
        $parent.StandardInput.WriteLine('exit')
        $parent.StandardInput.Flush()
        if (-not $parent.WaitForExit(10000)) { throw 'Fixture parent failed to exit.' }
        if (-not $helper.WaitForExit(70000)) { throw 'Maintenance helper failed to finish.' }
        $result = Get-Content -LiteralPath $outcome -Raw | ConvertFrom-Json
        if ($failure) {
            if ($result.status -cne 'failed' -or (Get-FileHash $installed).Hash.ToLowerInvariant() -cne $hash) { throw 'Invalid update did not preserve the installed executable.' }
        } else {
            if ($result.status -cne 'success' -or (Get-FileHash $installed).Hash.ToLowerInvariant() -cne $nextHash) { throw "Deferred replacement failed: $($result | ConvertTo-Json -Compress); $($helper.StandardError.ReadToEnd())" }
            if ((& $installed --version) -cne "yosoi $Version") { throw 'Updated binary did not execute.' }
        }
        if ((Test-Path $staging) -or (Test-Path (Join-Path $directory '.yosoi-maintenance.lock'))) { throw 'Maintenance left staging or its lock behind.' }
        $parent.Dispose(); $parent = $null
        $helper.Dispose(); $helper = $null
    }
    Write-Output 'Deferred Windows update and failed-update preservation passed.'
} finally {
    foreach ($process in @($parent, $helper)) {
        if ($process) { if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }; $process.Dispose() }
    }
    Remove-Item -LiteralPath $work -Recurse -Force
}
