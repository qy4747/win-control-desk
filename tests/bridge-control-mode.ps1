# Optional external integration check; not part of cddeck CI.
# Pass a trusted Local Codex Bridge control script explicitly; no personal default.
param([Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ControlPath)
if (-not (Test-Path -LiteralPath $ControlPath -PathType Leaf)) { throw 'ControlPath must name an existing trusted control script' }
$source = [IO.File]::ReadAllText($ControlPath)
$offset = $source.IndexOf('$before = Get-BridgeStatus')
if ($offset -lt 0) { throw 'Control dispatch block missing' }
$dispatchText = $source.Substring($offset)
if ($dispatchText -notmatch 'exit 0\s*$') { throw 'Successful controls must explicitly return zero instead of a curl status' }
# Keep exit local to the fake dispatch so all cases run in this test script.
$dispatch = [scriptblock]::Create(($dispatchText -replace 'exit 0', '$global:LASTEXITCODE = 0; return' -replace 'exit 1', 'throw "Control failed"'))
function Get-BridgeStatus { $global:LASTEXITCODE=28; [pscustomobject]@{ IsRunning = $script:local -and $script:git; Runtime = ''; Git = ''; Tray = '' } }
function Get-BridgeProcesses { if ($script:local) { [pscustomobject]@{ProcessId=1} } }
function Get-GitProcesses { if ($script:git) { [pscustomobject]@{ProcessId=2} } }
function Start-Bridge { $script:starts++; $script:local=$true; $script:git=$true }
function Stop-Bridge { $script:stops++; $script:local=$false; $script:git=$false }
function Start-Sleep { param($Seconds) }
function Read-Host { throw 'Non-interactive mode must not prompt' }
$NoPause = $true
$script:local=$true; $script:git=$false; $script:starts=0; $script:stops=0
$Mode='Stop'; & $dispatch
if ($LASTEXITCODE -ne 0) { throw 'Successful stop leaked a probe failure' }
if ($script:starts -ne 0 -or $script:stops -ne 1) { throw 'Stop must not restart a partial tunnel set' }
$Mode='Start'; & $dispatch
if ($script:starts -ne 1 -or -not $script:git) { throw 'Start must start both tunnels' }
& $dispatch
if ($script:starts -ne 1 -or $script:stops -ne 1) { throw 'Start must leave a running pair alone' }
$Mode='Toggle'; & $dispatch
if ($script:stops -ne 2) { throw 'Shortcut toggle behavior changed' }
