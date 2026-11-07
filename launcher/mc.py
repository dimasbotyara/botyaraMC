"""Поиск .minecraft, установка версии/загрузчика и запуск в offline-режиме."""
import hashlib
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

import minecraft_launcher_lib as mll

log = logging.getLogger("botyaraMC.mc")


def find_minecraft_dir(custom=""):
    """Сохранённый путь -> типичные места своей ОС -> путь по умолчанию из библиотеки."""
    if custom:
        return Path(custom)
    home = Path.home()
    cands = []
    if sys.platform.startswith("win"):
        if os.environ.get("APPDATA"):
            cands.append(Path(os.environ["APPDATA"]) / ".minecraft")
    elif sys.platform == "darwin":
        cands.append(home / "Library" / "Application Support" / "minecraft")
    else:
        cands += [home / ".minecraft", home / ".var/app/com.mojang.Minecraft/data/minecraft"]
    cands.append(home / ".minecraft")
    for c in cands:
        if (c / "versions").is_dir() or (c / "launcher_profiles.json").exists():
            return c
    return Path(mll.utils.get_minecraft_directory())


def offline_uuid(name):
    """Тот же UUID, что считает сам Minecraft для offline-игрока."""
    digest = hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest, version=3))


def _progress_callback(on_frac):
    state = {"max": 0}

    def set_progress(p):
        on_frac(min(1.0, p / state["max"]) if state["max"] else 0.0)

    return {
        "setStatus": lambda t: None,
        "setProgress": set_progress,
        "setMax": lambda m: state.__setitem__("max", m),
    }


def _installed_ids(mc_dir):
    try:
        return [v["id"] for v in mll.utils.get_installed_versions(str(mc_dir))]
    except Exception:
        return []


def ensure_version(mc_dir, mc_version, loader, on_frac=None):
    """Возвращает id версии для запуска; ставит недостающее. Версия загрузчика не важна."""
    mc_dir = Path(mc_dir)
    mc_dir.mkdir(parents=True, exist_ok=True)
    cb = _progress_callback(on_frac or (lambda f: None))
    loader = (loader or "none").lower()

    def pick():
        ids = _installed_ids(mc_dir)
        if loader == "fabric":
            m = [i for i in ids if i.startswith("fabric-loader-") and i.endswith("-" + mc_version)]
        elif loader == "forge":
            m = [i for i in ids if "forge" in i.lower() and "neoforge" not in i.lower()
                 and i.startswith(mc_version + "-")]
        else:
            m = [i for i in ids if i == mc_version]
        return sorted(m)[-1] if m else None

    vid = pick()
    if vid is None:
        if loader == "fabric":
            mll.fabric.install_fabric(mc_version, str(mc_dir), callback=cb)
        elif loader == "forge":
            fv = mll.forge.find_forge_version(mc_version)
            if not fv:
                raise RuntimeError(f"Forge для {mc_version} не найден")
            mll.forge.install_forge_version(fv, str(mc_dir), callback=cb)
        else:
            mll.install.install_minecraft_version(mc_version, str(mc_dir), callback=cb)
        vid = pick()
        if vid is None:
            raise RuntimeError("версия не установилась")

    try:  # нужная Java от Mojang (если её ещё нет)
        info = mll.runtime.get_version_runtime_information(vid, str(mc_dir))
        if info:
            mll.runtime.install_jvm_runtime(info["name"], str(mc_dir), callback=cb)
    except Exception:
        log.exception("не удалось проверить Java-рантайм")
    return vid


def launch(mc_dir, version_id, nickname, server, port, ram_mb, log_path):
    ram = max(1024, int(ram_mb))
    options = {
        "username": nickname,
        "uuid": offline_uuid(nickname),
        "token": "0",
        "launcherName": "botyaraMC",
        "launcherVersion": "1.0",
        "jvmArguments": [f"-Xmx{ram}M", "-Xms512M"],
    }
    if server:
        options["server"] = str(server)
        options["port"] = str(port or 25565)
    cmd = mll.command.get_minecraft_command(version_id, str(mc_dir), options)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    logf = open(log_path, "ab")
    return subprocess.Popen(cmd, cwd=str(mc_dir), stdout=logf, stderr=subprocess.STDOUT,
                            creationflags=flags)
