# Assess this Windows machine against the platform's requirements (README section 5) and write
# SYSTEM_ASSESSMENT.md at the repo root (git-ignored: it describes your machine only).
# Read-only: changes nothing. Run in PowerShell from anywhere:
#   .\infra\scripts\host\00-assess.ps1 [-Distro Ubuntu-26.04]
# Re-run after each setup step to see what's left.
param([string]$Distro)

$ErrorActionPreference = 'Continue'
$env:WSL_UTF8 = '1' # make wsl.exe print UTF-8 instead of UTF-16
$repo = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$out = Join-Path $repo 'SYSTEM_ASSESSMENT.md'
$checks = New-Object System.Collections.Generic.List[object]
function Check($name, $need, $found, $result, $fix = '') {
    $checks.Add([pscustomobject]@{ Name = $name; Need = $need; Found = ("$found" -replace '\|', '/'); Result = $result; Fix = $fix })
}
function ConvertTo-MdRows([object[]]$rows) { ($rows | ForEach-Object { '| ' + (($_ | ForEach-Object { "$_" -replace '\|', '/' }) -join ' | ') + ' |' }) -join "`n" }

# ---------- Windows hardware ----------
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$os = Get-CimInstance Win32_OperatingSystem
$bios = Get-CimInstance Win32_BIOS
$build = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
# RAM in use minus the WSL VM itself, so the figure means "what Windows needs"
$wslGB = [math]::Round((Get-Process -Name vmmemWSL -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum / 1GB, 1)
$usedGB = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB - $wslGB, 1)
$dimms = Get-CimInstance Win32_PhysicalMemory
$sysDrive = $env:SystemDrive.Substring(0, 1)
$vols = Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' } | Sort-Object SizeRemaining -Descending
$disks = Get-PhysicalDisk
$gpus = Get-CimInstance Win32_VideoController
$nvidia = $null
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $nvidia = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null }

$logical = $cpu.NumberOfLogicalProcessors
Check 'CPU threads' '8+' "$logical ($($cpu.NumberOfCores) cores)" $(if ($logical -ge 8) { 'PASS' } elseif ($logical -ge 6) { 'WARN' } else { 'FAIL' }) 'Fewer threads: lower processors= in .wslconfig and expect slower inference'
Check 'RAM' '32 GB' "$totalGB GB usable; Windows uses $usedGB GB now (WSL VM: $wslGB GB)" $(if ($totalGB -ge 31) { 'PASS' } elseif ($totalGB -ge 16) { 'WARN' } else { 'FAIL' }) 'Under 32 GB: trim the stack (README section 15) and lower memory='
$virt = $cs.HypervisorPresent -or $cpu.VirtualizationFirmwareEnabled
Check 'Virtualization' 'enabled' $(if ($cs.HypervisorPresent) { 'hypervisor running' } elseif ($cpu.VirtualizationFirmwareEnabled) { 'enabled in firmware' } else { 'off' }) $(if ($virt) { 'PASS' } else { 'FAIL' }) 'Enable VT-x/AMD-V in BIOS'
$best = $vols | Select-Object -First 1
$bestFree = [math]::Round($best.SizeRemaining / 1GB)
Check 'Free SSD space' '~100 GB on one drive' "$($best.DriveLetter): $bestFree GB free" $(if ($bestFree -ge 100) { 'PASS' } elseif ($bestFree -ge 50) { 'WARN' } else { 'FAIL' }) "Put the WSL distro on the drive with the most space (currently $($best.DriveLetter):)"

# ---------- WSL ----------
$wslVer = (wsl --version 2>$null | Select-Object -First 1) -replace '^[^:]*:\s*', ''
$list = @(wsl -l -v 2>$null | Select-Object -Skip 1 | ForEach-Object {
        $p = ($_ -replace '^\s*\*?\s*', '') -split '\s+'
        if ($p[0]) { [pscustomobject]@{ Name = $p[0]; State = $p[1]; Version = $p[2]; Default = $_ -match '^\s*\*' } } })
Check 'WSL' 'WSL 2 installed' $(if ($wslVer) { $wslVer } else { 'not found' }) $(if ($wslVer) { 'PASS' } else { 'FAIL' }) 'wsl --install --no-distribution'

