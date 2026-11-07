"""Синхронизация модов и ресурспаков: old-mods, кэш mods/botyaraMC, Range-докачка и SHA-256."""
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
import i18n

log = logging.getLogger("botyaraMC.sync")
TIMEOUT = 12
MAX_RETRIES = 4

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


def format_size(num_bytes, lang="ru"):
    """Человекочитаемый размер: '45 МБ' / '45 MB'."""
    b = max(0, int(num_bytes or 0))
    u_b, u_kb, u_mb, u_gb = ("B", "KB", "MB", "GB") if lang == "en" else ("Б", "КБ", "МБ", "ГБ")
    if b == 0:
        return f"0 {u_b}"
    if b < 1024:
        return f"{b} {u_b}"
    if b < 1024 * 1024:
        kb = b / 1024
        return f"{kb:.1f} {u_kb}".replace(".0 ", " ") if kb < 10 else f"{round(kb)} {u_kb}"
    if b < 1024 ** 3:
        mb = b / (1024 * 1024)
        if mb >= 100:
            return f"{round(mb)} {u_mb}"
        return f"{mb:.1f} {u_mb}".replace(".0 ", " ")
    gb = b / (1024 ** 3)
    return f"{gb:.2f} {u_gb}".replace(".00 ", " ")


def fetch_manifest(host, port):
    url = _base(host, port) + "/manifest"
    req = urllib.request.Request(url, headers={"User-Agent": "botyaraMC"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                wait = min(8.0, float(e.headers.get("Retry-After") or 2.0))
                time.sleep(wait)
                continue
            raise

    if data.get("app") != "botyaraMC":
        raise ValueError("not a botyaraMC server")

    data["server_name"] = str(data.get("server_name") or "").strip()[:64]
    data["client_folder"] = cfgmod.sanitize_client_folder(data.get("client_folder", ""))
    data["delete_user_mods"] = bool(data.get("delete_user_mods", False))

    srv = data.get("server") if isinstance(data.get("server"), dict) else {}
    data["server"] = {
        "host": str(srv.get("host") or "").strip(),
        "port": int(srv.get("port") or 25565),
        "auto_join": bool(srv.get("auto_join", True)),
    }

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
        if len(_hash_cache) > 4096:
            _hash_cache.clear()
        _hash_cache[key] = digest
    return digest


def _part_paths(dst):
    tmp = Path(str(dst) + ".part")
    meta = Path(str(dst) + ".part.sha256")
    return tmp, meta


def _valid_part_bytes(dst, expected_sha256, expected_size):
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


# --- учёт модов, поставленных именно botyaraMC ---
def _managed_state(target):
    """Возвращает (was_initialized: bool, managed_set: set[str])."""
    data = cfgmod._read("managed.json", {})
    key = str(Path(target).resolve())
    if key not in data:
        return False, set()
    return True, set(data.get(key, []))


def _managed_save(target, names):
    data = cfgmod._read("managed.json", {})
    data[str(Path(target).resolve())] = sorted(names)
    cfgmod._write("managed.json", data)


def _move_unique(src, dest_dir, preferred_name=None):
    """Аккуратно переносит файл или папку в dest_dir, не перезаписывая существующий элемент."""
    src = Path(src)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = preferred_name or src.name
    cand = dest_dir / name
    if cand.exists():
        if src.is_file() and cand.is_file():
            try:
                if file_sha256(cand) == file_sha256(src):
                    src.unlink()
                    return cand
            except OSError:
                pass
        stem = Path(name).stem if src.is_file() else name
        ext = Path(name).suffix if src.is_file() else ""
        i = 1
        while True:
            cand = dest_dir / f"{stem}_{i}{ext}"
            if not cand.exists():
                break
            i += 1
    shutil.move(str(src), str(cand))
    return cand


def _stash_mod(src, stash_dir):
    """Прячет временно ненужный мод botyaraMC в mods/botyaraMC/ (с защитой разных версий по хэшу)."""
    stash_dir = Path(stash_dir)
    stash_dir.mkdir(parents=True, exist_ok=True)
    cand = stash_dir / src.name
    if cand.is_file():
        try:
            src_sha = file_sha256(src)
            if file_sha256(cand) == src_sha:
                src.unlink()
                return cand
            cand = stash_dir / f"{src.stem}_{src_sha[:8]}{src.suffix}"
            if cand.is_file():
                src.unlink()
                return cand
        except OSError:
            pass
    shutil.move(str(src), str(cand))
    return cand


def _local_sha_index(targets):
    """Индексирует по SHA-256 все доступные локально .jar (включая кэш mods/botyaraMC и old-mods)."""
    by_sha = {}
    scan_dirs = []
    for t in targets:
        t = Path(t)
        scan_dirs.append(t)
        scan_dirs.append(t / "botyaraMC")
        scan_dirs.append(t / "old-mods")
    for d in scan_dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.jar"):
            if p.is_file() and not p.name.startswith("."):
                try:
                    by_sha.setdefault(file_sha256(p), p)
                except OSError:
                    continue
    return by_sha


def plan_sync(manifest, mc_dir, is_host=False, server_mods_dir=""):
    """
    Считает, сколько байт реально нужно докачать по сети
    (с учётом активных модов, запаса в mods/botyaraMC и .part).
    """
    game_dir = cfgmod.resolve_game_dir(mc_dir, manifest.get("client_folder", ""))
    mod_targets = [game_dir / "mods"]
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
        if sha in local_by_sha or sha in seen_mod_shas:
            continue
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

    rp_dir = game_dir / "resourcepacks"
    for rp in manifest.get("resourcepacks", []):
        dst = rp_dir / rp["name"]
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
    """Скачивает файл в dst.part с поддержкой HTTP Range (206), Retry-After (429) и проверкой SHA-256."""
    tmp, meta = _part_paths(dst)
    expected_sha = expected_sha.lower()

    if _valid_part_bytes(dst, expected_sha, expected_size) == 0 and tmp.exists():
        _cleanup_part(dst)
    meta.write_text(expected_sha + "\n", encoding="utf-8")

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

        headers = {"User-Agent": "botyaraMC"}
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
                raise OSError(f"stream interrupted ({cur_size}/{expected_size} bytes)")

            if h.hexdigest() != expected_sha:
                _cleanup_part(dst)
                raise ValueError(f"SHA-256 mismatch: {dst.name}")
            return tmp

        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 416:
                _cleanup_part(dst)
                meta.write_text(expected_sha + "\n", encoding="utf-8")
                continue
            if e.code == 429 and attempt + 1 < MAX_RETRIES:
                wait = min(10.0, float(e.headers.get("Retry-After") or (1.5 * (attempt + 1))))
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt + 1 < MAX_RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise

    if last_err:
        raise last_err
    return tmp


def sync(host, port, mods, targets, on_progress=None, on_bytes=None,
         delete_user_mods=False, client_targets=None):
    """
    Синхронизирует моды во все папки targets:
    - Если папка клиента не пустая и ранее не управлялась botyaraMC -> переносит всё былое в mods/old-mods/.
    - Временно ненужные моды botyaraMC (от других серверов) складывает в mods/botyaraMC/ вместо удаления.
    - При delete_user_mods=True удаляет моды, добавленные игроком вручную позже.
    """
    wanted = {m["name"]: m for m in mods}
    total = max(1, len(wanted) * max(1, len(targets)))
    done, all_ok = 0, True

    client_resolved = (
        {Path(p).resolve() for p in client_targets}
        if client_targets is not None
        else {Path(targets[0]).resolve()} if targets else set()
    )

    # 1. На клиентской папке при первом знакомстве убираем всё прежнее содержимое в old-mods/
    for target in targets:
        target = Path(target)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        is_client = target.resolve() in client_resolved
        was_init, managed = _managed_state(target)
        if is_client and not was_init:
            existing_entries = [
                p for p in sorted(target.iterdir())
                if p.name not in ("old-mods", "botyaraMC")
                and not p.name.endswith(".part")
                and not p.name.endswith(".part.sha256")
            ]
            if existing_entries:
                old_dir = target / "old-mods"
                old_dir.mkdir(parents=True, exist_ok=True)
                for entry_p in existing_entries:
                    try:
                        _move_unique(entry_p, old_dir)
                        log.info("перенесён элемент %s -> %s", entry_p.name, old_dir)
                    except OSError:
                        log.exception("не удалось перенести %s в old-mods", entry_p)
            # Создаём резервную папку botyaraMC для переключения между серверами
            (target / "botyaraMC").mkdir(parents=True, exist_ok=True)
            _managed_save(target, set())

    good = _local_sha_index(targets)  # sha256 -> Path существующего локально файла

    for target in targets:
        target = Path(target)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.exception("нет доступа к %s", target)
            all_ok = False
            continue

        is_client = target.resolve() in client_resolved
        stash_dir = target / "botyaraMC"
        if is_client:
            stash_dir.mkdir(parents=True, exist_ok=True)

        _, managed = _managed_state(target)
        keep = set()

        # 2. Сначала убираем управляемые нами моды, не нужные текущему серверу -> в mods/botyaraMC/
        for name in sorted(managed - set(wanted)):
            obsolete_p = target / name
            if not obsolete_p.is_file():
                _cleanup_part(obsolete_p)
                continue
            try:
                if is_client:
                    stashed = _stash_mod(obsolete_p, stash_dir)
                    good[file_sha256(stashed)] = stashed
                    log.info("отложен в запас %s -> %s", name, stashed)
                else:
                    obsolete_p.unlink()
                    log.info("удалён с сервера %s", obsolete_p)
                _cleanup_part(obsolete_p)
            except OSError:
                log.exception("не удалось убрать неактуальный мод %s", name)
                keep.add(name)

        # 3. Устанавливаем / достаём из запаса / докачиваем нужные моды текущего сервера
        for name, m in wanted.items():
            dst = target / name
            sha = m["sha256"]
            size = int(m.get("size", 0))
            try:
                if dst.is_file() and file_sha256(dst) == sha:
                    good.setdefault(sha, dst)
                    _cleanup_part(dst)
                elif sha in good and good[sha].is_file() and file_sha256(good[sha]) == sha:
                    src_cached = good[sha]
                    # Если файл лежал в запасе mods/botyaraMC этой же папки и больше никому не нужен в копии — перемещаем или копируем
                    if is_client and src_cached.parent.resolve() == stash_dir.resolve():
                        shutil.move(str(src_cached), str(dst))
                    else:
                        tmp, _ = _part_paths(dst)
                        shutil.copyfile(src_cached, tmp)
                        os.replace(tmp, dst)
                    _cleanup_part(dst)
                    good[sha] = dst
                    log.info("восстановлен локально по SHA-256 -> %s", dst)
                else:
                    url = f"{_base(host, port)}/mods/{urllib.parse.quote(name)}"
                    tmp = _download_resumable(url, sha, size, dst, on_bytes=on_bytes)
                    os.replace(tmp, dst)
                    _cleanup_part(dst)
                    good[sha] = dst
                    log.info("скачан мод %s -> %s", name, target)
            except Exception:
                log.exception("не удалось синхронизировать мод %s в %s", name, target)
                all_ok = False
            if dst.exists():
                keep.add(name)
            done += 1
            if on_progress:
                on_progress(done / total)

        # 4. Если на сервере включён delete_user_mods — удаляем моды, добавленные игроком вручную
        if is_client and delete_user_mods:
            for jar_p in list(target.glob("*.jar")):
                if jar_p.is_file() and not jar_p.name.startswith(".") and jar_p.name not in wanted:
                    try:
                        jar_p.unlink()
                        log.info("удалён пользовательский мод %s (строгий режим сервера)", jar_p.name)
                    except OSError:
                        log.exception("не удалось удалить сторонний мод %s", jar_p)

        _managed_save(target, keep)
    return all_ok


def sync_resourcepacks(host, port, resourcepacks, rp_dir, on_progress=None, on_bytes=None):
    """Синхронизирует ресурспаки ТОЛЬКО добавлением новых (существующие РП игрока не трогает)."""
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
             on_progress=None, on_status=None, lang="ru"):
    """Полная синхронизация модов и ресурспаков в рабочую папку сборки (game_dir)."""
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
                on_status(i18n.tr(
                    lang, "downloading_live",
                    got=format_size(min(got_bytes[0], need_bytes), lang=lang),
                    total=format_size(need_bytes, lang=lang),
                ))

    game_dir = cfgmod.resolve_game_dir(mc_dir, manifest.get("client_folder", ""))
    client_mods_dir = game_dir / "mods"
    targets = [client_mods_dir]
    if is_host and server_mods_dir:
        targets.append(Path(server_mods_dir))

    mods_prog = (None if need_bytes > 0 else
                 (lambda f: on_progress(f * 0.8) if on_progress else None))
    rp_prog = (None if need_bytes > 0 else
               (lambda f: on_progress(0.8 + f * 0.2) if on_progress else None))

    ok_mods = sync(
        host, port, manifest.get("mods", []), targets,
        on_progress=mods_prog,
        on_bytes=_on_bytes,
        delete_user_mods=bool(manifest.get("delete_user_mods", False)),
        client_targets=[client_mods_dir],
    )
    ok_rp = sync_resourcepacks(
        host, port, manifest.get("resourcepacks", []),
        game_dir / "resourcepacks",
        on_progress=rp_prog,
        on_bytes=_on_bytes,
    )
    if on_progress:
        on_progress(1.0)
    return ok_mods and ok_rp
