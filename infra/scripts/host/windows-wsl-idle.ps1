# Stop WSL from shutting Ubuntu down ~30 s after the last terminal closes, which kills k3s.
# Sets [general] instanceIdleTimeout=-1 and [wsl2] vmIdleTimeout=-1 in %UserProfile%\.wslconfig.
# Ubuntu then runs until `platform.ps1 down` (or `wsl --shutdown`) stops it.
# Run in PowerShell (no admin needed). Takes effect after `wsl --shutdown`.
# Undo: run with -Remove, then `wsl --shutdown`.
param([switch]$Remove)

$path = Join-Path $env:USERPROFILE '.wslconfig'
$lines = [Collections.Generic.List[string]](Get-Content $path)
$lines.RemoveAll([Predicate[string]]{ param($l) $l -match '^\s*(instanceIdleTimeout|vmIdleTimeout)\s*=' }) | Out-Null

if (-not $Remove) {
    # vmIdleTimeout belongs under [wsl2]
    $i = $lines.FindIndex([Predicate[string]]{ param($l) $l -match '^\s*\[wsl2\]' })
    $lines.Insert($i + 1, 'vmIdleTimeout=-1')
    # instanceIdleTimeout belongs under [general]
    $g = $lines.FindIndex([Predicate[string]]{ param($l) $l -match '^\s*\[general\]' })
    if ($g -lt 0) { $lines.Add(''); $lines.Add('[general]'); $lines.Add('instanceIdleTimeout=-1') }
    else { $lines.Insert($g + 1, 'instanceIdleTimeout=-1') }
}
# Drop an empty [general] section left behind by -Remove
$text = ($lines -join "`r`n") -replace "(\r\n)*\[general\]\s*$", ''
Set-Content $path $text.TrimEnd() -Encoding ascii
Get-Content $path
