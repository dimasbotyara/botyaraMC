"""Чтение, сохранение и локализация (RU / EN) config.txt для sync-сервера botyaraMC."""
import os
import re
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.txt"
MODS_DIR = BASE / "mods"
RESOURCEPACKS_DIR = BASE / "resourcepacks"
SALT_FILE = BASE / ".hide_salt"

VALID_LOADERS = ("fabric", "forge", "neoforge", "quilt", "none")
VALID_LANGS = ("ru", "en")
_FOLDER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,47}$")
_DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?$")

DEFAULTS = {
    "language": "ru",               # ru | en
    "server_name": "botyaraMC",     # отображаемое имя сервера в лаунчере
    "client_folder": "",            # пусто = по настройкам клиента, либо имя подпапки сборки
    "http_port": 25456,
    "discovery_port": 25457,
    "rate_limit_per_min": 300,      # запросов в минуту с одного IP (0 = без лимита)
    "mc_version": "1.20.1",
    "loader": "fabric",
    "java_version": None,           # None = auto, либо число (8, 17, 21...)
    "hide_mods": "none",            # none | words | hash
    "hide_mods_list": [],           # список .jar через запятую (пусто = скрывать все)
    "delete_user_mods": False,      # убирать ли сторонние моды, добавленные игроком вручную
    "serve_background": True,       # раздавать ли background.png/.jpg/.webp как фон лаунчера
    "auto_join": True,              # автоматически заходить на MC-сервер при запуске игры
    "minecraft_server": "auto",     # auto | IP (26.x.x.x) | буквенный домен (play.example.com)
    "minecraft_port": 25565,
}


def sanitize_folder_name(raw):
    """Безопасное имя клиентской папки (без ../ и слэшей) или пустая строка."""
    s = str(raw or "").strip()
    if not s or s.lower() in ("default", "none", ".minecraft", "minecraft"):
        return ""
    if ".." in s or "/" in s or "\\" in s:
        return ""
    return s if _FOLDER_RE.fullmatch(s) else ""


