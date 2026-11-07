"""Настройки лаунчера, авто-RAM, кэш манифеста и пути (Windows / macOS / Linux)."""
import json
import os
import subprocess
import sys
from pathlib import Path

APP = "botyaraMC"


def config_dir():
    env_override = os.environ.get("BOTYARAMC_CONFIG_DIR")
    if env_override:
        d = Path(env_override)
        d.mkdir(parents=True, exist_ok=True)
        return d
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


def system_ram_mb():
    """Общий объём ОЗУ системы в МБ."""
    try:
        import psutil
        return max(2048, int(psutil.virtual_memory().total // (1024 * 1024)))
    except Exception:
        return 8192


def recommended_ram_mb(total_mb=None):
    """Оптимальный объём RAM для Minecraft с модами (без лишних пауз GC)."""
    total = total_mb or system_ram_mb()
    if total <= 4096:
        return 2048
    if total <= 6144:
        return 3072
    if total <= 8192:
        return 4096
    if total <= 12288:
        return 5120
    if total <= 16384:
        return 6144
    if total <= 24576:
        return 8192
    return 10240


def max_selectable_ram_mb():
    """Верхняя граница ползунка RAM (~85% системной памяти, но не меньше 4 ГБ)."""
    total = system_ram_mb()
    cap = int(total * 0.85) // 256 * 256
    return max(4096, min(32768, cap))


DEFAULTS = {
    "nickname": "",
    "theme": "Catppuccin Mocha",
    "sync_host": "",
    "sync_port": 25456,
    "is_host": False,
    "server_mods_dir": "",
    "mc_dir": "",
    "auto_ram": True,
    "ram_mb": 4096,
    "java_mode": "auto",            # "auto" | "manual"
    "java_path": "",                # путь к java при ручном выборе
    "jvm_preset": "G1GC",           # выбранный пресет JVM
    "custom_jvm_presets": {},       # {имя: строка с аргументами}
    "extra_jvm_args": "",           # доп. аргументы поверх пресета
    "window_mode": "default",       # "default" | "fullscreen" | "custom"
    "window_width": 1280,
    "window_height": 720,
    "launch_timeout": 120,          # сек (0 = без таймаута)
    "setup_done": False,
}


def effective_ram_mb(cfg):
    if cfg.get("auto_ram", True):
        return recommended_ram_mb()
    try:
        return max(1024, int(cfg.get("ram_mb", 4096)))
    except (TypeError, ValueError):
        return 4096


def open_folder(path):
    """Создаёт папку (если её ещё нет) и открывает в системном проводнике."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    cfg["custom_jvm_presets"] = {}
    saved = _read("config.json", {})
    if isinstance(saved, dict):
        # Если конфиг старый (без auto_ram, но с явно заданным ram_mb != 4096), сохраняем выбор
        if "auto_ram" not in saved and "ram_mb" in saved:
            saved = dict(saved)
            saved["auto_ram"] = False
        cfg.update(saved)
    if not isinstance(cfg.get("custom_jvm_presets"), dict):
        cfg["custom_jvm_presets"] = {}
    return cfg


def save(cfg):
    _write("config.json", cfg)


def save_cache(manifest):
    _write("manifest_cache.json", manifest)


def load_cache():
    data = _read("manifest_cache.json", None)
    return data if isinstance(data, dict) and "mc_version" in data else None
