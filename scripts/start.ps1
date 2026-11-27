[CmdletBinding()]
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-StudioService($url, $marker) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content -match $marker
    } catch {
        return $false
    }
}

function Start-StudioService($name, $url, $marker, $executable, $arguments, $folder) {
    if (Test-StudioService $url $marker) { return }
    $stderr = Join-Path $logDir "$name.stderr.log"
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $folder -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir "$name.stdout.log") -RedirectStandardError $stderr
    $deadline = (Get-Date).AddMinutes(2)
    do {
        if (Test-StudioService $url $marker) { return }
        if ($process.HasExited) { throw "$name exited with code $($process.ExitCode). See $stderr" }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)
    throw "$name has not responded yet. See $stderr"
}

$pythonExe = (Get-Command python -CommandType Application | Select-Object -First 1).Source
$nodeExe = (Get-Command node -CommandType Application | Select-Object -First 1).Source
$nextCli = Join-Path $projectRoot 'ui/node_modules/next/dist/bin/next'
if (-not (Test-Path -LiteralPath $nextCli)) { throw "Install the UI dependencies with npm ci in the ui directory." }

# llama.cpp uses the CUDA libraries shipped with the active Python's PyTorch.
$torchLib = & $pythonExe -c "import importlib.util,pathlib; print(pathlib.Path(importlib.util.find_spec('torch').origin).parent / 'lib')"
if ($LASTEXITCODE -ne 0) { throw 'Install CUDA-enabled PyTorch for the active Python.' }
$env:PATH = "$torchLib;$env:PATH"
$env:PYTHONIOENCODING = 'utf-8'
Start-StudioService 'audiobook-api' 'http://127.0.0.1:8000/openapi.json' 'Shadow Slave Audiobook Pipeline' $pythonExe @('-m','uvicorn','api:app','--host','127.0.0.1','--port','8000') (Join-Path $projectRoot 'src')
Start-StudioService 'audiobook-ui' 'http://127.0.0.1:3000' 'One Who Reads Aloud' $nodeExe @('node_modules/next/dist/bin/next','dev','--hostname','127.0.0.1','--port','3000') (Join-Path $projectRoot 'ui')
Write-Host "Audiobook studio is ready at http://127.0.0.1:3000"
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:3000' }
