$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
# .env is loaded by main.py (load_dotenv) after uvicorn imports the app.
& "$PSScriptRoot\venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
