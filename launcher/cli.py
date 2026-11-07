"""CLI-режим (без GUI): python main.py --play --nick Steve ... (для скриптов и systemd)."""
import argparse
import logging
import re
import signal
import sys
import time
from pathlib import Path

import config as cfgmod
import crash
import discovery
import jvm
import mc
import sync

log = logging.getLogger("botyaraMC.cli")
NICK_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
RES_RE = re.compile(r"^(\d{3,5})[xXхХ](\d{3,5})$")
DEFAULT_PORT = 25456


def parse_hostport(text):
    t = (text or "").strip().rstrip("/")
    for prefix in ("http://", "https://"):
        if t.startswith(prefix):
            t = t[len(prefix):]
    if not t:
        return None
    host, port = t, DEFAULT_PORT
    if ":" in t:
        host, _, p = t.rpartition(":")
        if not p.isdigit() or not 0 < int(p) < 65536:
            return None
        port = int(p)
    if not host or " " in host:
        return None
    return host, port


def build_parser():
    p = argparse.ArgumentParser(
        prog="botyaraMC",
        description="botyaraMC — минималистичный лаунчер Minecraft с авто-синхронизацией модов и ресурспаков.",
    )
    p.add_argument("--play", action="store_true",
                   help="Запустить синхронизацию и игру без GUI (headless CLI)")
    p.add_argument("--sync-only", action="store_true",
                   help="Только синхронизировать моды/ресурспаки и подготовить версию игры без запуска")
    p.add_argument("--detect-java", action="store_true",
                   help="Показать найденные в системе установки Java и выйти")
    p.add_argument("--nick", type=str, default=None,
                   help="Ник в игре (3–16 символов: A-Za-z0-9_)")
    p.add_argument("--server", type=str, default=None,
                   help="Адрес sync-сервера (например 26.12.34.56 или 26.12.34.56:25456)")
    p.add_argument("--mc-dir", type=str, default=None,
                   help="Путь к папке .minecraft")
    p.add_argument("--ram", type=int, default=None,
                   help="Выделить фиксированный объём RAM в МБ (например 4096)")
    p.add_argument("--auto-ram", action="store_true",
                   help="Автоматически подобрать RAM по системе")
    p.add_argument("--java", type=str, default=None,
                   help="Путь к исполняемому файлу Java")
    p.add_argument("--jvm-preset", type=str, default=None,
                   help="JVM-пресет (G1GC, \"Aikar's Flags\", ZGC, Минимальный или свой)")
    p.add_argument("--jvm-args", type=str, default=None,
                   help="Дополнительные параметры JVM")
    p.add_argument("--fullscreen", action="store_true",
                   help="Запустить игру в полноэкранном режиме")
    p.add_argument("--resolution", type=str, default=None,
                   help="Свой размер окна игры в формате ШxВ (например 1920x1080)")
    p.add_argument("--timeout", type=int, default=None,
                   help="Таймаут запуска игры в секундах (0 — отключить)")
    p.add_argument("--no-wait", action="store_true",
                   help="Не ждать закрытия игры (отсоединиться сразу после старта процесса)")
    p.add_argument("--share-crash", action="store_true",
                   help="При краше автоматически отправить лог на https://mclo.gs и вывести ссылку")
    return p


def _status(msg):
    print(f"[botyaraMC] {msg}", flush=True)


