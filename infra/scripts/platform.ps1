# Start/stop the whole platform from Windows (PowerShell, Git Bash via `powershell -File`, VS Code).
#
#   .\infra\scripts\platform.ps1 up [-Docker]     start Ollama + k3s (+ Docker), wait for pods
#   .\infra\scripts\platform.ps1 down [-KeepWsl]  stop everything, then shut Ubuntu down to free its RAM
#   .\infra\scripts\platform.ps1 status
#   .\infra\scripts\platform.ps1 restart [-Docker] [-KeepWsl]  down, then up: a full cold restart
#   .\infra\scripts\platform.ps1 headlamp-token  copy the Headlamp login token to the clipboard
#
# `down` without -KeepWsl closes any open Ubuntu terminals too.
param(
    [Parameter(Mandatory, Position = 0)][ValidateSet('up', 'down', 'status', 'restart', 'headlamp-token')][string]$Action,
    [switch]$Docker,
    [switch]$KeepWsl
)
$ErrorActionPreference = 'Stop'
$distro = 'Ubuntu-26.04'

# E:\Github\local-ai-platform\infra\scripts -> /mnt/e/Github/local-ai-platform/infra/scripts
$drive = $PSScriptRoot.Substring(0, 1).ToLower()
$here = "/mnt/$drive" + ($PSScriptRoot.Substring(2) -replace '\\', '/')

function Invoke-Platform([string[]]$ArgList) {
    wsl -d $distro -u root -- bash "$here/platform.sh" @ArgList
    if ($LASTEXITCODE -ne 0) { throw "platform.sh $($ArgList -join ' ') failed ($LASTEXITCODE)" }
}

$extra = @(); if ($Docker) { $extra += '--docker' }

switch ($Action) {
    'up' { Invoke-Platform (@('up') + $extra) }
    'restart' {
        # Same as `down` then `up`: Ubuntu is shut down too (unless -KeepWsl), so nothing
        # carries over from the previous run; `up` then starts fresh pods
        Invoke-Platform @('down')
        if (-not $KeepWsl) {
            wsl --terminate $distro | Out-Null
            "Ubuntu stopped; starting again."
        }
        Invoke-Platform (@('up') + $extra)
    }
    'status' { wsl -d $distro -- bash "$here/status.sh" }
    'headlamp-token' {
        # As root, so no Ubuntu password is needed; the token is cluster-admin (ui/headlamp.yaml)
        $token = wsl -d $distro -u root -- sh -c "kubectl -n ui get secret headlamp-token -o jsonpath='{.data.token}' | base64 -d"
        if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'No token: is the platform up and ui/headlamp.yaml deployed?' }
        Set-Clipboard -Value $token
        'Headlamp token copied to the clipboard; paste it at http://headlamp.local'
    }
    'down' {
        Invoke-Platform @('down')
        if (-not $KeepWsl) {
            wsl --terminate $distro | Out-Null
            "Ubuntu stopped; its memory is released."
        }
    }
}
