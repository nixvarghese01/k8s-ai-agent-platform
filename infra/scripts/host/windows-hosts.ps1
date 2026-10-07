# README §6.7: make the platform's *.ai.local names reach Traefik from Windows, on any network.
#   1. hosts file: every name -> 127.0.0.1 (between # BEGIN/END local-ai-platform markers)
#   2. port proxies 127.0.0.1:80/443 -> [::1]:80/443, because WSL relays Traefik's ports to
#      Windows' IPv6 loopback only, and Chrome won't use ::1-only names when the network has
#      no IPv6 (2026-10-08: every *.ai.local failed with NXDOMAIN on such a network)
# Run in PowerShell as admin, from the repo folder. Safe to re-run: it replaces its own entries.
# Backs up the hosts file to hosts.bak-<timestamp> first. Undo: run again with -Remove
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
$begin = '# BEGIN local-ai-platform'
$end = '# END local-ai-platform'
# One name per line: Windows treats extra names on a line as aliases (CNAMEs) of the first,
# and those don't always resolve (only the first name on each line is reliable).
# Every UI lives under ai.local, so one sign-on cookie (domain ai.local) covers them all (§6.14)
$names = 'auth', 'chat', 'llm', 'agent', 'mlflow', 'dagster', 'n8n', 'phoenix', 'grafana', 'triage', 's3', 'qdrant', 'argocd', 'headlamp'
$block = @($begin) + ($names | ForEach-Object { "127.0.0.1 $_.ai.local" }) + @($end)
$ports = 80, 443

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this in an admin PowerShell (the hosts file and port proxies need it).' }

Copy-Item $hosts "$hosts.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"

# Drop any previous copy of the block, keep every other line as it was
$lines = New-Object System.Collections.Generic.List[string]
$inBlock = $false
foreach ($line in Get-Content $hosts) {
    if ($line -eq $begin) { $inBlock = $true; continue }
    if ($line -eq $end) { $inBlock = $false; continue }
    if (-not $inBlock) { $lines.Add($line) }
}
while ($lines.Count -and $lines[$lines.Count - 1] -eq '') { $lines.RemoveAt($lines.Count - 1) }
if (-not $Remove) { $lines.Add(''); $lines.AddRange([string[]]$block) }

Set-Content -Path $hosts -Value $lines -Encoding ASCII
ipconfig /flushdns | Out-Null

# Port proxies (kept by Windows across reboots; served by the IP Helper service)
foreach ($p in $ports) {
    netsh interface portproxy delete v4tov6 listenaddress=127.0.0.1 listenport=$p 2>$null | Out-Null
    if (-not $Remove) {
        netsh interface portproxy add v4tov6 listenaddress=127.0.0.1 listenport=$p connectaddress=::1 connectport=$p | Out-Null
    }
}
if (-not $Remove) { Start-Service iphlpsvc -ErrorAction SilentlyContinue }

if ($Remove) {
    'Removed the local-ai-platform hosts block and port proxies.'
} else {
    Get-Content $hosts | Select-String '\.ai\.local'
    netsh interface portproxy show v4tov6
}
