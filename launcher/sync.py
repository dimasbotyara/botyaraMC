"""Синхронизация модов, ресурспаков и фона: old-mods, кэш mods/botyaraMC, botyaramc.json, Range-докачка."""
import hashlib
import json
import logging
import os
import re
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
MARKER_FILE = cfgmod.MARKER_FILENAME  # "botyaramc.json"

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


def _safe_bg_name(name):
    return any(_safe_name(name, ext) for ext in (".png", ".jpg", ".jpeg", ".webp"))


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

    raw_bg = data.get("background")
    if isinstance(raw_bg, dict) and _safe_bg_name(raw_bg.get("name")) and raw_bg.get("sha256"):
        data["background"] = {
            "name": raw_bg["name"],
            "sha256": str(raw_bg["sha256"]).lower(),
            "size": max(0, int(raw_bg.get("size", 0))),
        }
    else:
        data["background"] = None

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


# --- учёт управляемых файлов прямо внутри папок (botyaramc.json) + резерв в managed.json ---
def _read_local_marker(folder):
    p = Path(folder) / MARKER_FILE
    try:
        d = json.loads(p.read_text("utf-8"))
        if isinstance(d, dict) and d.get("app") == "botyaraMC":
            return d
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_local_marker(folder, updates):
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    cur = _read_local_marker(folder) or {"app": "botyaraMC"}
    cur.update(updates)
    p = folder / MARKER_FILE
    tmp = p.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def _managed_state(target):
    """
    Возвращает (was_initialized: bool, managed_set: set[str]).
    Сначала читает botyaramc.json прямо внутри папки mods/ (не ломается при переименовании папки в Проводнике!).
    """
    local = _read_local_marker(target)
    if local is not None and "managed_mods" in local and isinstance(local["managed_mods"], list):
        return True, set(local["managed_mods"])
    data = cfgmod._read("managed.json", {})
    key = str(Path(target).resolve())
    if key not in data:
        return False, set()
    return True, set(data.get(key, []))


def _managed_save(target, names):
    sorted_names = sorted(names)
    _write_local_marker(target, {"managed_mods": sorted_names})
    try:
        data = cfgmod._read("managed.json", {})
        data[str(Path(target).resolve())] = sorted_names
        cfgmod._write("managed.json", data)
    except Exception:
        pass


def _managed_rp_state(rp_dir):
    local = _read_local_marker(rp_dir)
    if local is not None and isinstance(local.get("managed_resourcepacks"), list):
        return set(local["managed_resourcepacks"])
    return set()


def _managed_rp_save(rp_dir, names):
    _write_local_marker(rp_dir, {"managed_resourcepacks": sorted(names)})


