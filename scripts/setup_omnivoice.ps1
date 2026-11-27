[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $projectDir 'models/omnivoice-runtime'
$venv = Join-Path $runtime '.venv'
$python = (Get-Command python -CommandType Application | Select-Object -First 1).Source
& $python -c "import torch, torchaudio; assert torch.cuda.is_available(), 'Install a CUDA build of PyTorch and torchaudio first'"
if ($LASTEXITCODE) { throw 'CUDA runtime check failed.' }
& $python -m venv --system-site-packages $venv
if ($LASTEXITCODE) { throw 'Could not create the OmniVoice environment.' }
$workerPython = Join-Path $venv 'Scripts/python.exe'
& $workerPython -m pip install 'omnivoice==0.2.1' 'transformers==5.3.0'
if ($LASTEXITCODE) { throw 'Could not install the isolated speech runtime.' }
& $workerPython -c "from huggingface_hub import snapshot_download; import sys; snapshot_download('k2-fsa/OmniVoice',revision='c5fdb5ccb189668d56333f77ba2629f4cd7535f4',local_dir=sys.argv[1],allow_patterns=['*.json','*.safetensors','*.jinja','*LICENSE','README.md'])" (Join-Path $runtime 'checkpoints')
if ($LASTEXITCODE) { throw 'OmniVoice checkpoint download failed.' }
& $python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-base',revision='ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66',allow_patterns=['*.json','model.bin','vocabulary.*'])"
if ($LASTEXITCODE) { throw 'Read-back checkpoint download failed.' }
Write-Host 'OmniVoice is ready. Open Forge to choose a speech renderer.'
