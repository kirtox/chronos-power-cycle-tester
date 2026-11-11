"""Persistent app configuration (filter rules, device selections, test settings)."""
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

from .paths import get_config_path

DEFAULT_LEVELS = [1, 2, 3]  # Critical, Error, Warning


@dataclass
class FilterConfig:
    levels: List[int] = field(default_factory=lambda: list(DEFAULT_LEVELS))
    providers: List[str] = field(default_factory=list)
    event_ids: List[int] = field(default_factory=list)


@dataclass
class DeviceBaselineConfig:
    tracked_device_ids: List[str] = field(default_factory=list)


@dataclass
class PowerCycleTestConfig:
    types: List[str] = field(default_factory=lambda: ["reboot"])
    cycles_per_type: int = 10
    wake_delay_minutes: int = 5
    settle_seconds: int = 60
    stop_on_failure: bool = True
    mode: str = "per_type"  # "per_type" or "mixed"


@dataclass
class AppConfig:
    filter: FilterConfig = field(default_factory=FilterConfig)
    device_baseline: DeviceBaselineConfig = field(default_factory=DeviceBaselineConfig)
    power_cycle_test: PowerCycleTestConfig = field(default_factory=PowerCycleTestConfig)
    autostart_enabled: bool = False


def load_config() -> AppConfig:
    path = get_config_path()
    if not os.path.exists(path):
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return AppConfig()
    return AppConfig(
        filter=FilterConfig(**raw.get("filter", {})),
        device_baseline=DeviceBaselineConfig(**raw.get("device_baseline", {})),
        power_cycle_test=PowerCycleTestConfig(**raw.get("power_cycle_test", {})),
        autostart_enabled=raw.get("autostart_enabled", False),
    )


def save_config(config: AppConfig) -> None:
    path = get_config_path()
    data = {
        "filter": asdict(config.filter),
        "device_baseline": asdict(config.device_baseline),
        "power_cycle_test": asdict(config.power_cycle_test),
        "autostart_enabled": config.autostart_enabled,
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
