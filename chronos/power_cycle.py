"""Power Cycle Test: trigger Reboot / Sleep(Modern Standby) / Hibernate cycles and
verify each one using System log Kernel-Power / Power-Troubleshooter events plus a
Device Manager baseline comparison.

Event IDs below were confirmed by live inspection of this machine's System log
(see DESIGN_DECISIONS.md) rather than assumed from memory:
    Kernel-Power 41  = system rebooted without cleanly shutting down (FAILURE signal)
    Kernel-Power 42  = system is entering sleep
    Kernel-Power 107 = system has resumed from sleep
    Kernel-Power 109 = kernel power manager initiated a shutdown transition (Action field)
    Kernel-Power 506 = system is entering Modern Standby
    Kernel-Power 507 = system is exiting Modern Standby
    Power-Troubleshooter 1 = system returned from a low power state, with structured
        EventData fields SleepTime / WakeTime / SleepDuration / TargetState / WakeSourceType
"""
import ctypes
import json
import logging
import os
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

import win32evtlog as evt

from . import autostart, device_baseline, storage, wake_scheduler
from .config import PowerCycleTestConfig
from .paths import get_app_data_dir

logger = logging.getLogger(__name__)

KERNEL_POWER = "Microsoft-Windows-Kernel-Power"
POWER_TROUBLESHOOTER = "Microsoft-Windows-Power-Troubleshooter"
EVT_DIRTY_SHUTDOWN = 41
EVT_ENTERING_SLEEP = 42
EVT_RESUMED_FROM_SLEEP = 107
EVT_SHUTDOWN_INITIATED = 109
EVT_ENTERING_MODERN_STANDBY = 506
EVT_EXITING_MODERN_STANDBY = 507
EVT_TROUBLESHOOTER_RESUME = 1

WAKE_TASK_NAME = "Chronos_PowerCycleWake"
STATE_FILENAME = "power_cycle_state.json"


def _state_path() -> str:
    return os.path.join(get_app_data_dir(), STATE_FILENAME)


@dataclass
class PowerCycleState:
    row_id: int
    cycle_type: str
    cycle_index: int
    start_time: str
    queue: List[List[str]]  # list of [cycle_type, cycle_index_str] remaining after this one
    baseline_device_ids: List[str]
    baseline_snapshot: List[dict]  # captured once before the whole test started
    settle_seconds: int
    wake_delay_minutes: int
    stop_on_failure: bool
    restore_autostart: bool  # whether to unregister autostart when the whole test ends


def save_state(state: PowerCycleState) -> None:
    tmp = _state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f)
    os.replace(tmp, _state_path())


def load_state() -> Optional[PowerCycleState]:
    path = _state_path()
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return PowerCycleState(**raw)


def clear_state() -> None:
    path = _state_path()
    if os.path.exists(path):
        os.remove(path)


def detect_supported_states() -> dict:
    """Parse `powercfg /a` to find which sleep states this machine actually supports."""
    result = subprocess.run(["powercfg", "/a"], capture_output=True, text=True, check=False)
    output = result.stdout
    available_section = output.split("not available")[0]
    return {
        "modern_standby": "S0 Low Power Idle" in available_section,
        "s3": "Standby (S3)" in available_section,
        "hibernate": "Hibernate" in available_section,
    }


def enable_hibernate() -> None:
    """Enable hibernation, which requires elevation. Triggers a single UAC prompt."""
    ctypes.windll.shell32.ShellExecuteW(None, "runas", "powercfg", "/hibernate on", None, 1)


def trigger_reboot() -> None:
    subprocess.run(["shutdown", "/r", "/t", "3"], check=True)


def trigger_sleep() -> None:
    """Blocks until the system resumes (the calling thread suspends with the OS)."""
    subprocess.run(
        ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=False
    )


def trigger_hibernate() -> None:
    subprocess.run(["shutdown", "/h"], check=False)


