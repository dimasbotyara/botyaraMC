"""Синхронизация модов и ресурспаков: расчёт размера, докачка (.part + HTTP Range) и SHA-256."""
import hashlib
import json
import logging
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import config as cfgmod

log = logging.getLogger("botyaraMC.sync")
TIMEOUT = 12
MAX_RETRIES = 3

_hash_cache = {}  # (resolved_str, mtime_ns, size) -> sha256


def _safe_name(name, ext=".jar"):
    return (
        isinstance(name, str)
        and bool(name)
        and name == os.path.basename(name)
        and "/" not in name
        and "\\" not in name
        and name.lower().endswith(ext)
        and not name.startswith(".")
    )


def _base(host, port):
    return f"http://{host}:{port}"


def format_size(num_bytes):
    """Человекочитаемый размер: '45 МБ', '12.4 МБ', '820 КБ'."""
    b = max(0, int(num_bytes or 0))
    if b == 0:
        return "0 Б"
    if b < 1024:
        return f"{b} Б"
    if b < 1024 * 1024:
        kb = b / 1024
        return f"{kb:.1f} КБ".replace(".0 ", " ") if kb < 10 else f"{round(kb)} КБ"
    if b < 1024 ** 3:
        mb = b / (1024 * 1024)
        if mb >= 100:
            return f"{round(mb)} МБ"
        return f"{mb:.1f} МБ".replace(".0 ", " ")
    gb = b / (1024 ** 3)
    return f"{gb:.2f} ГБ".replace(".00 ", " ")