def run_cli(args):
    cfg = cfgmod.load()

    if args.mc_dir:
        cfg["mc_dir"] = args.mc_dir
    mc_dir = mc.find_minecraft_dir(cfg.get("mc_dir", ""))

    if args.detect_java:
        javas = jvm.detect_java_installations(mc_dir)
        if not javas:
            _status("Java в системе не найдена (при запуске скачается рантайм от Mojang).")
            return 0
        _status(f"Найдено установок Java: {len(javas)}")
        for j in javas:
            print(f"  - {j['label']}  ->  {j['path']}")
        return 0

    if args.nick is not None:
        cfg["nickname"] = args.nick.strip()
    if args.play and not NICK_RE.match(cfg.get("nickname", "")):
        print(
            "Ошибка: укажи корректный ник через --nick Steve (3–16 символов: a-z, A-Z, 0-9, _).",
            file=sys.stderr,
        )
        return 1

    if args.server:
        parsed = parse_hostport(args.server)
        if not parsed:
            print(f"Ошибка: некорректный адрес сервера: {args.server}", file=sys.stderr)
            return 1
        cfg["sync_host"], cfg["sync_port"] = parsed

    if args.ram is not None:
        cfg["auto_ram"] = False
        cfg["ram_mb"] = max(1024, int(args.ram))
    elif args.auto_ram:
        cfg["auto_ram"] = True

    if args.java:
        cfg["java_mode"] = "manual"
        cfg["java_path"] = args.java

    if args.jvm_preset:
        cfg["jvm_preset"] = args.jvm_preset
    if args.jvm_args is not None:
        cfg["extra_jvm_args"] = args.jvm_args

    if args.fullscreen:
        cfg["window_mode"] = "fullscreen"
    elif args.resolution:
        m = RES_RE.match(args.resolution.strip())
        if not m:
            print("Ошибка: разрешение должно быть вида 1920x1080", file=sys.stderr)
            return 1
        cfg["window_mode"] = "custom"
        cfg["window_width"], cfg["window_height"] = int(m.group(1)), int(m.group(2))

    if args.timeout is not None:
        cfg["launch_timeout"] = max(0, int(args.timeout))

    # 1. Получаем манифест с сервера (или автообнаружение -> кэш)
    host, port = cfg.get("sync_host", ""), cfg.get("sync_port", DEFAULT_PORT)
    manifest = None
    if host:
        try:
            _status(f"Подключаемся к sync-серверу {host}:{port}…")
            manifest = sync.fetch_manifest(host, port)
        except Exception as e:
            log.warning("sync-сервер %s:%s не ответил: %s", host, port, e)

    if manifest is None:
        _status("Ищем sync-сервер в локальной сети / Radmin VPN…")
        found = discovery.discover(2.5)
        if found:
            try:
                manifest = sync.fetch_manifest(*found)
                host, port = found
                _status(f"Найден сервер {host}:{port}")
            except Exception:
                log.exception("найденный сервер не отдал манифест")

    live = manifest is not None
    if live:
        cfgmod.save_cache(manifest)
    else:
        manifest = cfgmod.load_cache()
        if manifest:
            _status("Сервер недоступен — используем сохранённый кэш манифеста.")

    if manifest is None:
        print("Ошибка: sync-сервер недоступен и локальный кэш пуст.", file=sys.stderr)
        return 1

    # 2. Считаем размер загрузки и синхронизируем моды + ресурспаки
    if live:
        plan = sync.plan_sync(
            manifest, mc_dir,
            is_host=cfg.get("is_host", False),
            server_mods_dir=cfg.get("server_mods_dir", ""),
        )
        if plan["total_bytes"] > 0:
            _status(
                f"К загрузке: {sync.format_size(plan['total_bytes'])} "
                f"(модов: {plan['mods_count']}, ресурспаков: {plan['rp_count']})"
            )
        else:
            _status("Все моды и ресурспаки уже актуальны (0 Б).")

        last_pct = [-1]

        def on_prog(frac):
            pct = int(frac * 100)
            if pct >= last_pct[0] + 20 or pct == 100:
                last_pct[0] = pct
                _status(f"Синхронизация: {pct}%")

        ok = sync.sync_all(
            host, port, manifest, mc_dir,
            is_host=cfg.get("is_host", False),
            server_mods_dir=cfg.get("server_mods_dir", ""),
            on_progress=on_prog,
        )
        if not ok:
            _status("Предупреждение: часть файлов не удалось синхронизировать (см. launcher.log).")

    # 3. Проверяем / устанавливаем версию Minecraft и Java
    _status(f"Проверяем Minecraft {manifest['mc_version']} ({manifest['loader']})…")
    vid = mc.ensure_version(
        mc_dir, manifest["mc_version"], manifest["loader"],
        cfg=cfg, server_java_version=manifest.get("java_version"),
    )

    if args.sync_only and not args.play:
        _status(f"Готово! Версия {vid} установлена и файлы синхронизированы.")
        return 0

    # 4. Запускаем игру
    ram_mb = cfgmod.effective_ram_mb(cfg)
    srv = manifest.get("server") or {}
    log_path = cfgmod.config_dir() / "game.log"
    start_time = time.time()
    _status(
        f"Запускаем {vid} | ник: {cfg['nickname']} | RAM: {ram_mb} МБ | пресет: {cfg.get('jvm_preset', 'G1GC')}"
    )
    proc = mc.launch(
        mc_dir, vid, cfg["nickname"],
        srv.get("host"), srv.get("port"),
        ram_mb, log_path,
        cfg=cfg, server_java_version=manifest.get("java_version"),
    )
    _status(f"Процесс запущен (PID {proc.pid}).")

    if args.no_wait:
        return 0

    # Корректное завершение дочернего процесса при остановке systemd-юнита (SIGTERM / SIGINT)
    stopped_by_signal = [False]

    def _forward_stop(signum, _frame):
        stopped_by_signal[0] = True
        _status(f"Получен сигнал {signum}, завершаем игру…")
        try:
            proc.terminate()
        except OSError:
            pass

    old_int = signal.signal(signal.SIGINT, _forward_stop)
    old_term = signal.signal(signal.SIGTERM, _forward_stop)
    try:
        rc, timed_out = mc.monitor_launch(
            proc, log_path,
            timeout_sec=cfg.get("launch_timeout", 120),
            on_ready=lambda: _status("Игра успешно инициализирована! 🎮"),
        )
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)

    if stopped_by_signal[0]:
        _status("Игра остановлена по сигналу.")
        return 0

    full_log, has_cr, _ = crash.collect_session_log(mc_dir, log_path, start_time)
    if crash.is_crash(rc, full_log, has_crash_file=has_cr, timed_out=timed_out):
        report = crash.parse_crash(full_log, exit_code=rc, timed_out=timed_out)
        print(f"\n[CRASH] {report['title']} (код выхода: {rc})", file=sys.stderr)
        print(f"  {report['summary']}", file=sys.stderr)
        if report["exception"]:
            print(f"  Исключение: {report['exception']}", file=sys.stderr)
        if report["suspected_mods"]:
            print(f"  Подозрительные моды: {', '.join(report['suspected_mods'])}", file=sys.stderr)
        for tip in report["solutions"]:
            print(f"  * {tip}", file=sys.stderr)
        if args.share_crash:
            try:
                res = crash.upload_to_mclogs(
                    full_log,
                    mc_version=manifest["mc_version"],
                    loader=manifest["loader"],
                    exit_code=rc,
                )
                print(f"  Ссылка на лог (mclo.gs): {res['url']}", file=sys.stderr)
            except Exception as e:
                print(f"  Не удалось отправить лог на mclo.gs: {e}", file=sys.stderr)
        return 124 if timed_out else 2

    _status("Игра закрыта штатно.")
    return 0
