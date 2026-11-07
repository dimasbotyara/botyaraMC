"""Настройки лаунчера, список серверов, авто-RAM, кэш манифестов и пути."""
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

APP = "botyaraMC"
_FOLDER_SAFE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,47}$")


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


def sanitize_client_folder(raw):
    s = str(raw or "").strip()
    if not s or s.lower() in ("default", "none", ".minecraft", "minecraft"):
        return ""
    if ".." in s or "/" in s or "\\" in s:
        return ""
    return s if _FOLDER_SAFE_RE.fullmatch(s) else ""


def resolve_game_dir(mc_dir, client_folder=""):
    """Возвращает рабочую папку сборки (либо .minecraft, либо .minecraft/instances/<имя>)."""
    base = Path(mc_dir)
    sub = sanitize_client_folder(client_folder)
    if not sub:
        return base
    return base / "instances" / sub


DEFAULTS = {
    "language": "ru",               # "ru" | "en"
    "nickname": "",
    "theme": "Catppuccin Mocha",
    "sync_host": "",
    "sync_port": 25456,
    "servers": [],                  # [{"id", "name", "host", "port"}]
    "active_server_id": "",
    "is_host": False,
    "server_mods_dir": "",
    "mc_dir": "",
    "auto_ram": True,
    "ram_mb": 4096,
    "java_mode": "auto",            # "auto" | "manual"
    "java_path": "",
    "jvm_preset": "G1GC",
    "custom_jvm_presets": {},
    "extra_jvm_args": "",
    "window_mode": "default",       # "default" | "fullscreen" | "custom"
    "window_width": 1280,
    "window_height": 720,
    "launch_timeout": 120,
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


# ------------------------------------------------------------ управление списком серверов
def sync_servers_state(cfg):
    """Синхронизирует список servers <-> active_server_id <-> sync_host/sync_port."""
    raw_list = cfg.get("servers")
    clean = []
    if isinstance(raw_list, list):
        for item in raw_list:
            if isinstance(item, dict) and item.get("host"):
                sid = str(item.get("id") or secrets.token_hex(4))
                host = str(item["host"]).strip()
                try:
                    port = int(item.get("port", 25456))
                except (TypeError, ValueError):
                    port = 25456
                name = str(item.get("name") or "").strip()
                clean.append({"id": sid, "name": name, "host": host, "port": port})

    # Миграция старого одиночного сервера в список
    if not clean and cfg.get("sync_host"):
        sid = secrets.token_hex(4)
        clean.append({
            "id": sid,
            "name": "",
            "host": str(cfg["sync_host"]).strip(),
            "port": int(cfg.get("sync_port", 25456)),
        })
        cfg["active_server_id"] = sid

    cfg["servers"] = clean
    if clean:
        active = next((s for s in clean if s["id"] == cfg.get("active_server_id")), None)
        if active is None:
            active = clean[0]
            cfg["active_server_id"] = active["id"]
        cfg["sync_host"] = active["host"]
        cfg["sync_port"] = active["port"]
    else:
        cfg["active_server_id"] = ""
        cfg["sync_host"] = ""
        cfg["sync_port"] = 25456
    return cfg


def _server_id(host, port=25456):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{str(host).strip().lower()}_{int(port or 25456)}")
    return safe or secrets.token_hex(4)


def get_active_server(cfg):
    sync_servers_state(cfg)
    for s in cfg["servers"]:
        if s["id"] == cfg.get("active_server_id"):
            return s
    return None


active_server = get_active_server


def server_display_label(srv):
    addr = srv["host"] if srv.get("port", 25456) == 25456 else f"{srv['host']}:{srv['port']}"
    nm = (srv.get("name") or "").strip()
    if nm and nm != addr:
        return f"{nm} ({addr})"
    return addr


def add_or_select_server(cfg, host, port=25456, name=""):
    sync_servers_state(cfg)
    host = str(host).strip()
    port = int(port or 25456)
    for s in cfg["servers"]:
        if s["host"].lower() == host.lower() and int(s["port"]) == port:
            if name and not s.get("name"):
                s["name"] = name.strip()
            cfg["active_server_id"] = s["id"]
            sync_servers_state(cfg)
            return s
    new_srv = {
        "id": secrets.token_hex(4),
        "name": (name or "").strip(),
        "host": host,
        "port": port,
    }
    cfg["servers"].append(new_srv)
    cfg["active_server_id"] = new_srv["id"]
    sync_servers_state(cfg)
    return new_srv


def update_server_name(cfg, server_name_or_host, port=None, server_name=None, server_id=None):
    sync_servers_state(cfg)
    if server_name is None and port is None:
        # Вызов вида update_server_name(cfg, "Name", server_id=...)
        target_name = str(server_name_or_host or "").strip()[:64]
        if not target_name:
            return False
        sid = server_id or cfg.get("active_server_id")
        changed = False
        for s in cfg.get("servers", []):
            if sid and s["id"] == sid:
                if s.get("name") != target_name:
                    s["name"] = target_name
                    changed = True
        return changed

    if not server_name:
        return False
    changed = False
    for s in cfg.get("servers", []):
        if s["host"].lower() == str(server_name_or_host).lower() and int(s["port"]) == int(port):
            if s.get("name") != server_name:
                s["name"] = str(server_name).strip()[:64]
                changed = True
    return changed


def remove_server(cfg, server_id):
    sync_servers_state(cfg)
    cfg["servers"] = [s for s in cfg["servers"] if s["id"] != server_id]
    sync_servers_state(cfg)


def reset_account_and_servers(cfg):
    """Выход из аккаунта лаунчера и очистка всех сохранённых серверов."""
    cfg["nickname"] = ""
    cfg["servers"] = []
    cfg["active_server_id"] = ""
    cfg["sync_host"] = ""
    cfg["sync_port"] = 25456
    cfg["is_host"] = False
    cfg["setup_done"] = False
    save(cfg)
    for p in config_dir().glob("manifest_cache*.json"):
        try:
            p.unlink()
        except OSError:
            pass
    return cfg


def load():
    cfg = dict(DEFAULTS)
    cfg["servers"] = []
    cfg["custom_jvm_presets"] = {}
    saved = _read("config.json", {})
    if isinstance(saved, dict):
        if "auto_ram" not in saved and "ram_mb" in saved:
            saved = dict(saved)
            saved["auto_ram"] = False
        cfg.update(saved)
    if cfg.get("language") not in ("ru", "en"):
        cfg["language"] = "ru"
    if not isinstance(cfg.get("custom_jvm_presets"), dict):
        cfg["custom_jvm_presets"] = {}
    sync_servers_state(cfg)
    return cfg


def save(cfg):
    sync_servers_state(cfg)
    _write("config.json", cfg)


def _cache_filename(host="", port=25456, server_id=None):
    tag = str(server_id or "").strip()
    if tag:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", tag)
        return f"manifest_cache_{safe}.json"
    if not host:
        return "manifest_cache.json"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{host}_{port}")
    return f"manifest_cache_{safe}.json"


def save_cache(manifest, server_id=None, host="", port=25456):
    fname = _cache_filename(host, port, server_id=server_id)
    _write(fname, manifest)
    if fname != "manifest_cache.json":
        _write("manifest_cache.json", manifest)


def load_cache(server_id=None, host="", port=25456):
    fname = _cache_filename(host, port, server_id=server_id)
    if fname != "manifest_cache.json":
        data = _read(fname, None)
        if isinstance(data, dict) and "mc_version" in data:
            return data
    data = _read("manifest_cache.json", None)
    return data if isinstance(data, dict) and "mc_version" in data else None
