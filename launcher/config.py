"""Настройки лаунчера, мульти-серверы, режимы папок (home/instances), маркеры botyaramc.json и авто-RAM."""
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

APP = "botyaraMC"
MARKER_FILENAME = "botyaramc.json"

_FOLDER_SAFE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,47}$")
_WIN_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_FORBIDDEN_LOCAL_CHARS = set('/\\:*?"<>|\x00')

LOADER_TITLES = {
    "fabric": "Fabric",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "quilt": "Quilt",
    "optifine": "OptiFine",
    "none": "",
}


def config_dir(create=True):
    env_override = os.environ.get("BOTYARAMC_CONFIG_DIR")
    if env_override:
        d = Path(env_override)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        d = base / APP
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / APP
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        d = base / APP
    if create:
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
    """Строгая санитизация имени папки, пришедшего по сети от сервера."""
    s = str(raw or "").strip()
    if not s or s.lower() in ("default", "none", ".minecraft", "minecraft"):
        return ""
    if ".." in s or "/" in s or "\\" in s:
        return ""
    return s if _FOLDER_SAFE_RE.fullmatch(s) else ""


def sanitize_local_folder_name(raw):
    """
    Безопасная валидация локального имени подпапки (разрешает пробелы и кириллицу,
    например 'Fabric 1.16.5' или 'Моя сборка', но блокирует слэши, '..' и системные имена).
    """
    s = str(raw or "").strip()
    if not s or len(s) > 64:
        return ""
    if s in (".", "..") or ".." in s:
        return ""
    if s.endswith(".") or any(ch in _FORBIDDEN_LOCAL_CHARS or ord(ch) < 32 for ch in s):
        return ""
    if s.lower() in (".minecraft", "minecraft") or s.split(".")[0].lower() in _WIN_RESERVED:
        return ""
    return s


def mc_family_name(mc_version):
    """Выделяет семейство версии: '1.16.5' -> '1.16', '1.20.1' -> '1.20', 'rd-132211' -> 'rd-132211'."""
    v = str(mc_version or "").strip()
    m = re.match(r"^(\d+\.\d+)(?:\.\d+)?$", v)
    if m:
        return m.group(1)
    return sanitize_local_folder_name(v) or "Minecraft"


def family_folder_name(mc_version, loader="none", mc_dir=None):
    """Имя папки для режима 'По семействам' (по типу home/Fabric-1.16)."""
    fam = mc_family_name(mc_version)
    ld = LOADER_TITLES.get(str(loader or "none").lower(), str(loader or "").capitalize())
    default_name = f"{ld}-{fam}" if ld else fam
    if mc_dir:
        home = Path(mc_dir) / "home"
        alt_space = f"{ld} {fam}" if ld else fam
        if not (home / default_name).exists() and (home / alt_space).is_dir():
            return alt_space
    return default_name


def version_folder_name(mc_version, loader="none", mc_dir=None):
    """Имя папки для режима 'По версиям' (по типу home/Fabric 1.16.5)."""
    ver = sanitize_local_folder_name(mc_version) or "1.20.1"
    ld = LOADER_TITLES.get(str(loader or "none").lower(), str(loader or "").capitalize())
    default_name = f"{ld} {ver}" if ld else ver
    if mc_dir:
        home = Path(mc_dir) / "home"
        alt_dash = f"{ld}-{ver}" if ld else ver
        if not (home / default_name).exists() and (home / alt_dash).is_dir():
            return alt_dash
    return default_name


# ------------------------------------------------------------ botyaramc.json внутри папок сборок
def read_folder_marker(folder_path):
    """Безопасно читает botyaramc.json из папки сборки (защита от ручной правки/поломки)."""
    p = Path(folder_path) / MARKER_FILENAME
    try:
        data = json.loads(p.read_text("utf-8"))
        if isinstance(data, dict) and data.get("app") == APP:
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None


