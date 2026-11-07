"""Настройки лаунчера, кэш манифеста и пути (Windows / macOS / Linux)."""
import json
import os
import sys
from pathlib import Path

APP = "botyaraMC"


def config_dir():
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS = {
    "nickname": "",
    "theme": "Catppuccin Mocha",
    "sync_host": "",
    "sync_port": 25456,
    "is_host": False,
    "server_mods_dir": "",
    "mc_dir": "",
    "ram_mb": 4096,
    "setup_done": False,
}


def _read(name, default):
    try:
        return json.loads((config_dir() / name).read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write(name, data):
    path = config_dir() / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def load():
    cfg = dict(DEFAULTS)
    cfg.update(_read("config.json", {}))
    return cfg


def save(cfg):
    _write("config.json", cfg)


def save_cache(manifest):
    _write("manifest_cache.json", manifest)


def load_cache():
    data = _read("manifest_cache.json", None)
    return data if isinstance(data, dict) and "mc_version" in data else None
