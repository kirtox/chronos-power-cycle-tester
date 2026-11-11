"""Create/remove one-shot 'wake the computer to run this task' Task Scheduler
entries, used to resume the Power Cycle Test after Sleep/Hibernate."""
import os
import subprocess
import tempfile
from datetime import datetime

TASK_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{start_boundary}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user_id}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <WakeToRun>true</WakeToRun>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _current_user_id() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain else user


def create_wake_task(task_name: str, run_at: datetime, command: str, arguments: str = "") -> None:
    """Create a one-shot task that wakes the computer at `run_at` and runs `command`."""
    xml = TASK_XML_TEMPLATE.format(
        start_boundary=run_at.strftime("%Y-%m-%dT%H:%M:%S"),
        user_id=_current_user_id(),
        command=command,
        arguments=arguments,
    )
    fd, xml_path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(xml)
        subprocess.run(
            ["schtasks", "/create", "/tn", task_name, "/xml", xml_path, "/f"],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(xml_path)


def delete_wake_task(task_name: str) -> None:
    subprocess.run(
        ["schtasks", "/delete", "/tn", task_name, "/f"],
        check=False,
        capture_output=True,
        text=True,
    )
