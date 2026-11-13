"""Индекс модов и ресурспаков: SHA-256 с кэшем + скрытие (обфускация) имён модов."""
import hashlib
import hmac
import json
import threading
from pathlib import Path

import srv_config as C
from srv_config import MODS_DIR, RESOURCEPACKS_DIR

_ALIASES_FILE = Path(__file__).resolve().parent / ".hide_aliases.json"


def _load_alias_map():
    """Персистентная карта "mode:real_name" -> alias. Стабильна между запусками
    и при добавлении/удалении соседних модов (алиас не перетасовывается)."""
    try:
        data = json.loads(_ALIASES_FILE.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_alias_map(m):
    try:
        tmp = _ALIASES_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(_ALIASES_FILE)
    except OSError:
        pass


_cache = {}
_rp_cache = {}
_bg_cache = {}
_alias_to_path = {}
_lock = threading.Lock()

_BG_CANDIDATES = (
    ("background.png", "image/png"),
    ("background.jpg", "image/jpeg"),
    ("background.jpeg", "image/jpeg"),
    ("background.webp", "image/webp"),
)

_WORDS_A = (
    "silent", "cosmic", "velvet", "frosty", "golden", "shadow", "crimson", "cobalt",
    "emerald", "lunar", "solar", "mystic", "rapid", "vivid", "ancient", "crystal",
    "stormy", "gentle", "hidden", "bright", "fuzzy", "arctic", "blazing", "hollow",
    "mellow", "nimble", "polar", "rustic", "silver", "steady", "timber", "astral",
)
_WORDS_B = (
    "amber", "quartz", "onyx", "basalt", "copper", "nebula", "prism", "vortex",
    "cinder", "clover", "harbor", "meadow", "canyon", "glacier", "summit", "willow",
    "zenith", "aurora", "beacon", "comet", "echo", "fable", "granite", "horizon",
    "jasper", "lantern", "marble", "nectar", "orbit", "pebble", "ripple", "spark",
)
_WORDS_C = (
    "otter", "falcon", "badger", "lynx", "raven", "panda", "gecko", "heron",
    "koala", "lemur", "marten", "narwhal", "osprey", "puffin", "quokka", "robin",
    "salmon", "toucan", "urchin", "viper", "walrus", "yak", "zephyr", "bison",
    "condor", "ferret", "gopher", "iguana", "jackal", "kiwi", "magpie", "newt",
)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_alias(real_name, mode, salt, used):
    """Генерирует стабильное скрытое имя .jar без коллизий."""
    attempt = 0
    while True:
        msg = f"{real_name}#{attempt}".encode("utf-8")
        digest = hmac.new(salt.encode("utf-8"), msg, hashlib.sha256).digest()
        if mode == "hash":
            cand = f"mod_{digest[:8].hex()}.jar"
        else:  # words
            a = _WORDS_A[digest[0] % len(_WORDS_A)]
            b = _WORDS_B[digest[1] % len(_WORDS_B)]
            c = _WORDS_C[digest[2] % len(_WORDS_C)]
            num = (digest[3] % 90) + 10
            cand = f"{a}-{b}-{c}-{num}.jar"
        if cand.lower() not in used:
            used.add(cand.lower())
            return cand
        attempt += 1


def _should_hide(real_name, hide_mode, hide_list):
    if hide_mode == "none":
        return False
    if not hide_list:
        return True
    low = {x.lower() for x in hide_list}
    return real_name.lower() in low


def _files_to_hash(files, cache):
    """Выбирает файлы, чей (mtime_ns, size) изменился с прошлого скана, и снимает stat."""
    entries = []
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        key = (st.st_mtime_ns, st.st_size)
        if cache.get(p.name) is None or cache[p.name][0] != key:
            entries.append((p.name, key))
    return entries


def scan_mods(cfg=None):
    """Список {'name','sha256','size'} для всех .jar в mods/ (с учётом hide_mods)."""
    if cfg is None:
        cfg = C.load()
    hide_mode = cfg.get("hide_mods", "none")
    hide_list = cfg.get("hide_mods_list") or []
    salt = C.get_hide_salt()

    # Фаза 1 (под локом): снимок каталога + алиасы. SHA-256 считаем ПОСЛЕ,
    # чтобы хэширование сотен мегабайт не блокировало параллельные запросы.
    with _lock:
        MODS_DIR.mkdir(exist_ok=True)
        files = [p for p in sorted(MODS_DIR.glob("*.jar"))
                 if not p.name.startswith(".") and p.is_file() and not p.is_symlink()]
        # Сначала резервируем имена открытых модов, чтобы алиасы с ними не совпали
        used_names = {
            p.name.lower() for p in files if not _should_hide(p.name, hide_mode, hide_list)
        }

        # Стабильные алиасы: восстанавливаем сохранённые; новые генерим только для новых модов.
        alias_map = _load_alias_map()
        assigned = {}  # real_name -> alias
        for p in files:
            if _should_hide(p.name, hide_mode, hide_list):
                saved = alias_map.get(f"{hide_mode}:{p.name}")
                assigned_lower = {v.lower() for v in assigned.values()}
                if saved and saved.lower() not in used_names and saved.lower() not in assigned_lower:
                    assigned[p.name] = saved
                    used_names.add(saved.lower())
        for p in files:
            if _should_hide(p.name, hide_mode, hide_list) and p.name not in assigned:
                assigned[p.name] = _make_alias(p.name, hide_mode, salt, used_names)
        todo = _files_to_hash(files, _cache)

    # Фаза 2 (без лока): хэшируем только изменившиеся файлы
    hashed = {}
    for name, key in todo:
        p = MODS_DIR / name
        try:
            hashed[name] = (key, _sha256(p))
        except OSError:
            continue

    # Фаза 3 (под локом): публикуем кэши и результат
    result, seen, new_map = [], set(), {}
    with _lock:
        for p in files:
            try:
                st = p.stat()
                key = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
            cached = hashed.get(p.name) or _cache.get(p.name)
            if not cached or cached[0] != key:
                continue  # файл меняется прямо сейчас — подхватим на следующем скане
            _cache[p.name] = cached
            pub_name = assigned.get(p.name, p.name)
            new_map[pub_name] = p
            result.append({"name": pub_name, "sha256": cached[1], "size": st.st_size})
            seen.add(p.name)

        # Чистим карту алиасов от удалённых модов и сохраняем, если что-то изменилось
        alias_dirty = False
        live_keys = {f"{hide_mode}:{pn}" for pn in seen}
        for k in list(alias_map):
            if k.split(":", 1)[0] == hide_mode and k not in live_keys:
                del alias_map[k]
                alias_dirty = True
        for real_name, pub_name in assigned.items():
            if alias_map.get(f"{hide_mode}:{real_name}") != pub_name:
                alias_map[f"{hide_mode}:{real_name}"] = pub_name
                alias_dirty = True
        if alias_dirty:
            _save_alias_map(alias_map)

        for name in list(_cache):
            if name not in seen:
                del _cache[name]
        _alias_to_path.clear()
        _alias_to_path.update(new_map)
    # Сортируем выдачу по публичному имени, чтобы порядок не выдавал оригинал
    result.sort(key=lambda m: m["name"].lower())
    return result


def scan_real_mods():
    """Реальные имена модов на диске для логов консоли хоста."""
    MODS_DIR.mkdir(exist_ok=True)
    with _lock:
        files = [p for p in sorted(MODS_DIR.glob("*.jar"))
                 if not p.name.startswith(".") and p.is_file() and not p.is_symlink()]
        todo = _files_to_hash(files, _cache)
    hashed = {}
    for name, key in todo:
        try:
            hashed[name] = (key, _sha256(MODS_DIR / name))
        except OSError:
            continue
    out = {}
    with _lock:
        for p in files:
            cached = hashed.get(p.name) or _cache.get(p.name)
            try:
                st = p.stat()
                key = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
            if cached and cached[0] == key:
                _cache[p.name] = cached
                out[p.name] = cached[1]
    return out


def scan_resourcepacks():
    """Список {'name','sha256','size'} для всех .zip в папке resourcepacks/."""
    RESOURCEPACKS_DIR.mkdir(exist_ok=True)
    with _lock:
        files = [p for p in sorted(RESOURCEPACKS_DIR.glob("*.zip"))
                 if not p.name.startswith(".") and p.is_file() and not p.is_symlink()]
        todo = _files_to_hash(files, _rp_cache)
    hashed = {}
    for name, key in todo:
        try:
            hashed[name] = (key, _sha256(RESOURCEPACKS_DIR / name))
        except OSError:
            continue
    result, seen = [], set()
    with _lock:
        for p in files:
            cached = hashed.get(p.name) or _rp_cache.get(p.name)
            try:
                st = p.stat()
                key = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
            if cached and cached[0] == key:
                _rp_cache[p.name] = cached
                result.append({"name": p.name, "sha256": cached[1], "size": st.st_size})
                seen.add(p.name)
        for name in list(_rp_cache):
            if name not in seen:
                del _rp_cache[name]
    return result


def _is_safe_filename(name, ext):
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return False
    return name == Path(name).name and name.lower().endswith(ext)


def resolve_mod(name, cfg=None):
    """Безопасно превращает публичное имя мода из URL в реальный путь (с учётом hide_mods)."""
    if not _is_safe_filename(name, ".jar"):
        return None
    scan_mods(cfg)
    with _lock:
        p = _alias_to_path.get(name)
    return p if p is not None and p.is_file() else None


def resolve_resourcepack(name):
    """Безопасно превращает имя ресурспака из URL в путь к .zip."""
    if not _is_safe_filename(name, ".zip"):
        return None
    p = RESOURCEPACKS_DIR / name
    return p if p.is_file() else None


def resolve_background(cfg=None):
    """Возвращает (Path, mime_type) активного фона сервера или (None, None)."""
    if cfg is None:
        cfg = C.load()
    if not cfg.get("serve_background", True):
        return None, None
    base = C.BASE
    for fname, mime in _BG_CANDIDATES:
        p = base / fname
        if p.is_file():
            return p, mime
    return None, None


def scan_background(cfg=None):
    """Возвращает {'name', 'sha256', 'size'} для кастомного фона лаунчера или None."""
    p, _mime = resolve_background(cfg)
    if p is None:
        return None
    with _lock:
        try:
            st = p.stat()
            if st.st_size <= 0 or st.st_size > 25 * 1024 * 1024:
                return None
            key = (str(p), st.st_mtime_ns, st.st_size)
            cached = _bg_cache.get("bg")
            if not cached or cached[0] != key:
                cached = (key, _sha256(p))
                _bg_cache["bg"] = cached
            return {"name": p.name, "sha256": cached[1], "size": st.st_size}
        except OSError:
            return None


# Обратной совместимости больше нет: все вызовы идут по полным именам scan_mods / resolve_mod