def _query_recent_events(provider: str, event_ids: List[int], since: datetime) -> List[dict]:
    ids_clause = " or ".join(f"EventID={eid}" for eid in event_ids)
    query = f"*[System[Provider[@Name='{provider}'] and ({ids_clause})]]"
    q = evt.EvtQuery("System", evt.EvtQueryReverseDirection, query)
    ctx = evt.EvtCreateRenderContext(evt.EvtRenderContextSystem)
    out = []
    while True:
        batch = evt.EvtNext(q, 50)
        if not batch:
            break
        stop = False
        for event_handle in batch:
            result = evt.EvtRender(event_handle, evt.EvtRenderEventValues, Context=ctx)
            tc = result[evt.EvtSystemTimeCreated][0]
            if tc < since:
                stop = True
                break
            out.append({
                "event_id": result[evt.EvtSystemEventID][0],
                "time_created": tc,
                "xml": evt.EvtRender(event_handle, evt.EvtRenderEventXml),
            })
        if stop:
            break
    return out


def _parse_event_data(xml_text: str) -> dict:
    ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
    root = ET.fromstring(xml_text)
    data = {}
    for el in root.findall(".//e:EventData/e:Data", ns):
        name = el.get("Name")
        if name:
            data[name] = el.text
    return data


def verify_cycle(cycle_type: str, start_time: datetime) -> Tuple[bool, str]:
    """Verify a completed cycle by inspecting Kernel-Power/Power-Troubleshooter events
    logged since `start_time`."""
    dirty = _query_recent_events(KERNEL_POWER, [EVT_DIRTY_SHUTDOWN], start_time)
    if dirty:
        return False, "偵測到 Kernel-Power Event 41（未正常關機/意外斷電）"

    if cycle_type == "reboot":
        reboots = _query_recent_events(KERNEL_POWER, [EVT_SHUTDOWN_INITIATED], start_time)
        if not reboots:
            return False, "沒有找到 Event 109（正常重開機發起）紀錄"
        return True, "乾淨重開機，無 Event 41"

    # sleep / hibernate: look for a resume event via Power-Troubleshooter or Kernel-Power
    resumes = _query_recent_events(POWER_TROUBLESHOOTER, [EVT_TROUBLESHOOTER_RESUME], start_time)
    if resumes:
        data = _parse_event_data(resumes[0]["xml"])
        return True, f"恢復成功，SleepDuration={data.get('SleepDuration', '?')}s"

    kp_resumes = _query_recent_events(
        KERNEL_POWER, [EVT_RESUMED_FROM_SLEEP, EVT_EXITING_MODERN_STANDBY], start_time
    )
    if kp_resumes:
        return True, f"恢復成功（Event {kp_resumes[0]['event_id']}）"

    return False, "找不到任何恢復事件，系統可能沒有真正進入睡眠/休眠"