def write_folder_marker(folder_path, server_entry=None, extra=None):
    """Записывает/обновляет botyaramc.json внутри папки сборки."""
    folder = Path(folder_path)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    cur = read_folder_marker(folder) or {"app": APP, "server_ids": []}
    sids = list(cur.get("server_ids") or [])
    if isinstance(server_entry, dict) and server_entry.get("id"):
        sid = str(server_entry["id"])
        if sid not in sids:
            sids.append(sid)
        cur["server_ids"] = sids
        cur["last_server_id"] = sid
        if server_entry.get("name"):
            cur["server_name"] = server_entry["name"]
        if server_entry.get("host"):
            cur["sync_host"] = server_entry["host"]
            cur["sync_port"] = int(server_entry.get("port", 25456))
    if isinstance(extra, dict):
        cur.update(extra)
    marker_file = folder / MARKER_FILENAME
    tmp = marker_file.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, marker_file)
    except OSError:
        pass


def find_relocated_server_folder(mc_dir, server_id, sync_host="", sync_port=25456):
    """
    Защита от переименования папки в Проводнике / файловом менеджере:
    ищет подпапку в .minecraft/home/* и .minecraft/instances/* по botyaramc.json.
    """
    if not mc_dir or not server_id:
        return None
    base = Path(mc_dir)
    for container_name in ("home", "instances"):
        container = base / container_name
        if not container.is_dir():
            continue
        try:
            subdirs = sorted(p for p in container.iterdir() if p.is_dir())
        except OSError:
            continue
        for sub in subdirs:
            marker = read_folder_marker(sub) or read_folder_marker(sub / "mods")
            if not marker:
                continue
            sids = marker.get("server_ids") or []
            if server_id in sids or marker.get("last_server_id") == server_id:
                return sub
    # Резервный поиск по host:port, если пересоздавался профиль с тем же адресом
    if sync_host:
        for container_name in ("home", "instances"):
            container = base / container_name
            if not container.is_dir():
                continue
            try:
                subdirs = sorted(p for p in container.iterdir() if p.is_dir())
            except OSError:
                continue
            for sub in subdirs:
                marker = read_folder_marker(sub)
                if (
                    marker
                    and str(marker.get("sync_host", "")).lower() == str(sync_host).lower()
                    and int(marker.get("sync_port", 25456)) == int(sync_port or 25456)
                ):
                    return sub
    return None


def resolve_game_dir(mc_dir, client_folder="", cfg=None, manifest=None, server_id=None):
    """
    Определяет рабочую папку сборки (gameDirectory) по приоритету:
    1) Кастомная папка этого сервера, заданная игроком в лаунчере (или найденная по botyaramc.json после переименования в Проводнике).
       Приоритет при поиске существующей папки: home/<имя> раньше instances/<имя>;
       если папки ещё нет — новой считается home/<имя>.
    2) Папка client_folder от сервера (.minecraft/instances/<имя> или .minecraft/home/<имя>)
    3) Режим разделения версий из настроек игрока:
       - 'none'    -> .minecraft
       - 'family'  -> .minecraft/home/Fabric-1.16
       - 'version' -> .minecraft/home/Fabric 1.16.5
    """
    base = Path(mc_dir)
    srv = None
    if isinstance(cfg, dict):
        sid = server_id or cfg.get("active_server_id")
        if sid:
            srv = next((s for s in (cfg.get("servers") or []) if s.get("id") == sid), None)
        if srv is None:
            srv = get_active_server(cfg)

    # 1. Пользовательское имя папки для конкретного сервера + защита от ручного переименования в Проводнике
    if srv is not None:
        custom_raw = sanitize_local_folder_name(srv.get("custom_folder", ""))
        if custom_raw:
            cand_home = base / "home" / custom_raw
            cand_inst = base / "instances" / custom_raw
            if cand_home.is_dir():
                return cand_home
            if cand_inst.is_dir():
                return cand_inst
            relocated = find_relocated_server_folder(
                base, srv.get("id"), srv.get("host", ""), srv.get("port", 25456)
            )
            if relocated is not None:
                srv["custom_folder"] = relocated.name
                return relocated
            return cand_home

    # 2. Серверный client_folder
    raw_cf = client_folder or ((manifest or {}).get("client_folder") if isinstance(manifest, dict) else "")
    sub = sanitize_client_folder(raw_cf)
    if sub:
        cand_inst = base / "instances" / sub
        cand_home = base / "home" / sub
        if cand_inst.is_dir():
            return cand_inst
        if cand_home.is_dir():
            return cand_home
        if srv is not None:
            relocated = find_relocated_server_folder(
                base, srv.get("id"), srv.get("host", ""), srv.get("port", 25456)
            )
            if relocated is not None:
                srv["custom_folder"] = relocated.name
                return relocated
        return cand_inst

    # 3. Режим разделения папок из настроек лаунчера
    iso = (cfg or {}).get("isolation_mode", "none") if isinstance(cfg, dict) else "none"
    mc_ver = (manifest or {}).get("mc_version") if isinstance(manifest, dict) else None
    loader = (manifest or {}).get("loader", "none") if isinstance(manifest, dict) else "none"

    if iso == "family" and mc_ver:
        return base / "home" / family_folder_name(mc_ver, loader, mc_dir=base)
    if iso == "version" and mc_ver:
        return base / "home" / version_folder_name(mc_ver, loader, mc_dir=base)
    return base


