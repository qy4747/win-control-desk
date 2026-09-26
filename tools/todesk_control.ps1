param([ValidateSet('Start', 'Stop')][string]$Mode = 'Stop')

$ErrorActionPreference = 'Stop'
$exe = 'C:\Program Files\ToDesk\ToDesk.exe'
$serviceName = 'ToDesk_Service'
try {
    $service = Get-CimInstance Win32_Service -Filter "Name='$serviceName'"
    $expected = '"' + $exe + '" --runservice'
    if (-not $service -or $service.PathName.Trim() -ine $expected) {
        throw 'ToDesk service executable or arguments changed; no action was taken.'
    }
    if ($Mode -eq 'Start') {
        Start-Service -Name $serviceName
        (Get-Service -Name $serviceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(20))
        # The service may create the GUI itself. --show asks that instance to open.
        $client = Start-Process -FilePath $exe -ArgumentList '--show' -WindowStyle Normal -PassThru -Wait
        exit $client.ExitCode
    }
    $context = $env:CDDECK_APP_CONTEXT | ConvertFrom-Json
    if ($context.appId -ne '159f3cbd' -or -not $context.processes) {
        throw 'Missing verified ToDesk card context; no action was taken.'
    }
    # Stop the protector before terminating the GUI, so it cannot recreate it.
    Stop-Service -Name $serviceName
    (Get-Service -Name $serviceName).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20))
    $python = Join-Path $PSScriptRoot '..\..\.runtime\python\cpython-3.12.13-windows-x86_64-none\python.exe'
    & $python (Join-Path $PSScriptRoot 'stop_app_processes.py')
    if ($LASTEXITCODE -ne 0) { throw 'The ToDesk service stopped, but verified client processes could not all be closed.' }
    if ((Get-Service -Name $serviceName).Status -ne 'Stopped') {
        throw 'The ToDesk service restarted; shutdown is incomplete.'
    }
    Write-Output 'ToDesk service and verified client processes stopped.'
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