class PowerCycleTestRunner:
    """Orchestrates a multi-cycle Power Cycle Test. Runs synchronously on a worker
    thread; Sleep/Hibernate cycles block in-place (the OS suspends this thread along
    with everything else), Reboot cycles terminate the process and rely on
    `resume_after_restart()` being called from `main.py` at the next launch."""

    def __init__(self,
                 on_progress: Callable[[dict], None],
                 on_finished: Callable[[], None]):
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._stopped = threading.Event()

    def start_new_test(self, config: PowerCycleTestConfig, tracked_device_ids: List[str]) -> None:
        queue = []
        if config.mode == "mixed":
            for i in range(1, config.cycles_per_type + 1):
                for t in config.types:
                    queue.append([t, i])
        else:
            for t in config.types:
                for i in range(1, config.cycles_per_type + 1):
                    queue.append([t, i])

        was_registered = autostart.is_registered()
        baseline_snapshot = device_baseline.take_snapshot(tracked_device_ids)
        state = PowerCycleState(
            row_id=-1,
            cycle_type="",
            cycle_index=0,
            start_time="",
            queue=queue,
            baseline_device_ids=tracked_device_ids,
            baseline_snapshot=baseline_snapshot,
            settle_seconds=config.settle_seconds,
            wake_delay_minutes=config.wake_delay_minutes,
            stop_on_failure=config.stop_on_failure,
            restore_autostart=not was_registered,
        )
        threading.Thread(target=self._drive, args=(state,), daemon=True).start()

    def resume_after_restart(self) -> None:
        """Call once at app startup. If a cycle was in-flight when we rebooted,
        verify it and continue the queue."""
        state = load_state()
        if state is None:
            return
        threading.Thread(target=self._verify_and_continue, args=(state,), daemon=True).start()

    def stop(self) -> None:
        self._stopped.set()

    def _verify_and_continue(self, state: PowerCycleState) -> None:
        start_time = datetime.fromisoformat(state.start_time)
        time.sleep(state.settle_seconds)
        passed, reason = verify_cycle(state.cycle_type, start_time)
        self._finish_one_cycle(state, passed, reason)

    def _finish_one_cycle(self, state: PowerCycleState, passed: bool, reason: str) -> None:
        current = device_baseline.take_snapshot(state.baseline_device_ids)
        diffs = device_baseline.compare(state.baseline_snapshot, current)
        if diffs:
            passed = False
            reason += f"; 裝置狀態不一致: {diffs}"

        storage.update_power_cycle_result(
            state.row_id, datetime.now(timezone.utc).isoformat(),
            "pass" if passed else "fail", reason,
        )
        self._on_progress({
            "cycle_type": state.cycle_type,
            "cycle_index": state.cycle_index,
            "result": "pass" if passed else "fail",
            "reason": reason,
        })

        if not passed and state.stop_on_failure:
            clear_state()
            if state.restore_autostart:
                autostart.unregister()
            self._on_finished()
            return

        self._drive(state)

    def _drive(self, state: PowerCycleState) -> None:
        if self._stopped.is_set() or not state.queue:
            clear_state()
            if state.restore_autostart:
                autostart.unregister()
            self._on_finished()
            return

        cycle_type, cycle_index = state.queue.pop(0)
        start_time = datetime.now(timezone.utc)
        row_id = storage.insert_power_cycle_result(
            cycle_type, cycle_index, start_time.isoformat(), None, "running",
        )
        next_state = PowerCycleState(
            row_id=row_id,
            cycle_type=cycle_type,
            cycle_index=cycle_index,
            start_time=start_time.isoformat(),
            queue=state.queue,
            baseline_device_ids=state.baseline_device_ids,
            baseline_snapshot=state.baseline_snapshot,
            settle_seconds=state.settle_seconds,
            wake_delay_minutes=state.wake_delay_minutes,
            stop_on_failure=state.stop_on_failure,
            restore_autostart=state.restore_autostart,
        )
        save_state(next_state)

        if cycle_type == "reboot":
            autostart.register()
            self._on_progress({"cycle_type": cycle_type, "cycle_index": cycle_index, "result": "running", "reason": "觸發 Reboot..."})
            trigger_reboot()
            return  # process will be terminated by the OS shortly

        # sleep / hibernate: create a hardware wake timer, then suspend in-place.
        # The task's own action is a no-op (`cmd /c exit`) -- our process is not
        # killed by suspend, it simply resumes execution right after this call
        # returns, so we don't want the wake task launching a second instance.
        wake_at = datetime.now() + timedelta(minutes=state.wake_delay_minutes)
        wake_scheduler.create_wake_task(
            WAKE_TASK_NAME, wake_at, r"C:\Windows\System32\cmd.exe", "/c exit"
        )
        self._on_progress({"cycle_type": cycle_type, "cycle_index": cycle_index, "result": "running", "reason": f"觸發 {cycle_type}..."})
        if cycle_type == "sleep":
            trigger_sleep()
        else:
            trigger_hibernate()
        wake_scheduler.delete_wake_task(WAKE_TASK_NAME)

        time.sleep(next_state.settle_seconds)
        passed, reason = verify_cycle(cycle_type, start_time)
        self._finish_one_cycle(next_state, passed, reason)
