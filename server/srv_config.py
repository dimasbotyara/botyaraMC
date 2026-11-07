"""Чтение/создание config.txt и папок mods / resourcepacks для sync-сервера botyaraMC."""
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.txt"
MODS_DIR = BASE / "mods"
RESOURCEPACKS_DIR = BASE / "resourcepacks"
SALT_FILE = BASE / ".hide_salt"

VALID_LOADERS = ("fabric", "forge", "neoforge", "quilt", "none")

DEFAULTS = {
    "http_port": 25456,
    "discovery_port": 25457,
    "mc_version": "1.20.1",
    "loader": "fabric",
    "minecraft_server": "127.0.0.1",
    "minecraft_port": 25565,
    "java_version": None,       # None = авто, либо мажорная версия (8, 17, 21...)
    "hide_mods": "none",        # none | words | hash
    "hide_mods_list": [],       # пусто = скрывать все моды (при включённом hide_mods)
}

DEFAULT_CONFIG = """\
# ===== botyaraMC sync-server: настройки =====
# Строки с # - комментарии. Формат: ключ = значение
# Файл перечитывается на лету (кроме портов - для них перезапусти сервер).

# TCP-порт, с которого клиенты качают моды и ресурспаки
http_port = 25456

# UDP-порт автообнаружения (лаунчер кричит в сеть, сервер отзывается)
discovery_port = 25457

# Версия Minecraft, которую лаунчер запустит у всех
mc_version = 1.20.1

# Загрузчик: fabric / forge / neoforge / quilt / none
# (версия загрузчика не учитывается - лаунчер берёт последнюю подходящую)
loader = fabric

# Требуемая мажорная версия Java: auto (определится по версии MC) или число (8, 17, 21)
java_version = auto

# Скрытие настоящих названий модов у клиентов:
#   none  - обычные имена файлов (как лежат в mods/)
#   words - случайные красивые слова (например silent-amber-otter-42.jar)
#   hash  - криптохэш (например mod_7f3a9c12e4b08d51.jar)
hide_mods = none

# Если нужно скрыть ТОЛЬКО отдельные моды - перечисли их через запятую
# (если оставить пустым при включённом hide_mods, скроются ВСЕ моды):
# hide_mods_list = secret_mod.jar, anticheat.jar
hide_mods_list =

# К какому Minecraft-серверу автоматически подключать игроков.
# ИЗМЕНИ на IP хоста в Radmin VPN (например 26.12.34.56)
minecraft_server = 127.0.0.1
minecraft_port = 25565
"""


def ensure_files():
    """Создаёт всё нужное при первом запуске. True - если config.txt создан только что."""
    MODS_DIR.mkdir(exist_ok=True)
    RESOURCEPACKS_DIR.mkdir(exist_ok=True)
    get_hide_salt()
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG, encoding="utf-8")
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
    v = str(raw or "").strip().lower()
    if v in ("", "auto", "none", "0", "default"):
        return None
    if v.startswith("1.") and v[2:].isdigit():  # например 1.8 -> 8
        return int(v[2:])
    if v.isdigit() and 6 <= int(v) <= 40:
        return int(v)
    return None


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

    cfg.update(raw)
    for key in ("http_port", "discovery_port", "minecraft_port"):
        try:
            cfg[key] = int(raw.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]

    cfg["loader"] = str(raw.get("loader", DEFAULTS["loader"])).lower()
    if cfg["loader"] not in VALID_LOADERS:
        cfg["loader"] = "none"

    cfg["java_version"] = _parse_java_version(raw.get("java_version", "auto"))
    cfg["hide_mods"] = _parse_hide_mode(raw.get("hide_mods", "none"))
    raw_list = raw.get("hide_mods_list", "")
    if isinstance(raw_list, str) and raw_list.strip():
        cfg["hide_mods_list"] = [x.strip() for x in raw_list.split(",") if x.strip()]
    else:
        cfg["hide_mods_list"] = []
    return cfg
