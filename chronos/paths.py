"""Shared filesystem paths for app data (config, bookmark, database, logs)."""
import os
import sys


def get_app_data_dir() -> str:
    """Return %LOCALAPPDATA%\\Chronos, creating it if needed."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    app_dir = os.path.join(base, "Chronos")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def get_config_path() -> str:
    return os.path.join(get_app_data_dir(), "config.json")


def get_bookmark_path() -> str:
    return os.path.join(get_app_data_dir(), "bookmark.xml")


def get_db_path() -> str:
    return os.path.join(get_app_data_dir(), "chronos.db")


def get_log_path() -> str:
    return os.path.join(get_app_data_dir(), "chronos.log")


def get_exe_path() -> str:
    """Return the path to invoke this app again (frozen exe or current interpreter + script)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return sys.executable
