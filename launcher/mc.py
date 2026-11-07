"""Поиск .minecraft, установка версии/загрузчика, разрешение экрана, запуск и таймаут."""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import minecraft_launcher_lib as mll

import config as cfgmod
import jvm

log = logging.getLogger("botyaraMC.mc")

_READY_MARKERS = (
    "backend library:",
    "lwjgl version:",
    "lwjgl ",
    "openal initialized",
    "sound engine started",
    "narrator library",
    "connecting to ",
)


def _natural_key(text):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(text))]


def find_minecraft_dir(custom=""):
    """Сохранённый путь -> типичные места своей ОС -> путь по умолчанию из библиотеки."""
    if custom:
        return Path(custom).expanduser()
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


def _pick_installed_version(mc_dir, mc_version, loader):
    ids = _installed_ids(mc_dir)
    loader = (loader or "none").lower()
    if loader == "fabric":
        m = [i for i in ids if i.startswith("fabric-loader-") and i.endswith("-" + mc_version)]
    elif loader == "quilt":
        m = [i for i in ids if i.startswith("quilt-loader-") and i.endswith("-" + mc_version)]
    elif loader == "neoforge":
        m = [i for i in ids if "neoforge" in i.lower() and mc_version in i]
    elif loader == "forge":
        m = [i for i in ids if "forge" in i.lower() and "neoforge" not in i.lower()
             and i.startswith(mc_version + "-")]
    else:
        m = [i for i in ids if i == mc_version]
    return sorted(m, key=_natural_key)[-1] if m else None


def ensure_version(mc_dir, mc_version, loader, on_frac=None, cfg=None, server_java_version=None):
    """Возвращает id версии для запуска; ставит недостающую версию, загрузчик и Java-рантайм."""
    mc_dir = Path(mc_dir)
    mc_dir.mkdir(parents=True, exist_ok=True)
    cb = _progress_callback(on_frac or (lambda f: None))
    loader = (loader or "none").lower()
    cfg = cfg or cfgmod.load()

    vid = _pick_installed_version(mc_dir, mc_version, loader)
    if vid is None:
        # Для Forge/NeoForge установщик запускает java-процессоры — сначала гарантируем базовую версию и Java!
        if loader in ("forge", "neoforge"):
            if _pick_installed_version(mc_dir, mc_version, "none") is None:
                mll.install.install_minecraft_version(mc_version, str(mc_dir), callback=cb)
            java_for_installer, _ = jvm.resolve_java(
                cfg, mc_dir, version_id=mc_version,
                server_java_version=server_java_version, cb=cb,
            )
        else:
            java_for_installer = None

        if hasattr(mll, "mod_loader") and loader in ("fabric", "forge", "neoforge", "quilt"):
            ml = mll.mod_loader.get_mod_loader(loader)
            vid = ml.install(mc_version, str(mc_dir), callback=cb, java=java_for_installer)
        elif loader == "fabric":
            mll.fabric.install_fabric(mc_version, str(mc_dir), callback=cb)
        elif loader == "forge":
            fv = mll.forge.find_forge_version(mc_version)
            if not fv:
                raise RuntimeError(f"Forge для {mc_version} не найден")
            mll.forge.install_forge_version(fv, str(mc_dir), callback=cb, java=java_for_installer)
        else:
            mll.install.install_minecraft_version(mc_version, str(mc_dir), callback=cb)

        vid = vid or _pick_installed_version(mc_dir, mc_version, loader)
        if vid is None:
            raise RuntimeError("версия не установилась")

    # Проверяем / докачиваем подходящую Java
    try:
        jvm.resolve_java(cfg, mc_dir, version_id=vid, server_java_version=server_java_version, cb=cb)
    except Exception:
        if cfg.get("java_mode") == "manual":
            raise
        log.exception("не удалось подготовить Java-рантайм")
    return vid


def _supports_quick_play_multiplayer(mc_dir, version_id):
    """Проверяет по client.json (и родительскому профилю), поддерживает ли версия --quickPlayMultiplayer (MC 1.20+)."""
    mc_dir = Path(mc_dir)
    seen = set()
    cur = version_id
    while cur and cur not in seen:
        seen.add(cur)
        vjson = mc_dir / "versions" / cur / f"{cur}.json"
        try:
            raw = vjson.read_text(encoding="utf-8")
            if "is_quick_play_multiplayer" in raw:
                return True
            data = json.loads(raw)
            cur = data.get("inheritsFrom")
        except (OSError, ValueError):
            break
    return False