def parse_mc_address(raw_host, fallback_port=25565):
    """
    Разбирает адрес Minecraft-сервера: поддерживает 'auto', IPv4, localhost,
    буквенные домены хостингов (в т.ч. IDN .рф) и необязательный ':порт'.
    Возвращает (normalized_host, port) или None при ошибке.
    """
    s = str(raw_host or "").strip().rstrip("/")
    for prefix in ("minecraft://", "http://", "https://"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    if not s:
        return "auto", int(fallback_port or 25565)
    if " " in s or "/" in s or "\\" in s:
        return None

    port = int(fallback_port or 25565)
    host = s
    if ":" in s:
        h_part, _, p_part = s.rpartition(":")
        if not p_part.isdigit() or not (1 <= int(p_part) <= 65535):
            return None
        host = h_part.strip()
        port = int(p_part)

    if not host:
        return None
    if host.lower() == "auto":
        return "auto", port
    if host.lower() == "localhost":
        return "localhost", port

    # Если строка состоит только из цифр и точек — проверяем строгий IPv4
    if re.fullmatch(r"[0-9.]+", host):
        octets = host.split(".")
        if len(octets) != 4 or any(not o.isdigit() or not (0 <= int(o) <= 255) for o in octets):
            return None
        return host, port

    # Буквенный домен хостинга (включая поддомены и IDN вида мойсервер.рф)
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None

    labels = ascii_host.split(".")
    if any(not _DOMAIN_LABEL_RE.fullmatch(lb) for lb in labels):
        return None
    if len(labels) == 1 and len(ascii_host) < 2:
        return None
    return host, port


def validate_mc_host(raw):
    """Проверка корректности хоста Minecraft-сервера (IP, буквенный домен или auto)."""
    s = str(raw or "").strip()
    if not s:
        return False
    return parse_mc_address(s) is not None


def _parse_bool(raw, default=False):
    if isinstance(raw, bool):
        return raw
    v = str(raw or "").strip().lower()
    if v in ("true", "1", "yes", "on", "да"):
        return True
    if v in ("false", "0", "no", "off", "нет"):
        return False
    return default


def _parse_hide_mode(raw):
    v = str(raw or "").strip().lower()
    if v in ("", "none", "false", "0", "off", "no"):
        return "none"
    if v in ("true", "1", "on", "yes", "words", "random"):
        return "words"
    if v in ("hash", "sha", "sha256", "hex"):
        return "hash"
    return "none"


def _parse_java_version(raw):
    if raw is None:
        return None
    v = str(raw).strip().lower()
    if v in ("", "auto", "none", "0", "default"):
        return None
    if v.startswith("1.") and v[2:].isdigit():
        return int(v[2:])
    if v.isdigit() and 6 <= int(v) <= 40:
        return int(v)
    return None


def render_config(cfg=None, lang=None):
    """Генерирует текст config.txt с комментариями на русском или английском языке."""
    c = dict(DEFAULTS)
    if cfg:
        c.update(cfg)
    lg = (lang or c.get("language") or "ru").lower()
    if lg not in VALID_LANGS:
        lg = "ru"

    java_val = str(c["java_version"]) if c.get("java_version") else "auto"
    hide_list_val = ", ".join(c.get("hide_mods_list") or [])
    del_mods_val = "true" if c.get("delete_user_mods") else "false"
    serve_bg_val = "true" if c.get("serve_background", True) else "false"
    auto_join_val = "true" if c.get("auto_join", True) else "false"
    folder_val = sanitize_folder_name(c.get("client_folder", ""))
    mc_srv_val = str(c.get("minecraft_server") or "auto").strip() or "auto"

    if lg == "en":
        return f"""\
# ===== botyaraMC sync-server configuration =====
# Lines starting with # are comments. Format: key = value
# Reloaded live on the fly (except ports — restart server.py after changing ports).
# Tip: run `python tui.py` for an interactive terminal configurator!

# Server language for logs & TUI: en / ru
language = en

# Display name of your server shown in players' launchers
server_name = {c['server_name']}

# Optional isolated client folder name (leave empty to follow player's folder setting,
# or set e.g. my_rpg_server to isolate mods/resourcepacks for this server)
client_folder = {folder_val}

# HTTP TCP port (serving manifest, mods & resourcepacks) and UDP discovery port
http_port = {c['http_port']}
discovery_port = {c['discovery_port']}

# Per-IP HTTP rate limit (requests per minute; generous for big modpacks, 0 = disabled)
rate_limit_per_min = {c['rate_limit_per_min']}

# Target Minecraft version & mod loader (fabric / forge / neoforge / quilt / none)
mc_version = {c['mc_version']}
loader = {c['loader']}

# Required Java major version: auto (detected from MC version) or number (8, 17, 21)
java_version = {java_val}

# Server-side mod filename cloaking:
#   none  - keep original .jar filenames
#   words - random word slugs (e.g. silent-amber-otter-42.jar)
#   hash  - salted cryptographic hash (e.g. mod_7f3a9c12e4b08d51.jar)
hide_mods = {c['hide_mods']}

# Comma-separated .jar names to cloak selectively (leave empty to cloak ALL mods when hide_mods != none)
hide_mods_list = {hide_list_val}

# Move unmanaged custom mods added manually by players to mods/old-mods/ (true = strict modpack, false = keep)
delete_user_mods = {del_mods_val}

# Serve custom launcher background if background.png / background.jpg / background.webp exists in server folder
serve_background = {serve_bg_val}

# Automatically connect players straight into the Minecraft server upon game launch
# minecraft_server accepts:
#   auto             - connect to the exact same IP/domain used for mod sync (best for LAN / Radmin VPN)
#   26.12.34.56      - explicit numeric IPv4 address
#   play.example.com - alphabetic domain name (e.g. external Minecraft hosting)
auto_join = {auto_join_val}
minecraft_server = {mc_srv_val}
minecraft_port = {c['minecraft_port']}
"""

    return f"""\
# ===== botyaraMC sync-server: настройки =====
# Строки с # - комментарии. Формат: ключ = значение
# Файл перечитывается на лету (кроме портов - для них перезапусти server.py).
# Совет: запусти `python tui.py` для удобной интерактивной настройки в терминале!

# Язык сервера и настроек: ru / en
language = ru

# Название сервера (отображается у игроков в лаунчере)
server_name = {c['server_name']}

# Имя отдельной папки сборки у клиентов (оставь пустым для режима игрока,
# либо укажи например my_rpg_pack для собственной изолированной папки сервера)
client_folder = {folder_val}

# TCP-порт раздачи файлов и UDP-порт автообнаружения в сети
http_port = {c['http_port']}
discovery_port = {c['discovery_port']}

# Лимит запросов с одного IP в минуту (достаточно большой для сборок, 0 = выключен)
rate_limit_per_min = {c['rate_limit_per_min']}

# Версия Minecraft и загрузчик (fabric / forge / neoforge / quilt / none)
mc_version = {c['mc_version']}
loader = {c['loader']}

# Требуемая версия Java: auto (по версии MC) или число (8, 17, 21)
java_version = {java_val}

# Скрытие настоящих названий модов у клиентов:
#   none  - обычные имена файлов
#   words - случайные слова (например silent-amber-otter-42.jar)
#   hash  - криптохэш с солью (например mod_7f3a9c12e4b08d51.jar)
hide_mods = {c['hide_mods']}

# Если нужно скрыть ТОЛЬКО отдельные моды - перечисли через запятую (пусто = скрывать все)
hide_mods_list = {hide_list_val}

# Убирать ли сторонние моды игрока в mods/old-mods/ (true = строгая сборка, false = не трогать)
delete_user_mods = {del_mods_val}

# Раздавать ли кастомный фон лаунчера, если в папке сервера лежит background.png / .jpg / .webp
serve_background = {serve_bg_val}

# Автоматически подключать игроков к Minecraft-серверу сразу после запуска игры
# minecraft_server поддерживает:
#   auto             - заходить по тому же адресу, откуда скачаны моды (идеально для LAN и Radmin VPN)
#   26.12.34.56      - конкретный цифровой IP-адрес
#   play.example.com - буквенный домен хостинга
auto_join = {auto_join_val}
minecraft_server = {mc_srv_val}
minecraft_port = {c['minecraft_port']}
"""


def save(cfg, lang=None):
    """Атомарно сохраняет словарь настроек в config.txt на выбранном языке."""
    MODS_DIR.mkdir(exist_ok=True)
    RESOURCEPACKS_DIR.mkdir(exist_ok=True)
    if lang in ("ru", "en"):
        cfg["language"] = lang
    text = render_config(cfg, lang=cfg.get("language", "ru"))
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)