if (-not $Distro) { $Distro = ($list | Where-Object Name -like 'Ubuntu*' | Select-Object -First 1).Name }
$d = $list | Where-Object Name -eq $Distro
$lxss = Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq $Distro
$location = $lxss.BasePath -replace '^\\\\\?\\', ''
Check 'Ubuntu distro' 'Ubuntu on WSL 2' $(if ($d) { "$($d.Name), WSL $($d.Version), at $location" } else { 'none' }) $(if ($d -and $d.Version -eq '2') { 'PASS' } else { 'FAIL' }) "wsl --install Ubuntu-26.04 --location $($best.DriveLetter):\wsl\Ubuntu-26.04"
if ($d -and $location) {
    $locDrive = $location.Substring(0, 1)
    $locFree = [math]::Round(($vols | Where-Object DriveLetter -eq $locDrive).SizeRemaining / 1GB)
    Check 'Distro drive space' '~100 GB free' "$($locDrive): $locFree GB free" $(if ($locFree -ge 100) { 'PASS' } else { 'WARN' }) 'Models, images and volumes all live in the distro disk'
}

# .wslconfig
$cfgPath = Join-Path $env:USERPROFILE '.wslconfig'
$cfg = @{}
if (Test-Path $cfgPath) { Get-Content $cfgPath | Where-Object { $_ -match '^\s*([A-Za-z]+)\s*=\s*(.+?)\s*$' } | ForEach-Object { $cfg[$Matches[1]] = $Matches[2] } }
$suggestMem = [math]::Max(8, [math]::Min(24, [math]::Floor($totalGB - [math]::Max($usedGB, 8) - 2)))
$suggestCpu = [math]::Max(2, $logical - 4)
$memSet = if ($cfg.memory) { [int]($cfg.memory -replace '[^0-9]', '') } else { 0 }
Check '.wslconfig memory' "~$suggestMem GB (RAM − Windows use − 2 GB, max 24)" $(if ($memSet) { $cfg.memory } else { 'not set (WSL default: half of RAM)' }) $(if (-not $memSet) { 'WARN' } elseif ($memSet + $usedGB -gt $totalGB) { 'WARN' } else { 'PASS' }) "memory=$($suggestMem)GB"
Check '.wslconfig processors' "$suggestCpu (leave 4 threads for Windows)" $(if ($cfg.processors) { $cfg.processors } else { 'not set (all threads)' }) $(if ($cfg.processors) { 'PASS' } else { 'WARN' }) "processors=$suggestCpu"
$swapOnSys = -not $cfg.swapFile -or $cfg.swapFile -match "^$sysDrive`:"
Check 'WSL swap file' 'on the distro drive' $(if ($cfg.swapFile) { $cfg.swapFile } else { "default (%TEMP% on $($sysDrive):)" }) $(if ($swapOnSys -and $location -and -not $location.StartsWith($sysDrive)) { 'WARN' } else { 'PASS' }) 'swapFile=<drive>:\\wsl\\swap.vhdx'
$idle = $cfg.instanceIdleTimeout -eq '-1' -and $cfg.vmIdleTimeout -eq '-1'
Check 'WSL idle shutdown' 'off' $(if ($idle) { 'off' } else { 'on (WSL stops ~30 s after the last terminal closes)' }) $(if ($idle) { 'PASS' } else { 'WARN' }) 'infra/scripts/host/windows-wsl-idle.ps1'

# ---------- Inside Ubuntu ----------
$w = @{}
if ($d) {
    $drive = $PSScriptRoot.Substring(0, 1).ToLower()
    $sh = "/mnt/$drive" + ($PSScriptRoot.Substring(2) -replace '\\', '/') + '/assess-wsl.sh'
    wsl -d $Distro -- bash $sh 2>$null | Where-Object { $_ -match '^([a-z0-9_]+)=(.*)$' } | ForEach-Object { $w[$Matches[1]] = $Matches[2].Trim() }
    Check 'systemd' 'PID 1' $w.init $(if ($w.init -eq 'systemd') { 'PASS' } else { 'FAIL' }) '/etc/wsl.conf: [boot] systemd=true, then wsl --shutdown'
    $steps = [ordered]@{
        tool_zstd = '01-install-k3s-helm-ollama.sh'; tool_k3s = '01-install-k3s-helm-ollama.sh'; tool_helm = '01-install-k3s-helm-ollama.sh'
        tool_ollama = '01-install-k3s-helm-ollama.sh'; tool_docker = '04-install-docker.sh'; tool_make = '05-on-demand-services.sh'
    }
    foreach ($k in $steps.Keys) {
        Check ($k -replace 'tool_', '') 'installed' $w[$k] $(if ($w[$k] -and $w[$k] -ne 'missing') { 'PASS' } else { 'TODO' }) "infra/scripts/host/$($steps[$k])"
    }
    $hasModels = $w.models -match 'qwen2.5:3b' -and $w.models -match 'nomic-embed-text'
    Check 'Models' 'qwen2.5:3b, nomic-embed-text' $w.models $(if ($hasModels) { 'PASS' } elseif ($w.models -match 'not running') { 'INFO' } else { 'TODO' }) 'infra/scripts/host/02-pull-models.sh (start the platform first)'
}
$gpuText = if ($nvidia) { $nvidia -join '; ' } else { ($gpus.Name -join '; ') }
Check 'GPU' 'not required' $gpuText 'INFO' 'Platform is CPU-only; a GPU with 6+ GB VRAM could speed up Ollama'