def rename_server_folder(cfg, mc_dir, new_folder_name, server_id=None, manifest=None):
    """
    Переименовывает/назначает папку сборки для выбранного сервера прямо из лаунчера.
    Если старая изолированная папка использовалась только этим сервером — переносит её на диске целиком.
    Возвращает (ok: bool, result_or_err_code: Path | str).
    """
    clean = sanitize_local_folder_name(new_folder_name)
    if not clean:
        return False, "bad_name"

    sync_servers_state(cfg)
    sid = server_id or cfg.get("active_server_id")
    srv = next((s for s in cfg.get("servers", []) if s["id"] == sid), None)
    if srv is None:
        return False, "no_server"

    base = Path(mc_dir)
    old_dir = resolve_game_dir(base, cfg=cfg, manifest=manifest, server_id=sid)
    parent_container = old_dir.parent if old_dir.parent.name in ("home", "instances") else (base / "home")
    new_dir = parent_container / clean

    try:
        same_dir = old_dir.exists() and new_dir.exists() and old_dir.resolve() == new_dir.resolve()
    except OSError:
        same_dir = False

    if not same_dir and new_dir.exists():
        marker = read_folder_marker(new_dir)
        sids = (marker or {}).get("server_ids") or []
        if sid not in sids and any(new_dir.iterdir()):
            return False, "already_exists"

    # Проверяем, не использует ли старую папку другой сохранённый сервер
    shared_with_other = False
    if old_dir.exists() and old_dir.resolve() != base.resolve():
        marker = read_folder_marker(old_dir)
        other_ids = [x for x in ((marker or {}).get("server_ids") or []) if x != sid]
        active_ids = {s["id"] for s in cfg.get("servers", []) if s["id"] != sid}
        if any(oid in active_ids for oid in other_ids):
            shared_with_other = True
        else:
            for other_s in cfg.get("servers", []):
                if other_s["id"] != sid:
                    od = resolve_game_dir(base, cfg=cfg, manifest=None, server_id=other_s["id"])
                    if od.resolve() == old_dir.resolve():
                        shared_with_other = True
                        break

    try:
        parent_container.mkdir(parents=True, exist_ok=True)
        if (
            not same_dir
            and old_dir.is_dir()
            and old_dir.resolve() != base.resolve()
            and not shared_with_other
            and not new_dir.exists()
        ):
            shutil.move(str(old_dir), str(new_dir))
        else:
            new_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False, "io_error"

    srv["custom_folder"] = clean
    write_folder_marker(new_dir, srv)
    save(cfg)
    return True, new_dir