def _enable_resourcepacks_in_options(game_dir, pack_names, mc_version="1.20.1"):
    """
    Аккуратно включает новые серверные ресурспаки в game_dir/options.txt при первой установке,
    не трогая уже выбранные ресурспаки игрока.
    """
    if not pack_names:
        return
    game_dir = Path(game_dir)
    opts_path = game_dir / "options.txt"

    # В MC 1.13+ записи имеют вид "file/pack.zip", в 1.12.2 и старше — "pack.zip"
    m = re.match(r"^1\.(\d+)", str(mc_version or "1.20.1").strip())
    legacy_fmt = bool(m and int(m.group(1)) < 13)

    lines = []
    if opts_path.is_file():
        try:
            lines = opts_path.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            return

    def _entry_for(nm):
        return nm if legacy_fmt else f"file/{nm}"

    rp_idx = None
    current_list = []
    for i, ln in enumerate(lines):
        if ln.startswith("resourcePacks:"):
            rp_idx = i
            raw_json = ln[len("resourcePacks:"):].strip()
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, list):
                    current_list = [str(x) for x in parsed]
            except ValueError:
                current_list = []
            break

    if not current_list and not legacy_fmt:
        current_list = ["vanilla"]

    changed = False
    existing_norm = {x.lower() for x in current_list}
    for nm in pack_names:
        cand = _entry_for(nm)
        if cand.lower() not in existing_norm and nm.lower() not in existing_norm:
            current_list.append(cand)
            existing_norm.add(cand.lower())
            changed = True

    if not changed:
        return

    rendered_line = "resourcePacks:" + json.dumps(current_list, ensure_ascii=False, separators=(",", ":"))
    if rp_idx is not None:
        lines[rp_idx] = rendered_line
    else:
        lines.append(rendered_line)

    try:
        game_dir.mkdir(parents=True, exist_ok=True)
        tmp = opts_path.with_suffix(".txt.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, opts_path)
    except OSError:
        log.exception("не удалось обновить resourcePacks в options.txt")


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


def _effective_host_target(is_host, server_mods_dir, client_mods_dir):
    """Возвращает безопасный Path папки модов MC-сервера хоста или None."""
    if not is_host or not server_mods_dir:
        return None
    if cfgmod.is_sync_server_own_mods_dir(server_mods_dir):
        log.warning("server_mods_dir указывает на папку самого sync-сервера — пропускаем перезапись источника")
        return None
    srv_p = Path(server_mods_dir)
    try:
        if srv_p.expanduser().resolve() == Path(client_mods_dir).expanduser().resolve():
            return None
    except OSError:
        pass
    return srv_p


def plan_sync(manifest, mc_dir, is_host=False, server_mods_dir="", cfg=None):
    """
    Считает, сколько байт реально нужно докачать по сети
    (с учётом активных модов, запаса в mods/botyaraMC, обновлённых серверных РП и .part).
    """
    game_dir = cfgmod.resolve_game_dir(
        mc_dir, manifest.get("client_folder", ""), cfg=cfg, manifest=manifest
    )
    client_mods_dir = game_dir / "mods"
    mod_targets = [client_mods_dir]
    host_target = _effective_host_target(is_host, server_mods_dir, client_mods_dir)
    if host_target is not None:
        mod_targets.append(host_target)

    local_by_sha = _local_sha_index(mod_targets)
    total_bytes = 0
    mods_to_dl = 0
    rp_to_dl = 0
    stash_swaps = 0

    seen_mod_shas = set()
    for m in manifest.get("mods", []):
        sha = m["sha256"]
        size = max(0, int(m.get("size", 0)))
        name = m["name"]

        in_place_all = True
        for t in mod_targets:
            dst = t / name
            if not (dst.is_file() and file_sha256(dst) == sha):
                in_place_all = False
                break
        if in_place_all:
            continue

        if sha in local_by_sha or sha in seen_mod_shas:
            stash_swaps += 1
            continue

        best_part = 0
        for t in mod_targets:
            dst = t / name
            best_part = max(best_part, _valid_part_bytes(dst, sha, size))
        seen_mod_shas.add(sha)
        mods_to_dl += 1
        total_bytes += max(0, size - best_part)

    rp_dir = game_dir / "resourcepacks"
    managed_rps = _managed_rp_state(rp_dir)
    for rp in manifest.get("resourcepacks", []):
        name = rp["name"]
        sha = rp["sha256"]
        dst = rp_dir / name
        if dst.exists():
            # Личные РП игрока с совпадающим именем не трогаем; обновляем только РП самого сервера при смене SHA-256!
            if name not in managed_rps:
                continue
            try:
                if file_sha256(dst) == sha:
                    continue
            except OSError:
                continue
        size = max(0, int(rp.get("size", 0)))
        part = _valid_part_bytes(dst, sha, size)
        rp_to_dl += 1
        total_bytes += max(0, size - part)

    return {
        "total_bytes": total_bytes,
        "mods_count": mods_to_dl,
        "rp_count": rp_to_dl,
        "stash_swaps": stash_swaps,
        "total_files": mods_to_dl + rp_to_dl + stash_swaps,
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


def ensure_server_background(host, port, bg_meta, server_id=""):
    """Скачивает и кэширует кастомный фон от сервера по SHA-256; возвращает локальный Path или None."""
    if not isinstance(bg_meta, dict) or not _safe_bg_name(bg_meta.get("name")) or not bg_meta.get("sha256"):
        return None
    sha = str(bg_meta["sha256"]).lower()
    size = max(0, int(bg_meta.get("size", 0)))
    ext = Path(bg_meta["name"]).suffix.lower()
    bg_dir = cfgmod.config_dir() / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)
    tag = re.sub(r"[^A-Za-z0-9_.-]", "_", str(server_id or host or "srv"))[:24]
    dst = bg_dir / f"{tag}_{sha[:16]}{ext}"
    if dst.is_file():
        try:
            if file_sha256(dst) == sha:
                return dst
        except OSError:
            pass
    url = f"{_base(host, port)}/background"
    tmp = _download_resumable(url, sha, size, dst)
    os.replace(tmp, dst)
    _cleanup_part(dst)
    return dst


def sync(host, port, mods, targets, on_progress=None, on_bytes=None,
         delete_user_mods=False, client_targets=None):
    """
    Синхронизирует моды во все папки targets:
    - Если папка клиента не пустая и ранее не управлялась botyaraMC -> переносит всё былое в mods/old-mods/.
    - Временно ненужные моды botyaraMC (от других серверов) складывает в mods/botyaraMC/ вместо удаления.
    - При delete_user_mods=True бережно убирает сторонние моды игрока в mods/old-mods/ (не уничтожая их навсегда!).
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
        was_init, _ = _managed_state(target)
        if is_client and not was_init:
            existing_entries = [
                p for p in sorted(target.iterdir())
                if p.name not in ("old-mods", "botyaraMC", MARKER_FILE)
                and not p.name.endswith(".part")
                and not p.name.endswith(".part.sha256")
                and not p.name.endswith(".json.tmp")
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

        # 2. Убираем управляемые нами моды, не нужные текущему серверу -> в mods/botyaraMC/
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

        # 4. При delete_user_mods=True бережно убираем сторонние моды игрока в mods/old-mods/ (вместо удаления!)
        if is_client and delete_user_mods:
            old_dir = target / "old-mods"
            for jar_p in list(target.glob("*.jar")):
                if jar_p.is_file() and not jar_p.name.startswith(".") and jar_p.name not in wanted:
                    try:
                        _move_unique(jar_p, old_dir)
                        log.info("перенесён пользовательский мод %s -> %s (строгий режим)", jar_p.name, old_dir)
                    except OSError:
                        log.exception("не удалось перенести сторонний мод %s", jar_p)

        _managed_save(target, keep)
    return all_ok


def sync_resourcepacks(host, port, resourcepacks, rp_dir, on_progress=None, on_bytes=None,
                       mc_version="1.20.1", auto_enable_options=True):
    """
    Синхронизирует ресурспаки сервера:
    - Не трогает и не удаляет личные ресурспаки игрока.
    - Если сам хост обновил ранее установленный серверный ресурспак (изменился SHA-256) — обновляет его!
    - При первой установке серверного ресурспака автоматически включает его в options.txt.
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

    managed_rps = _managed_rp_state(rp_dir)
    newly_installed = []
    all_ok = True
    total = max(1, len(resourcepacks))

    for idx, rp in enumerate(resourcepacks, 1):
        name = rp["name"]
        sha = rp["sha256"]
        dst = rp_dir / name

        if dst.exists():
            # Файл не от botyaraMC -> личный ресурспак игрока, не перезаписываем!
            if name not in managed_rps:
                if on_progress:
                    on_progress(idx / total)
                continue
            try:
                if file_sha256(dst) == sha:
                    if on_progress:
                        on_progress(idx / total)
                    continue
            except OSError:
                pass

        was_first_install = not dst.exists()
        try:
            url = f"{_base(host, port)}/resourcepacks/{urllib.parse.quote(name)}"
            tmp = _download_resumable(url, sha, int(rp.get("size", 0)), dst, on_bytes=on_bytes)
            os.replace(tmp, dst)
            _cleanup_part(dst)
            managed_rps.add(name)
            if was_first_install:
                newly_installed.append(name)
            log.info("синхронизирован ресурспак %s -> %s", name, rp_dir)
        except Exception:
            log.exception("не удалось скачать ресурспак %s", name)
            all_ok = False
        if on_progress:
            on_progress(idx / total)

    _managed_rp_save(rp_dir, managed_rps)
    if auto_enable_options and newly_installed:
        _enable_resourcepacks_in_options(rp_dir.parent, newly_installed, mc_version=mc_version)
    return all_ok


def sync_all(host, port, manifest, mc_dir, is_host=False, server_mods_dir="",
             on_progress=None, on_status=None, lang="ru", cfg=None):
    """Полная синхронизация модов и ресурспаков в рабочую папку сборки (game_dir)."""
    plan = plan_sync(manifest, mc_dir, is_host=is_host, server_mods_dir=server_mods_dir, cfg=cfg)
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

    game_dir = cfgmod.resolve_game_dir(
        mc_dir, manifest.get("client_folder", ""), cfg=cfg, manifest=manifest
    )
    if isinstance(cfg, dict):
        srv_entry = cfgmod.get_active_server(cfg)
        if srv_entry is not None and game_dir.resolve() != Path(mc_dir).resolve():
            cfgmod.write_folder_marker(game_dir, srv_entry)

    client_mods_dir = game_dir / "mods"
    targets = [client_mods_dir]
    host_target = _effective_host_target(is_host, server_mods_dir, client_mods_dir)
    if host_target is not None:
        targets.append(host_target)

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
        mc_version=manifest.get("mc_version", "1.20.1"),
    )
    if on_progress:
        on_progress(1.0)
    return ok_mods and ok_rp