def fetch_manifest(host, port):
    with urllib.request.urlopen(_base(host, port) + "/manifest", timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("app") != "botyaraMC":
        raise ValueError("это не botyaraMC-сервер")
    data["mods"] = [
        {"name": m["name"], "sha256": str(m["sha256"]).lower(), "size": max(0, int(m.get("size", 0)))}
        for m in data.get("mods", [])
        if _safe_name(m.get("name"), ".jar") and m.get("sha256")
    ]
    data["resourcepacks"] = [
        {"name": rp["name"], "sha256": str(rp["sha256"]).lower(), "size": max(0, int(rp.get("size", 0)))}
        for rp in data.get("resourcepacks", [])
        if _safe_name(rp.get("name"), ".zip") and rp.get("sha256")
    ]
    jv = data.get("java_version")
    data["java_version"] = int(jv) if isinstance(jv, int) or (isinstance(jv, str) and jv.isdigit()) else None
    data["mods_hidden"] = bool(data.get("mods_hidden", False))
    return data


def file_sha256(path):
    p = Path(path)
    try:
        st = p.stat()
        key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
        if key in _hash_cache:
            return _hash_cache[key]
    except OSError:
        key = None

    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if key is not None:
        if len(_hash_cache) > 2048:
            _hash_cache.clear()
        _hash_cache[key] = digest
    return digest


def _part_paths(dst):
    tmp = Path(str(dst) + ".part")
    meta = Path(str(dst) + ".part.sha256")
    return tmp, meta


def _valid_part_bytes(dst, expected_sha256, expected_size):
    """Сколько байт уже скачано в .part для этого конкретного SHA-256."""
    tmp, meta = _part_paths(dst)
    try:
        if not tmp.is_file() or not meta.is_file():
            return 0
        if meta.read_text("utf-8").strip().lower() != expected_sha256.lower():
            return 0
        sz = tmp.stat().st_size
        if expected_size > 0 and sz > expected_size:
            return 0
        return sz
    except OSError:
        return 0


def _cleanup_part(dst):
    tmp, meta = _part_paths(dst)
    for p in (tmp, meta):
        try:
            p.unlink()
        except OSError:
            pass


# --- помним, какие моды поставили МЫ, чтобы не трогать чужие ---
def _managed_load(target):
    data = cfgmod._read("managed.json", {})
    return set(data.get(str(Path(target).resolve()), []))


def _managed_save(target, names):
    data = cfgmod._read("managed.json", {})
    data[str(Path(target).resolve())] = sorted(names)
    cfgmod._write("managed.json", data)


def _local_sha_index(targets):
    """Находит уже лежащие локально .jar по их SHA-256 (позволяет не перекачивать при переключении hide_mods)."""
    by_sha = {}
    for t in targets:
        t = Path(t)
        if not t.is_dir():
            continue
        for p in t.glob("*.jar"):
            if p.is_file() and not p.name.startswith("."):
                try:
                    by_sha.setdefault(file_sha256(p), p)
                except OSError:
                    continue
    return by_sha


def plan_sync(manifest, mc_dir, is_host=False, server_mods_dir=""):
    """
    Считает, сколько байт реально нужно докачать по сети (с учётом локальных файлов и .part).
    Возвращает словарь: {'total_bytes', 'mods_count', 'rp_count', 'total_files'}.
    """
    mc_dir = Path(mc_dir)
    mod_targets = [mc_dir / "mods"]
    if is_host and server_mods_dir:
        mod_targets.append(Path(server_mods_dir))

    local_by_sha = _local_sha_index(mod_targets)
    total_bytes = 0
    mods_to_dl = 0
    rp_to_dl = 0

    seen_mod_shas = set()
    for m in manifest.get("mods", []):
        sha = m["sha256"]
        size = max(0, int(m.get("size", 0)))
        name = m["name"]
        # Если такой мод по хэшу уже есть локально или уже учтён в плане загрузки — по сети качать не надо
        if sha in local_by_sha or sha in seen_mod_shas:
            continue
        # Проверяем, есть ли уже точный файл в одной из папок назначения
        already = False
        best_part = 0
        for t in mod_targets:
            dst = t / name
            if dst.is_file():
                try:
                    if file_sha256(dst) == sha:
                        already = True
                        break
                except OSError:
                    pass
            best_part = max(best_part, _valid_part_bytes(dst, sha, size))
        if not already:
            seen_mod_shas.add(sha)
            mods_to_dl += 1
            total_bytes += max(0, size - best_part)

    rp_dir = mc_dir / "resourcepacks"
    for rp in manifest.get("resourcepacks", []):
        dst = rp_dir / rp["name"]
        # Ресурспаки пользователей НЕ трогаем: качаем только отсутствующие!
        if dst.exists():
            continue
        size = max(0, int(rp.get("size", 0)))
        part = _valid_part_bytes(dst, rp["sha256"], size)
        rp_to_dl += 1
        total_bytes += max(0, size - part)

    return {
        "total_bytes": total_bytes,
        "mods_count": mods_to_dl,
        "rp_count": rp_to_dl,
        "total_files": mods_to_dl + rp_to_dl,
    }


def _download_resumable(url, expected_sha, expected_size, dst, on_bytes=None):
    """Скачивает файл в dst.part с поддержкой докачки по HTTP Range и проверкой SHA-256."""
    tmp, meta = _part_paths(dst)
    expected_sha = expected_sha.lower()

    # Если остался .part от другой версии файла — сбрасываем
    if _valid_part_bytes(dst, expected_sha, expected_size) == 0 and tmp.exists():
        _cleanup_part(dst)
    meta.write_text(expected_sha + "\n", encoding="utf-8")

    # Возможно, .part уже докачался целиком в прошлый раз
    if expected_size > 0 and tmp.is_file() and tmp.stat().st_size == expected_size:
        if file_sha256(tmp) == expected_sha:
            return tmp
        _cleanup_part(dst)
        meta.write_text(expected_sha + "\n", encoding="utf-8")

    last_err = None
    for attempt in range(MAX_RETRIES):
        resume_from = tmp.stat().st_size if tmp.is_file() else 0
        if expected_size > 0 and resume_from > expected_size:
            _cleanup_part(dst)
            meta.write_text(expected_sha + "\n", encoding="utf-8")
            resume_from = 0

        headers = {"User-Agent": "botyaraMC/2.0"}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                status = getattr(resp, "status", 200)
                h = hashlib.sha256()
                if status == 206 and resume_from > 0 and tmp.is_file():
                    with open(tmp, "rb") as rf:
                        for chunk in iter(lambda: rf.read(1 << 20), b""):
                            h.update(chunk)
                    mode = "ab"
                else:
                    resume_from = 0
                    mode = "wb"

                content_len = resp.headers.get("Content-Length")
                expected_chunk_total = int(content_len) if (content_len and content_len.isdigit()) else None
                read_now = 0

                with open(tmp, mode) as f:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                        h.update(chunk)
                        read_now += len(chunk)
                        if on_bytes:
                            on_bytes(len(chunk))

            cur_size = tmp.stat().st_size if tmp.is_file() else 0
            if (expected_chunk_total is not None and read_now < expected_chunk_total) or (
                expected_size > 0 and cur_size < expected_size
            ):
                # Обрыв соединения посреди потока: сохраняем .part для докачки!
                raise OSError(f"загрузка прервана ({cur_size}/{expected_size} байт)")

            if h.hexdigest() != expected_sha:
                _cleanup_part(dst)
                raise ValueError(f"хэш не сошёлся: {dst.name}")
            return tmp

        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 416:
                # Диапазон не подошёл — сбрасываем .part и качаем заново
                _cleanup_part(dst)
                meta.write_text(expected_sha + "\n", encoding="utf-8")
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Важно: НЕ удаляем tmp (.part), чтобы докачать с места обрыва!
            last_err = e
            if attempt + 1 < MAX_RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise

    if last_err:
        raise last_err
    return tmp


def sync(host, port, mods, targets, on_progress=None, on_bytes=None):
    """Синхронизирует моды во все папки targets (с докачкой и переиспользованием по SHA-256)."""
    wanted = {m["name"]: m for m in mods}
    total = max(1, len(wanted) * max(1, len(targets)))
    done, all_ok = 0, True
    good = _local_sha_index(targets)  # sha256 -> Path существующего файла

    for target in targets:
        target = Path(target)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.exception("нет доступа к %s", target)
            all_ok = False
            continue
        managed = _managed_load(target)
        keep = set()

        for name, m in wanted.items():
            dst = target / name
            sha = m["sha256"]
            size = int(m.get("size", 0))
            try:
                if dst.is_file() and file_sha256(dst) == sha:
                    good.setdefault(sha, dst)
                    _cleanup_part(dst)
                elif sha in good and good[sha].is_file() and file_sha256(good[sha]) == sha:
                    tmp, _ = _part_paths(dst)
                    shutil.copyfile(good[sha], tmp)
                    os.replace(tmp, dst)
                    _cleanup_part(dst)
                    good[sha] = dst
                    log.info("скопирован локально по SHA-256 -> %s", dst)
                else:
                    url = f"{_base(host, port)}/mods/{urllib.parse.quote(name)}"
                    tmp = _download_resumable(url, sha, size, dst, on_bytes=on_bytes)
                    os.replace(tmp, dst)
                    _cleanup_part(dst)
                    good[sha] = dst
                    log.info("обновлён мод %s -> %s", name, target)
            except Exception:
                log.exception("не удалось синхронизировать мод %s в %s", name, target)
                all_ok = False
            if dst.exists():
                keep.add(name)
            done += 1
            if on_progress:
                on_progress(done / total)

        for name in managed - set(wanted):  # на сервере этого мода (или старого алиаса) больше нет
            try:
                (target / name).unlink()
                _cleanup_part(target / name)
                log.info("удалён мод %s из %s", name, target)
            except FileNotFoundError:
                _cleanup_part(target / name)
            except OSError:
                log.exception("не удалось удалить %s", name)
                keep.add(name)
        _managed_save(target, keep)
    return all_ok


def sync_resourcepacks(host, port, resourcepacks, rp_dir, on_progress=None, on_bytes=None):
    """
    Синхронизирует ресурспаки ТОЛЬКО добавлением новых.
    Существующие ресурспаки пользователя не перезаписываются и никогда не удаляются!
    """
    if not resourcepacks:
        if on_progress:
            on_progress(1.0)
        return True

    rp_dir = Path(rp_dir)
    try:
        rp_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.exception("нет доступа к папке ресурспаков %s", rp_dir)
        return False

    all_ok = True
    total = max(1, len(resourcepacks))
    for idx, rp in enumerate(resourcepacks, 1):
        name = rp["name"]
        dst = rp_dir / name
        if dst.exists():
            if on_progress:
                on_progress(idx / total)
            continue
        try:
            url = f"{_base(host, port)}/resourcepacks/{urllib.parse.quote(name)}"
            tmp = _download_resumable(url, rp["sha256"], int(rp.get("size", 0)), dst, on_bytes=on_bytes)
            os.replace(tmp, dst)
            _cleanup_part(dst)
            log.info("добавлен ресурспак %s -> %s", name, rp_dir)
        except Exception:
            log.exception("не удалось скачать ресурспак %s", name)
            all_ok = False
        if on_progress:
            on_progress(idx / total)
    return all_ok


def sync_all(host, port, manifest, mc_dir, is_host=False, server_mods_dir="",
             on_progress=None, on_status=None):
    """Полная синхронизация модов и ресурспаков с прогрессом в мегабайтах."""
    mc_dir = Path(mc_dir)
    plan = plan_sync(manifest, mc_dir, is_host=is_host, server_mods_dir=server_mods_dir)
    need_bytes = plan["total_bytes"]
    got_bytes = [0]

    def _on_bytes(n):
        got_bytes[0] += n
        if need_bytes > 0:
            frac = min(1.0, got_bytes[0] / need_bytes)
            if on_progress:
                on_progress(frac)
            if on_status:
                on_status(
                    f"Скачиваем файлы: {format_size(min(got_bytes[0], need_bytes))} / {format_size(need_bytes)} 📥"
                )

    targets = [mc_dir / "mods"]
    if is_host and server_mods_dir:
        targets.append(Path(server_mods_dir))

    mods_prog = (None if need_bytes > 0 else
                 (lambda f: on_progress(f * 0.8) if on_progress else None))
    rp_prog = (None if need_bytes > 0 else
               (lambda f: on_progress(0.8 + f * 0.2) if on_progress else None))

    ok_mods = sync(host, port, manifest.get("mods", []), targets,
                   on_progress=mods_prog, on_bytes=_on_bytes)
    ok_rp = sync_resourcepacks(host, port, manifest.get("resourcepacks", []),
                               mc_dir / "resourcepacks",
                               on_progress=rp_prog, on_bytes=_on_bytes)
    if on_progress:
        on_progress(1.0)
    return ok_mods and ok_rp