def reset_server_folder(cfg, server_id=None):
    """Сбрасывает кастомное имя папки сервера обратно к автоматическому режиму."""
    sync_servers_state(cfg)
    sid = server_id or cfg.get("active_server_id")
    for s in cfg.get("servers", []):
        if s["id"] == sid:
            s["custom_folder"] = ""
    save(cfg)


DEFAULTS = {
    "language": "ru",               # "ru" | "en"
    "nickname": "",
    "theme": "Catppuccin Mocha",
    "sync_host": "",
    "sync_port": 25456,
    "servers": [],                  # [{"id", "name", "host", "port", "is_host", "server_mods_dir", "custom_folder"}]
    "active_server_id": "",
    "is_host": False,               # зеркало флага активного сервера
    "server_mods_dir": "",          # зеркало папки серверных модов активного сервера
    "mc_dir": "",
    "isolation_mode": "none",       # "none" | "family" (home/Fabric-1.16) | "version" (home/Fabric 1.16.5)
    "on_launch_action": "keep",     # "keep" | "minimize" | "hide"
    "use_server_bg": True,          # показывать ли кастомный фон от сервера
    "use_gamemode": False,          # Linux: gamemoderun
    "use_mangohud": False,          # Linux: mangohud
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
        p = config_dir(create=False) / name
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write(name, data):
    path = config_dir(create=True) / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------ хост-папки и валидация уникальности
def is_sync_server_own_mods_dir(path_str):
    """Проверяет, не указал ли хост саму раздающую папку botyaraMC/server/mods вместо папки Minecraft-сервера."""
    if not path_str:
        return False
    try:
        p = Path(path_str).expanduser().resolve()
        parent = p.parent
        return p.name == "mods" and (parent / "server.py").is_file() and (parent / "srv_config.py").is_file()
    except OSError:
        return False


def validate_unique_host_dir(cfg, server_id, candidate_dir):
    """
    Проверяет, что папка серверных модов уникальна среди сохранённых серверов.
    Если у другого сервера ранее была указана эта же директория, но сама директория на диске была удалена —
    старая привязка не мешает и папку использовать можно!
    Возвращает (ok: bool, conflict_label: str).
    """
    raw = str(candidate_dir or "").strip()
    if not raw:
        return False, ""
    try:
        cand_res = Path(raw).expanduser().resolve()
    except OSError:
        return False, ""

    for s in (cfg.get("servers") or []):
        if server_id and s.get("id") == server_id:
            continue
        other_raw = str(s.get("server_mods_dir") or "").strip()
        if not other_raw:
            continue
        other_p = Path(other_raw).expanduser()
        # Если директория была удалена с диска — освобождаем старую привязку!
        if not other_p.exists():
            s["is_host"] = False
            s["server_mods_dir"] = ""
            continue
        try:
            if other_p.resolve() == cand_res:
                return False, server_display_label(s)
        except OSError:
            continue
    return True, ""


# ------------------------------------------------------------ управление списком серверов
def sync_servers_state(cfg):
    """Синхронизирует список servers <-> active_server_id <-> sync_host/sync_port/is_host/server_mods_dir."""
    raw_list = cfg.get("servers")
    clean = []
    had_per_srv_host_keys = False
    if isinstance(raw_list, list):
        for item in raw_list:
            if isinstance(item, dict) and item.get("host"):
                if "is_host" in item or "server_mods_dir" in item:
                    had_per_srv_host_keys = True
                sid = str(item.get("id") or secrets.token_hex(4))
                host = str(item["host"]).strip()
                try:
                    port = int(item.get("port", 25456))
                except (TypeError, ValueError):
                    port = 25456
                name = str(item.get("name") or "").strip()
                s_is_host = bool(item.get("is_host", False))
                s_mods_dir = str(item.get("server_mods_dir") or "").strip()
                s_custom_folder = sanitize_local_folder_name(item.get("custom_folder", ""))
                clean.append({
                    "id": sid,
                    "name": name,
                    "host": host,
                    "port": port,
                    "is_host": s_is_host,
                    "server_mods_dir": s_mods_dir,
                    "custom_folder": s_custom_folder,
                })

    # Миграция старого одиночного сервера в список
    if not clean and cfg.get("sync_host"):
        sid = secrets.token_hex(4)
        clean.append({
            "id": sid,
            "name": "",
            "host": str(cfg["sync_host"]).strip(),
            "port": int(cfg.get("sync_port", 25456)),
            "is_host": bool(cfg.get("is_host", False)),
            "server_mods_dir": str(cfg.get("server_mods_dir") or "").strip(),
            "custom_folder": "",
        })
        cfg["active_server_id"] = sid
        had_per_srv_host_keys = True

    cfg["servers"] = clean
    if clean:
        active = next((s for s in clean if s["id"] == cfg.get("active_server_id")), None)
        if active is None:
            active = clean[0]
            cfg["active_server_id"] = active["id"]
        # Миграция старых верхнеуровневых is_host/server_mods_dir, если они задавались до мульти-серверов
        if not had_per_srv_host_keys and (cfg.get("is_host") or cfg.get("server_mods_dir")):
            active["is_host"] = bool(cfg.get("is_host", False))
            active["server_mods_dir"] = str(cfg.get("server_mods_dir") or "").strip()
        cfg["sync_host"] = active["host"]
        cfg["sync_port"] = active["port"]
        cfg["is_host"] = bool(active.get("is_host", False))
        cfg["server_mods_dir"] = str(active.get("server_mods_dir") or "")
    else:
        cfg["active_server_id"] = ""
        cfg["sync_host"] = ""
        cfg["sync_port"] = 25456
        cfg["is_host"] = False
        cfg["server_mods_dir"] = ""
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


def set_active_server_host_settings(cfg, is_host, server_mods_dir=""):
    """Сохраняет настройку 'я хост! 👑' и папку модов именно для текущего выбранного сервера."""
    srv = get_active_server(cfg)
    if srv is not None:
        srv["is_host"] = bool(is_host)
        srv["server_mods_dir"] = str(server_mods_dir or "").strip()
        sync_servers_state(cfg)
    else:
        cfg["is_host"] = bool(is_host)
        cfg["server_mods_dir"] = str(server_mods_dir or "").strip()


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
        "is_host": False,
        "server_mods_dir": "",
        "custom_folder": "",
    }
    cfg["servers"].append(new_srv)
    cfg["active_server_id"] = new_srv["id"]
    sync_servers_state(cfg)
    return new_srv


