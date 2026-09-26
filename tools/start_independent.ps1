param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$workspaceRoot = Split-Path $repoRoot -Parent
$python = Join-Path $workspaceRoot '.runtime\python\cpython-3.12.13-windows-x86_64-none\pythonw.exe'
$entry = Join-Path $PSScriptRoot 'launch_console.py'
if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $entry)) {
    throw 'Independent launcher runtime or entry point is missing.'
}
# Local WMI creates the process outside the invoking tool's Job. Explicit
# breakaway avoids inheriting the provider's Job as well; no task is registered.
$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{
    CreateFlags = [uint32]0x09000200
    ShowWindow = [uint16]0
    WinstationDesktop = 'winsta0\default'
}
# Keep server.py in argv for the existing project-instance discovery helper.
$command = '"' + $python + '" -X utf8 "' + $entry + '" "' + (Join-Path $repoRoot 'server.py') + '"'
if ($NoBrowser) { $command += ' --no-browser' }
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $command
    CurrentDirectory = $repoRoot
    ProcessStartupInformation = $startup
}
if ($result.ReturnValue -ne 0) { throw ('Independent process creation failed: ' + $result.ReturnValue) }
Write-Output ('Independent console PID: ' + $result.ProcessId)