def build_command(mc_dir, version_id, nickname, server=None, port=None, cfg=None,
                  server_java_version=None, auto_join=True, client_folder=""):
    """Собирает полную команду запуска Minecraft с учётом Java, JVM-пресета, RAM, папки и автовхода."""
    mc_dir = Path(mc_dir)
    cfg = cfg or cfgmod.load()
    game_dir = cfgmod.resolve_game_dir(mc_dir, client_folder)
    game_dir.mkdir(parents=True, exist_ok=True)

    ram = cfgmod.effective_ram_mb(cfg)
    java_exec, java_major = jvm.resolve_java(
        cfg, mc_dir, version_id=version_id, server_java_version=server_java_version,
    )
    jvm_args = jvm.build_jvm_arguments(cfg, ram, java_major=java_major)

    options = {
        "username": nickname,
        "uuid": offline_uuid(nickname),
        "token": "0",
        "executablePath": java_exec,
        "launcherName": "botyaraMC",
        "launcherVersion": "2.0",
        "gameDirectory": str(game_dir),
        "jvmArguments": jvm_args,
    }

    win_mode = cfg.get("window_mode", "default")
    if win_mode == "custom":
        try:
            w = max(320, int(cfg.get("window_width", 1280)))
            h = max(240, int(cfg.get("window_height", 720)))
        except (TypeError, ValueError):
            w, h = 1280, 720
        options["customResolution"] = True
        options["resolutionWidth"] = str(w)
        options["resolutionHeight"] = str(h)

    if auto_join:
        srv_host = str(server or "").strip()
        sync_h = str(cfg.get("sync_host") or "").strip()
        if srv_host.lower() in ("", "auto", "127.0.0.1", "localhost", "0.0.0.0") and sync_h:
            srv_host = sync_h
        srv_port = str(port or 25565).strip()
        if srv_host:
            if _supports_quick_play_multiplayer(mc_dir, version_id):
                options["quickPlayMultiplayer"] = f"{srv_host}:{srv_port}"
            else:
                options["server"] = srv_host
                options["port"] = srv_port

    cmd = mll.command.get_minecraft_command(version_id, str(mc_dir), options)
    if win_mode == "fullscreen" and "--fullscreen" not in cmd:
        cmd.append("--fullscreen")
    return cmd


def launch(mc_dir, version_id, nickname, server, port, ram_mb, log_path,
           cfg=None, server_java_version=None, auto_join=True, client_folder=""):
    """Запускает процесс Minecraft, ротируя прошлый game.log -> game.prev.log."""
    mc_dir = Path(mc_dir)
    game_dir = cfgmod.resolve_game_dir(mc_dir, client_folder)
    game_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if log_path.is_file() and log_path.stat().st_size > 0:
        try:
            shutil.copyfile(log_path, log_path.with_name("game.prev.log"))
        except OSError:
            pass

    eff_cfg = dict(cfg or cfgmod.load())
    if ram_mb and "auto_ram" not in (cfg or {}):
        eff_cfg["auto_ram"] = False
        eff_cfg["ram_mb"] = int(ram_mb)

    cmd = build_command(
        mc_dir, version_id, nickname,
        server=server, port=port, cfg=eff_cfg,
        server_java_version=server_java_version,
        auto_join=auto_join,
        client_folder=client_folder,
    )
    log.info("Команда запуска (%s): %s ...", version_id, cmd[:6])

    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    with open(log_path, "wb") as logf:
        proc = subprocess.Popen(
            cmd,
            cwd=str(game_dir),
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    return proc


def _log_has_ready_marker(log_path):
    try:
        if not log_path.is_file():
            return False
        size = log_path.stat().st_size
        with open(log_path, "rb") as f:
            if size > 262_144:
                f.seek(size - 262_144)
            tail = f.read().decode("utf-8", errors="ignore").lower()
        return any(m in tail for m in _READY_MARKERS)
    except OSError:
        return False


def monitor_launch(proc, log_path, timeout_sec=120, on_ready=None):
    """
    Ждёт инициализации окна игры с контролем таймаута запуска, затем ждёт закрытия игры.
    Возвращает (exit_code, timed_out).
    """
    log_path = Path(log_path)
    try:
        timeout = max(0, int(timeout_sec or 0))
    except (TypeError, ValueError):
        timeout = 120

    started_notified = False
    start_ts = time.monotonic()

    if timeout <= 0:
        # Таймаут выключен — ждём пару секунд и считаем запущенным, если процесс жив
        time.sleep(1.2)
        if proc.poll() is None and on_ready:
            on_ready()
        rc = proc.wait()
        return rc, False

    deadline = start_ts + timeout
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            return rc, False
        if _log_has_ready_marker(log_path):
            started_notified = True
            if on_ready:
                on_ready()
            break
        time.sleep(0.4)

    if not started_notified and proc.poll() is None:
        log.warning("Таймаут запуска (%s сек) истёк — останавливаем процесс PID %s", timeout, proc.pid)
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except OSError:
                pass
        except OSError:
            pass
        try:
            with open(log_path, "ab") as f:
                f.write(
                    f"\n[botyaraMC] Превышен таймаут запуска ({timeout} сек). Процесс остановлен.\n".encode("utf-8")
                )
        except OSError:
            pass
        return (proc.returncode if proc.returncode is not None else -9), True

    rc = proc.wait()
    return rc, False