def update_active_server_address(cfg, host, port=25456):
    """
    Обновляет host:port у текущего сервера БЕЗ смены его id (чтобы не ломать привязку папки и кэш).
    Если адрес изменился — очищает устаревший кэш манифеста этого id.
    """
    srv = get_active_server(cfg)
    host = str(host).strip()
    port = int(port or 25456)
    if srv is None:
        return add_or_select_server(cfg, host, port)
    changed = (srv["host"].lower() != host.lower() or int(srv["port"]) != port)
    srv["host"] = host
    srv["port"] = port
    if changed:
        srv["name"] = ""
        cache_p = config_dir(create=False) / _cache_filename(server_id=srv["id"])
        try:
            cache_p.unlink()
        except OSError:
            pass
    sync_servers_state(cfg)
    return srv


def match_discovered_server(cfg, candidates):
    """
    Умное сопоставление ответивших в LAN/Radmin серверов при недоступности основного IP:
    - Не перехватывает ЧУЖОЙ сервер из списка серверов игрока!
    - Если сменился Radmin IP у нашего сервера — обновляет адрес на месте без дублей.
    Возвращает (host, port, sname, server_entry) или None.
    """
    if not candidates:
        return None
    sync_servers_state(cfg)
    servers = cfg.get("servers") or []
    if not servers:
        fh, fp, fname = candidates[0]
        entry = add_or_select_server(cfg, fh, fp, name=fname)
        return fh, fp, fname, entry

    cur = get_active_server(cfg)
    if cur is None:
        return None

    other_addrs = {
        (s["host"].lower(), int(s["port"]))
        for s in servers if s["id"] != cur["id"]
    }
    other_names = {
        s["name"].strip().lower()
        for s in servers if s["id"] != cur["id"] and s.get("name", "").strip()
    }

    filtered = [
        (fh, fp, fname) for (fh, fp, fname) in candidates
        if (fh.lower(), int(fp)) not in other_addrs
        and (not fname or fname.strip().lower() not in other_names)
    ]
    if not filtered:
        return None

    cur_name = (cur.get("name") or "").strip().lower()
    if cur_name:
        for fh, fp, fname in filtered:
            if fname and fname.strip().lower() == cur_name:
                cur["host"], cur["port"] = fh, int(fp)
                sync_servers_state(cfg)
                return fh, int(fp), fname, cur
        return None

    # Имя ещё не было известно и сервер в списке всего один -> обновляем его IP на месте
    if len(servers) == 1 and len(filtered) == 1:
        fh, fp, fname = filtered[0]
        cur["host"], cur["port"] = fh, int(fp)
        if fname:
            cur["name"] = fname
        sync_servers_state(cfg)
        return fh, int(fp), fname, cur

    return None


