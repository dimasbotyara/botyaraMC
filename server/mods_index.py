"""Индекс модов: имена, размеры и SHA-256 (с кэшем по mtime+size)."""
import hashlib
import threading
from pathlib import Path

from srv_config import MODS_DIR

_cache = {}
_lock = threading.Lock()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan():
    """Список {'name','sha256','size'} для всех .jar в папке mods."""
    result, seen = [], set()
    with _lock:
        for p in sorted(MODS_DIR.glob("*.jar")):
            if p.name.startswith(".") or not p.is_file():
                continue
            try:
                st = p.stat()
                key = (st.st_mtime_ns, st.st_size)
                cached = _cache.get(p.name)
                if not cached or cached[0] != key:
                    cached = (key, _sha256(p))
                    _cache[p.name] = cached
                result.append({"name": p.name, "sha256": cached[1], "size": st.st_size})
                seen.add(p.name)
            except OSError:
                continue
        for name in list(_cache):
            if name not in seen:
                del _cache[name]
    return result


def resolve(name):
    """Безопасно превращает имя из URL в путь к файлу (никаких ../)."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    if name != Path(name).name or not name.lower().endswith(".jar"):
        return None
    p = MODS_DIR / name
    return p if p.is_file() else None
