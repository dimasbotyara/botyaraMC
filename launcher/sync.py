"""Тихая синхронизация модов: скачать / обновить / удалить, сверяя SHA-256."""
import hashlib
import json
import logging
import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

import config as cfgmod

log = logging.getLogger("botyaraMC.sync")
TIMEOUT = 8


def _safe_name(name):
    return (isinstance(name, str) and name and name == os.path.basename(name)
            and "/" not in name and "\\" not in name
            and name.lower().endswith(".jar") and not name.startswith("."))


def _base(host, port):
    return f"http://{host}:{port}"


def fetch_manifest(host, port):
    with urllib.request.urlopen(_base(host, port) + "/manifest", timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("app") != "botyaraMC":
        raise ValueError("это не botyaraMC-сервер")
    data["mods"] = [
        {"name": m["name"], "sha256": str(m["sha256"]).lower(), "size": int(m.get("size", 0))}
        for m in data.get("mods", []) if _safe_name(m.get("name")) and m.get("sha256")
    ]
    return data


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(host, port, mod, tmp):
    url = f"{_base(host, port)}/mods/{urllib.parse.quote(mod['name'])}"
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
    if h.hexdigest() != mod["sha256"]:
        raise ValueError(f"хэш не сошёлся: {mod['name']}")


# --- помним, какие моды поставили МЫ, чтобы не трогать чужие ---
def _managed_load(target):
    data = cfgmod._read("managed.json", {})
    return set(data.get(str(Path(target).resolve()), []))


def _managed_save(target, names):
    data = cfgmod._read("managed.json", {})
    data[str(Path(target).resolve())] = sorted(names)
    cfgmod._write("managed.json", data)


def sync(host, port, mods, targets, on_progress=None):
    """Синхронизирует моды во все папки targets. True - если всё прошло гладко."""
    wanted = {m["name"]: m for m in mods}
    total = max(1, len(wanted) * len(targets))
    done, all_ok, good = 0, True, {}

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
            dst, tmp = target / name, target / (name + ".part")
            try:
                if dst.is_file() and file_sha256(dst) == m["sha256"]:
                    good.setdefault(name, dst)
                else:
                    if name in good:
                        shutil.copyfile(good[name], tmp)
                    else:
                        _download(host, port, m, tmp)
                    os.replace(tmp, dst)
                    good[name] = dst
                    log.info("обновлён %s -> %s", name, target)
            except Exception:
                log.exception("не удалось синхронизировать %s в %s", name, target)
                all_ok = False
                try:
                    tmp.unlink()
                except OSError:
                    pass
            if dst.exists():
                keep.add(name)
            done += 1
            if on_progress:
                on_progress(done / total)
        for name in managed - set(wanted):  # на сервере этого мода больше нет
            try:
                (target / name).unlink()
                log.info("удалён %s из %s", name, target)
            except FileNotFoundError:
                pass
            except OSError:
                log.exception("не удалось удалить %s", name)
                keep.add(name)  # попробуем в следующий раз
        _managed_save(target, keep)
    return all_ok
