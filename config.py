import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SERVICES_FILE = os.path.join(BASE_DIR, "services.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

_cached_settings = None
_settings_mtime = 0

def load_settings():
    global _cached_settings, _settings_mtime
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        mtime = os.path.getmtime(SETTINGS_FILE)
        if _cached_settings is not None and mtime == _settings_mtime:
            return _cached_settings
        with open(SETTINGS_FILE, "r") as f:
            _cached_settings = json.load(f)
            _settings_mtime = mtime
            return _cached_settings
    except Exception:
        return _cached_settings or {}

def save_settings(settings_data):
    global _cached_settings, _settings_mtime
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings_data, f, indent=2)
    _cached_settings = settings_data
    try:
        _settings_mtime = os.path.getmtime(SETTINGS_FILE)
    except Exception:
        pass