def ensure_files(lang="ru"):
    """Создаёт всё нужное при первом запуске. True - если config.txt создан только что."""
    MODS_DIR.mkdir(exist_ok=True)
    RESOURCEPACKS_DIR.mkdir(exist_ok=True)
    get_hide_salt()
    if not CONFIG_FILE.exists():
        init_cfg = dict(DEFAULTS, language=(lang if lang in VALID_LANGS else "ru"))
        CONFIG_FILE.write_text(render_config(init_cfg, lang=init_cfg["language"]), encoding="utf-8")
        return True
    return False


def get_hide_salt():
    """Стабильная секретная соль сервера для обфускации имён модов."""
    try:
        if SALT_FILE.is_file():
            val = SALT_FILE.read_text(encoding="utf-8").strip()
            if len(val) >= 16:
                return val
    except OSError:
        pass
    val = secrets.token_hex(16)
    try:
        SALT_FILE.write_text(val + "\n", encoding="utf-8")
    except OSError:
        pass
    return val


def load():
    cfg = dict(DEFAULTS)
    cfg["hide_mods_list"] = []
    raw = {}
    try:
        text = CONFIG_FILE.read_text(encoding="utf-8-sig")
    except OSError:
        return cfg
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key.strip().lower()] = value.strip()

    lang = str(raw.get("language", DEFAULTS["language"])).strip().lower()
    cfg["language"] = lang if lang in VALID_LANGS else "ru"

    sname = str(raw.get("server_name", DEFAULTS["server_name"])).strip()
    cfg["server_name"] = sname[:64] if sname else "botyaraMC"
    cfg["client_folder"] = sanitize_folder_name(raw.get("client_folder", ""))

    for key in ("http_port", "discovery_port", "minecraft_port", "rate_limit_per_min"):
        try:
            cfg[key] = max(0, int(raw.get(key, DEFAULTS[key])))
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]

    cfg["mc_version"] = str(raw.get("mc_version", DEFAULTS["mc_version"])).strip() or DEFAULTS["mc_version"]
    cfg["loader"] = str(raw.get("loader", DEFAULTS["loader"])).strip().lower()
    if cfg["loader"] not in VALID_LOADERS:
        cfg["loader"] = "none"

    cfg["java_version"] = _parse_java_version(raw.get("java_version", "auto"))
    cfg["hide_mods"] = _parse_hide_mode(raw.get("hide_mods", "none"))
    raw_list = raw.get("hide_mods_list", "")
    if isinstance(raw_list, str) and raw_list.strip():
        cfg["hide_mods_list"] = [x.strip() for x in raw_list.split(",") if x.strip()]
    else:
        cfg["hide_mods_list"] = []

    cfg["delete_user_mods"] = _parse_bool(raw.get("delete_user_mods"), False)
    cfg["serve_background"] = _parse_bool(raw.get("serve_background"), True)
    cfg["auto_join"] = _parse_bool(raw.get("auto_join"), True)

    raw_mc_srv = str(raw.get("minecraft_server", DEFAULTS["minecraft_server"])).strip()
    parsed_mc = parse_mc_address(raw_mc_srv, fallback_port=cfg["minecraft_port"])
    if parsed_mc is not None:
        cfg["minecraft_server"] = parsed_mc[0]
        if ":" in raw_mc_srv and "minecraft_port" not in raw:
            cfg["minecraft_port"] = parsed_mc[1]
    else:
        cfg["minecraft_server"] = raw_mc_srv or "auto"
    return cfg
