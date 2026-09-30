# README §6.7: point the platform's *.local hostnames at ::1 (Traefik on the WSL host's ports 80/443).
# Run in PowerShell as admin, from the repo folder. Safe to re-run: it replaces its own block.
# Backs up the hosts file to hosts.bak-<timestamp> first.
# Undo: run again with -Remove
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
$begin = '# BEGIN local-ai-platform'
$end = '# END local-ai-platform'
# One name per line: Windows treats extra names on a line as aliases (CNAMEs) of the first,
# and those don't resolve for ::1 (only the first name on each line would work).
$names = 'chat', 'llm', 'agent', 'mlflow', 'dagster', 'n8n', 'langfuse', 'grafana', 'minio', 'qdrant', 'argocd'
$block = @($begin) + ($names | ForEach-Object { "::1 $_.local" }) + @($end)

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this in an admin PowerShell (the hosts file is read-only for normal users).' }

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

if ($Remove) { 'Removed the local-ai-platform block.' } else { Get-Content $hosts | Select-String '\.local' }
