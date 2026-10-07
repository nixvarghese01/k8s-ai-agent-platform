# Start the platform from the repo folder (PowerShell):  .\local-up  [-Docker] [-Profile mlops,observability]
# Starts Ollama + k3s, replaces the previous run's pods with fresh ones and waits until every
# pod is Ready. -Profile picks the optional services (default: last time's; `core` = none).
# Same as `.\infra\scripts\platform.ps1 up` (README section 6.6).
param([switch]$Docker, [Alias('Profile')][string]$Profiles)  # not $Profile: that's PowerShell's own $PROFILE
& "$PSScriptRoot\infra\scripts\platform.ps1" up -Docker:$Docker -Profiles $Profiles