# ---------- Report ----------
$icon = @{ PASS = '✅'; WARN = '⚠️'; FAIL = '❌'; TODO = '⬜'; INFO = 'ℹ️' }
$sum = $checks | Group-Object Result | ForEach-Object { "$($_.Count) $($_.Name)" }
$now = Get-Date -Format 'yyyy-MM-dd HH:mm'

$report = @"
# System Assessment

Generated $now by ``infra/scripts/host/00-assess.ps1`` on **$($cs.Manufacturer) $($cs.Model)**. Read-only snapshot of this machine; git-ignored. Re-run after each setup step.

**Summary:** $($sum -join ' - ')

## Readiness

| Check | Needed | Found | Result | Next step |
|---|---|---|---|---|
$(($checks | ForEach-Object { "| $($_.Name) | $($_.Need) | $($_.Found) | $($icon[$_.Result]) $($_.Result) | $(if ($_.Result -ne 'PASS') { $_.Fix }) |" }) -join "`n")

## Machine

| | |
|---|---|
$(ConvertTo-MdRows @(
    ,@('**Model**', "$($cs.Manufacturer) $($cs.Model)")
    ,@('**BIOS**', "$($bios.SMBIOSBIOSVersion) ($($bios.ReleaseDate.ToString('yyyy-MM-dd')))")
    ,@('**OS**', "$($os.Caption) $($build.DisplayVersion), build $($os.BuildNumber).$($build.UBR)")
    ,@('**CPU**', "$($cpu.Name.Trim()), $($cpu.NumberOfCores) cores / $logical threads, load $($cpu.LoadPercentage)%")
    ,@('**RAM**', "$totalGB GB usable, Windows uses $usedGB GB (+ WSL VM $wslGB GB); modules: $(($dimms | ForEach-Object { '{0} GB {1} MT/s' -f ($_.Capacity / 1GB), $_.Speed }) -join ', ')")
    ,@('**GPU**', $gpuText)
))

## Storage

| Drive | Label | Size | Free |
|---|---|---|---|
$(($vols | Sort-Object DriveLetter | ForEach-Object { "| $($_.DriveLetter): | $($_.FileSystemLabel) | $([math]::Round($_.Size / 1GB)) GB | $([math]::Round($_.SizeRemaining / 1GB)) GB |" }) -join "`n")

Physical disks: $(($disks | ForEach-Object { "$($_.FriendlyName) ($($_.BusType) $($_.MediaType), $([math]::Round($_.Size / 1GB)) GB, $($_.HealthStatus))" }) -join '; ')

## WSL

| | |
|---|---|
$(ConvertTo-MdRows @(
    ,@('**WSL**', $wslVer)
    ,@('**Distros**', (($list | ForEach-Object { "$($_.Name) (WSL $($_.Version), $($_.State))" }) -join ', '))
    ,@('**Assessed distro**', "$Distro at $location")
    ,@('**.wslconfig**', $(if ($cfg.Count) { ($cfg.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ', ' } else { 'none' }))
))
$(if ($w.Count) { @"

## Inside $Distro

| | |
|---|---|
$(ConvertTo-MdRows @(
    ,@('**OS / kernel**', "$($w.os) / $($w.kernel)")
    ,@('**Seen by Linux**', "$($w.cpus) CPUs, $($w.mem_gib) GiB RAM, $($w.swap_gib) GiB swap, disk $($w.disk_used) of $($w.disk_size)")
    ,@('**User**', "$($w.user) (sudo group: $($w.sudo_group)); kubeconfig $($w.kubeconfig)")
    ,@('**Tools**', "git: $($w.tool_git); curl: $($w.tool_curl); zstd: $($w.tool_zstd); make: $($w.tool_make)")
    ,@('**Platform**', "k3s: $($w.tool_k3s); helm: $($w.tool_helm); ollama: $($w.tool_ollama); docker: $($w.tool_docker)")
    ,@('**Services** (active / enabled)', "k3s: $($w.svc_k3s); ollama: $($w.svc_ollama); docker: $($w.svc_docker)")
    ,@('**Cluster**', "$($w.node); $($w.pods)")
    ,@('**Models**', $w.models)
))
"@ })
"@

[IO.File]::WriteAllText($out, $report, (New-Object Text.UTF8Encoding $false))
$checks | Format-Table Name, Result, Found -AutoSize
"Report written to $out"