def update_server_name(cfg, server_name_or_host, port=None, server_name=None, server_id=None):
    sync_servers_state(cfg)
    if server_name is None and port is None:
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
    if server_id:
        cache_p = config_dir(create=False) / _cache_filename(server_id=server_id)
        try:
            cache_p.unlink()
        except OSError:
            pass
    sync_servers_state(cfg)


def _close_config_log_handlers(cfg_path):
    """Отсоединяет и закрывает FileHandler-ы внутри папки конфига перед её полным удалением."""
    try:
        cfg_res = Path(cfg_path).resolve()
    except OSError:
        return
    root_logger = logging.getLogger()
    for lg in [root_logger, *[logging.getLogger(n) for n in list(logging.Logger.manager.loggerDict)]]:
        for h in list(getattr(lg, "handlers", [])):
            base_fn = getattr(h, "baseFilename", None)
            if base_fn:
                try:
                    if cfg_res in Path(base_fn).resolve().parents:
                        lg.removeHandler(h)
                        h.close()
                except OSError:
                    pass


def reset_account_and_servers(cfg):
    """
    Выход из аккаунта лаунчера, очистка всех серверов и ПОЛНОЕ удаление папки конфигов botyaraMC
    (~/.config/botyaraMC на Linux, %APPDATA%\\botyaraMC на Windows, ~/Library/Application Support/botyaraMC на macOS).
    """
    d = config_dir(create=False)
    _close_config_log_handlers(d)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)

    keep_lang = cfg.get("language") if cfg.get("language") in ("ru", "en") else "ru"
    cfg.clear()
    cfg.update(DEFAULTS)
    cfg["language"] = keep_lang
    cfg["servers"] = []
    cfg["custom_jvm_presets"] = {}
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
    if cfg.get("isolation_mode") not in ("none", "family", "version"):
        cfg["isolation_mode"] = "none"
    if cfg.get("on_launch_action") not in ("keep", "minimize", "hide"):
        cfg["on_launch_action"] = "keep"
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
    if not server_id and fname != "manifest_cache.json":
        _write("manifest_cache.json", manifest)


def load_cache(server_id=None, host="", port=25456):
    """Читает кэш строго для указанного server_id (без утечки кэша от другого сервера!)."""
    fname = _cache_filename(host, port, server_id=server_id)
    data = _read(fname, None)
    if isinstance(data, dict) and "mc_version" in data:
        return data
    if server_id:
        return None
    data = _read("manifest_cache.json", None)
    return data if isinstance(data, dict) and "mc_version" in data else None
