# Shadow Slave Audiobook Pipeline — Dev Launch Script
# Run from project root:  .\scripts\start.ps1

$ProjectRoot = Split-Path -Parent $PSScriptRoot

# Add PyTorch CUDA DLLs to PATH so llama-cpp-python can find cublas/cudart
$TorchLib = python -c "import torch, os; print(os.path.join(os.path.dirname(torch.__file__), 'lib'))"
$env:PATH = "$TorchLib;" + $env:PATH

Write-Host "[start] PyTorch lib: $TorchLib" -ForegroundColor Cyan
Write-Host "[start] Starting FastAPI backend on http://localhost:8000 ..." -ForegroundColor Cyan

# Backend — run from src/ so intra-package imports resolve
Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "api:app", "--reload", "--port", "8000" `
    -WorkingDirectory "$ProjectRoot\src" `
    -WindowStyle Normal

Start-Sleep -Seconds 2

Write-Host "[start] Starting Next.js frontend on http://localhost:3000 ..." -ForegroundColor Cyan

# Frontend
Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory "$ProjectRoot\ui" `
    -WindowStyle Normal

Write-Host "[start] Both servers launched. Open http://localhost:3000" -ForegroundColor Green
