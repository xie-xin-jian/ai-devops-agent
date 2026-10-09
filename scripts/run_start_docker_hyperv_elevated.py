"""Launch Docker Desktop with isolated app-data and Hyper-V backend."""

import ctypes
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
cmd_path = project_root / "scripts" / "start_docker_hyperv.cmd"
result = ctypes.windll.shell32.ShellExecuteW(
    None,
    "runas",
    r"C:\Windows\System32\cmd.exe",
    f'/c "{cmd_path}"',
    str(project_root),
    1,
)
print(result)
