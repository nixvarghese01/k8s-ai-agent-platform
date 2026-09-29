# README §12: cap the CPU at 80% of its base clock on the active Windows power plan.
# Anything below 100% also turns off Turbo Boost. Run in PowerShell (no admin needed).
# Undo: run again with -Max 100
param([int]$Max = 80)

powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX $Max
powercfg /setdcvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX $Max
powercfg /setactive SCHEME_CURRENT
powercfg /query SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX | Select-String 'Current AC|Current DC'
