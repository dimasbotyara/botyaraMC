"""Чтение/создание config.txt и папки mods для sync-сервера botyaraMC."""
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.txt"
MODS_DIR = BASE / "mods"

DEFAULTS = {
    "http_port": 25456,
    "discovery_port": 25457,
    "mc_version": "1.20.1",
    "loader": "fabric",
    "minecraft_server": "127.0.0.1",
    "minecraft_port": 25565,
}

DEFAULT_CONFIG = """\
# ===== botyaraMC sync-server: настройки =====
# Строки с # - комментарии. Формат: ключ = значение
# Файл перечитывается на лету (кроме портов - для них перезапусти сервер).

# TCP-порт, с которого клиенты качают моды
http_port = 25456

# UDP-порт автообнаружения (лаунчер кричит в сеть, сервер отзывается)
discovery_port = 25457

# Версия Minecraft, которую лаунчер запустит у всех
mc_version = 1.20.1

# Загрузчик: fabric / forge / none
# (версия загрузчика не учитывается - лаунчер берёт последнюю подходящую)
loader = fabric

# К какому Minecraft-серверу автоматически подключать игроков.
# ИЗМЕНИ на IP хоста в Radmin VPN (например 26.12.34.56)
minecraft_server = 127.0.0.1
minecraft_port = 25565
"""


def ensure_files():
    """Создаёт всё нужное при первом запуске. True - если config.txt создан только что."""
    MODS_DIR.mkdir(exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG, encoding="utf-8")
        return True
    return False


def load():
    cfg = dict(DEFAULTS)
    try:
        text = CONFIG_FILE.read_text(encoding="utf-8-sig")
    except OSError:
        return cfg
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip().lower()] = value.strip()
    for key in ("http_port", "discovery_port", "minecraft_port"):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    cfg["loader"] = str(cfg["loader"]).lower()
    if cfg["loader"] not in ("fabric", "forge", "none"):
        cfg["loader"] = "none"
    return cfg
