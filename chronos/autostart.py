"""Register/unregister the app to auto-start at user logon via Task Scheduler."""
import subprocess
import sys

from .paths import get_exe_path

TASK_NAME = "Chronos_AutoStart"


def _build_command() -> str:
    exe = get_exe_path()
    if getattr(sys, "frozen", False):
        return f'"{exe}"'
    # Running from source: re-invoke the interpreter with the main module.
    return f'"{exe}" "{sys.argv[0]}"'


def register() -> None:
    command = _build_command()
    subprocess.run(
        [
            "schtasks", "/create", "/tn", TASK_NAME, "/sc", "onlogon",
            "/rl", "limited", "/tr", command, "/f",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def unregister() -> None:
    subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        check=False,
        capture_output=True,
        text=True,
    )


def is_registered() -> bool:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
