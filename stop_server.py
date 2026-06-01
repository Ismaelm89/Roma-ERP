"""Kill any Python process from this project's venv (i.e. the dev server).
Uses PowerShell Get-Process — wmic is removed on newer Windows."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = str(ROOT / '.venv' / 'Scripts' / 'python.exe')

ps = (
    f"Get-Process python -ErrorAction SilentlyContinue | "
    f"Where-Object {{ $_.Path -eq '{VENV_PY}' }} | "
    f"ForEach-Object {{ Stop-Process -Id $_.Id -Force; Write-Host \"killed $($_.Id)\" }}"
)
result = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                         capture_output=True, text=True)
out = (result.stdout or '').strip()
if out:
    print(out)
else:
    print('No running server found (nothing to stop).')
