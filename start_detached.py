"""One-shot launcher: fork off Django runserver as a fully detached process
that survives the parent dying.  Run once, then close.  Server stays alive
until you kill it from Task Manager or run stop_server.py."""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv' / 'Scripts' / 'python.exe'

# Windows: DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_FLAGS = 0x00000008 | 0x00000200

log_path = ROOT / 'server.log'
log_file = open(log_path, 'ab')

env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'

p = subprocess.Popen(
    # Bind to 0.0.0.0 so other devices on the same Wi-Fi can reach the server.
    # Access from the laptop:  http://127.0.0.1:8001/
    # Access from phone/etc.:  http://<laptop's LAN IP>:8001/
    # (Port 8001 to avoid clashing with Comfit-ERP on 8000.)
    [str(PYTHON), 'manage.py', 'runserver', '0.0.0.0:8001', '--noreload'],
    cwd=str(ROOT),
    stdin=subprocess.DEVNULL,
    stdout=log_file,
    stderr=subprocess.STDOUT,
    creationflags=CREATE_FLAGS,
    close_fds=True,
    env=env,
)
print(f'Detached server PID: {p.pid}')
print(f'Log: {log_path}')
time.sleep(2)
print(f'Process alive: {p.poll() is None}')
