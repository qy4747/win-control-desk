# Manual regression check: all service/process operations are replaced with fakes.
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '..\tools\todesk_control.ps1'))
$body = $source.Substring($source.IndexOf("`$ErrorActionPreference ="))
$body = $body.Replace('& $python (Join-Path $PSScriptRoot ''stop_app_processes.py'')', 'Invoke-FakeClientStop')
$body = $body.Replace('exit $client.ExitCode', 'return').Replace('exit 1', 'throw $_')
$control = [scriptblock]::Create($body)
$script:order = [Collections.Generic.List[string]]::new()
$script:servicePath = '"C:\Program Files\ToDesk\ToDesk.exe" --runservice'
function Get-CimInstance { [pscustomobject]@{ PathName = $script:servicePath } }
function Stop-Service { $script:order.Add('service-stop') }
function Start-Service { $script:order.Add('service-start') }
function Get-Service {
    $fake = [pscustomobject]@{ Status = 'Stopped' }
    $fake | Add-Member ScriptMethod WaitForStatus { param($status, $timeout) $script:order.Add("wait-$status") }
    $fake
}
function Invoke-FakeClientStop { $script:order.Add('client-stop'); $global:LASTEXITCODE=0 }
function Start-Process { $script:order.Add('client-show'); [pscustomobject]@{ExitCode=0} }
function Write-Error { param($Message, $ErrorAction) }
$savedContext = $env:CDDECK_APP_CONTEXT
try {
    $env:CDDECK_APP_CONTEXT = '{"appId":"159f3cbd","processes":[{"pid":123,"created":"456"}]}'
    $Mode='Stop'; & $control
    if (($script:order -join ',') -ne 'service-stop,wait-Stopped,client-stop') { throw 'Stop order changed' }
    $script:order.Clear()
    $Mode='Start'; & $control
    if (($script:order -join ',') -ne 'service-start,wait-Running,client-show') { throw 'Start order changed' }
    $script:order.Clear()
    $script:servicePath='"C:\Other\ToDesk.exe" --runservice'
    $rejected=$false
    try { $Mode='Stop'; & $control } catch { $rejected=$true }
    if (-not $rejected -or $script:order.Count) { throw 'Unexpected service path must be rejected before any operation' }
} finally { $env:CDDECK_APP_CONTEXT = $savedContext }
