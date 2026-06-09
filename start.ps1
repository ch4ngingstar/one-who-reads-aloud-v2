$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m uvicorn api:app --port 8000 --reload" -WorkingDirectory "$root\src"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev"                                    -WorkingDirectory "$root\ui"

Start-Sleep -Seconds 5
Start-Process "http://localhost:3000"
