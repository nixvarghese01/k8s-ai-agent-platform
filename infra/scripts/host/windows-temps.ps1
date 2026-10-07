# README section 12: CPU temperatures on Windows (issue #3), with LibreHardwareMonitor (open source).
#   .\infra\scripts\host\windows-temps.ps1          current temperatures
#   .\infra\scripts\host\windows-temps.ps1 -Load    idle vs. Ollama under load (~2 minutes)
# The first run installs LibreHardwareMonitor with winget if it's missing, switches on its
# built-in web server (127.0.0.1:8085 only; this version has no WMI provider) and starts it as
# admin (UAC prompt): reading CPU sensors needs its kernel driver. It stays in the tray; this
# script reads http://127.0.0.1:8085/data.json. Quit it from the tray icon to stop.
param([switch]$Load, [int]$IdleSeconds = 30, [int]$LoadSeconds = 90)
$ErrorActionPreference = 'Stop'
$distro = 'Ubuntu-26.04'
$url = 'http://127.0.0.1:8085/data.json'

function Find-Lhm {
    Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter LibreHardwareMonitor.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}

# LibreHardwareMonitor rewrites its config on exit, so change it only while it's not running
function Set-LhmSetting {
    [CmdletBinding(SupportsShouldProcess)]
    param([string]$Config, [hashtable]$Settings)
    if (-not $PSCmdlet.ShouldProcess($Config, 'update LibreHardwareMonitor settings')) { return }
    [xml]$xml = if (Test-Path $Config) { Get-Content $Config -Raw } else { '<?xml version="1.0" encoding="utf-8"?><configuration><appSettings /></configuration>' }
    $app = $xml.configuration.SelectSingleNode('appSettings')
    foreach ($k in $Settings.Keys) {
        $node = $app.SelectSingleNode("add[@key='$k']")
        if (-not $node) { $node = $xml.CreateElement('add'); $node.SetAttribute('key', $k); [void]$app.AppendChild($node) }
        $node.SetAttribute('value', $Settings[$k])
    }
    $xml.Save($Config)
}

# Every sensor in LibreHardwareMonitor's tree: Name, Type (Temperature, Load, ...), Value, Hardware
function Get-Sensor([string]$Type) {
    function Walk($node, $hardware) {
        $hw = if ($node.ImageURL -match 'cpu|mainboard|nvme|hdd|ram|nvidia|ati|intel') { $node.Text } else { $hardware }
        if ($node.Type -and $node.Value -match '^-?[\d.,]+') {
            [pscustomobject]@{ Name = $node.Text; Type = $node.Type; Value = [double]($Matches[0] -replace ',', '.'); Hardware = $hw }
        }
        foreach ($c in $node.Children) { Walk $c $hw }
    }
    try { $tree = Invoke-RestMethod $url -TimeoutSec 5 } catch { return }
    Walk $tree '' | Where-Object Type -eq $Type
}

function Get-Reading {
    $temps = Get-Sensor 'Temperature'
    $load = Get-Sensor 'Load' | Where-Object Name -eq 'CPU Total' | Select-Object -First 1
    $package = $temps | Where-Object Name -match '^CPU Package$|Tctl|Tdie' | Select-Object -First 1
    $cores = $temps | Where-Object Name -match '^(CPU )?Core #\d+$|^Core Max$'
    [pscustomobject]@{
        Package = if ($package) { [math]::Round($package.Value, 1) } else { $null }
        CoreMax = if ($cores) { [math]::Round(($cores | Measure-Object Value -Maximum).Maximum, 1) } else { $null }
        CpuLoad = if ($load) { [math]::Round($load.Value, 0) } else { $null }
    }
}

# Install, configure and start LibreHardwareMonitor if needed
$exe = Find-Lhm
if (-not $exe) {
    winget install --id LibreHardwareMonitor.LibreHardwareMonitor --exact --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $exe = Find-Lhm
    if (-not $exe) { throw 'LibreHardwareMonitor not found after winget install' }
}
if (-not (Get-Sensor 'Temperature')) {
    if (Get-Process LibreHardwareMonitor -ErrorAction SilentlyContinue) {
        # Running without the web server: stop it (as admin, it may be elevated) to change settings
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', 'Stop-Process -Name LibreHardwareMonitor -Force'
        Start-Sleep 2
    }
    Set-LhmSetting (Join-Path (Split-Path $exe) 'LibreHardwareMonitor.config') @{
        runWebServerMenuItem = 'true'; listenerIp = '127.0.0.1'; listenerPort = '8085'
        startMinMenuItem = 'true'; minTrayMenuItem = 'true'; minCloseMenuItem = 'true'
    }
    Start-Process $exe -Verb RunAs -WindowStyle Minimized
    for ($i = 0; $i -lt 40 -and -not (Get-Sensor 'Temperature'); $i++) { Start-Sleep 1 }
}
if (-not (Get-Sensor 'Temperature')) { throw "No temperatures at $url : is LibreHardwareMonitor running (as admin)?" }

if (-not $Load) {
    Get-Sensor 'Temperature' | Sort-Object Hardware, Name | Format-Table Hardware, @{n = 'Sensor'; e = { $_.Name } }, @{n = 'C'; e = { $_.Value } } -AutoSize
    return
}

function Measure-Phase([string]$Name, [int]$Seconds) {
    $samples = for ($t = 0; $t -lt $Seconds; $t += 5) { Get-Reading; Start-Sleep 5 }
    [pscustomobject]@{
        Phase          = $Name
        'Package avg'  = [math]::Round(($samples.Package | Measure-Object -Average).Average, 1)
        'Package max'  = ($samples.Package | Measure-Object -Maximum).Maximum
        'Core max'     = ($samples.CoreMax | Measure-Object -Maximum).Maximum
        'CPU load avg' = "$([math]::Round(($samples.CpuLoad | Measure-Object -Average).Average, 0))%"
    }
}

"Idle for $IdleSeconds s (close heavy apps)..."
$idle = Measure-Phase 'idle' $IdleSeconds

"Ollama generating for $LoadSeconds s..."
$body = @{ model = 'llama3.2:3b'; stream = $false; options = @{ num_predict = 4000 }
    prompt = 'Write a long, detailed essay about the history of computing, at least 2000 words.' } | ConvertTo-Json
# Ollama answers on Windows' localhost too (WSL forwards it); no quoting through wsl/curl
$job = Start-Job { Invoke-RestMethod http://localhost:11434/api/generate -Method Post -Body $using:body -ContentType 'application/json' -TimeoutSec 600 | Out-Null }
Start-Sleep 5  # model load
$busy = Measure-Phase 'Ollama load' $LoadSeconds
Stop-Job $job -ErrorAction SilentlyContinue; Remove-Job $job -Force -ErrorAction SilentlyContinue
wsl -d $distro -u root -- systemctl restart ollama 2>$null  # stop the generation that may still run

"Cooling for 20 s..."
Start-Sleep 20
$after = Measure-Phase 'after (cooling)' 15

$idle, $busy, $after | Format-Table -AutoSize
