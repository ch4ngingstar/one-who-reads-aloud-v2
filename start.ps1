param([switch]$NoBrowser)
& (Join-Path $PSScriptRoot 'scripts/start.ps1') -NoBrowser:$NoBrowser
