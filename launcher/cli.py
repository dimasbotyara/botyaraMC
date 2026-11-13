"""CLI-режим (без GUI): python main.py --play --nick Steve ... (для скриптов и systemd)."""
import argparse
import ipaddress
import logging
import re
import signal
import sys
import time

import config as cfgmod
import crash
import discovery
import i18n
import jvm
import mc
import sync

log = logging.getLogger("botyaraMC.cli")
RES_RE = re.compile(r"^(\d{3,5})[xXхХ](\d{3,5})$")
DEFAULT_PORT = 25456
_DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?$")


def parse_hostport(text):
    t = (text or "").strip().rstrip("/")
    for prefix in ("http://", "https://"):
        if t.lower().startswith(prefix):
            t = t[len(prefix):]
    if not t or " " in t or "/" in t or "\\" in t:
        return None
    host, port = t, DEFAULT_PORT
    if t.startswith("["):  # [::1]:25456 — скобочный IPv6
        close = t.find("]")
        if close == -1:
            return None
        host, rest = t[:close + 1], t[close + 1:]
        if rest.startswith(":"):
            if not rest[1:].isdigit() or not 0 < int(rest[1:]) < 65536:
                return None
            port = int(rest[1:])
        elif rest:
            return None
    elif ":" in t:
        host, _, p = t.rpartition(":")
        if not p.isdigit() or not 0 < int(p) < 65536 or ":" in host:
            return None  # bare IPv6 вида 26::1 не должен склеиваться в host:port
        port = int(p)
    if not host:
        return None
    if ":" in host:  # IPv6 (в скобках): сохраняем их — они нужны в http://URL
        inner = host[1:-1] if host.startswith("[") and host.endswith("]") else host
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            return None
        return host, port
    # Если ввод состоит только из цифр и точек — требуем полный корректный IPv4 (4 октета 0..255)
    if re.fullmatch(r"[0-9.]+", host):
        parts = host.split(".")
        if len(parts) != 4 or any(not x.isdigit() or not 0 <= int(x) <= 255 for x in parts):
            return None
        return host, port
    # Поддержка буквенных доменов хостинга, поддоменов и IDN (.рф)
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = ascii_host.split(".")
    if len(ascii_host) < 2 or any(not _DOMAIN_LABEL_RE.fullmatch(lb) for lb in labels):
        return None
    return host, port


def build_parser():
    p = argparse.ArgumentParser(
        prog="botyaraMC",
        description="botyaraMC — minimalist Minecraft launcher with automatic modpack & resourcepack sync.",
    )
    p.add_argument("--play", action="store_true",
                   help="Sync and launch Minecraft without GUI (headless CLI)")
    p.add_argument("--sync-only", action="store_true",
                   help="Only sync mods/resourcepacks and prepare Minecraft version without launching")
    p.add_argument("--detect-java", action="store_true",
                   help="List detected Java installations and exit")
    p.add_argument("--lang", type=str, choices=["ru", "en"], default=None,
                   help="Output language: ru or en")
    p.add_argument("--nick", type=str, default=None,
                   help="In-game nickname (3–16 chars: A-Za-z0-9_)")
    p.add_argument("--server", type=str, default=None,
                   help="Sync server address (IP or domain, e.g. 26.12.34.56 or sync.example.com:25456)")
    p.add_argument("--mc-dir", type=str, default=None,
                   help="Path to base .minecraft directory")
    p.add_argument("--isolation", type=str, choices=["none", "family", "version"], default=None,
                   help="Version folder isolation mode: none, family (home/Fabric-1.16), version (home/Fabric 1.16.5)")
    p.add_argument("--ram", type=int, default=None,
                   help="Fixed RAM allocation in MB (e.g. 4096)")
    p.add_argument("--auto-ram", action="store_true",
                   help="Automatically calculate RAM based on system memory")
    p.add_argument("--java", type=str, default=None,
                   help="Path to Java executable")
    p.add_argument("--jvm-preset", type=str, default=None,
                   help="JVM preset (G1GC, \"Aikar's Flags\", ZGC, Minimal, Custom)")
    p.add_argument("--jvm-args", type=str, default=None,
                   help="Additional JVM flags")
    p.add_argument("--fullscreen", action="store_true",
                   help="Launch Minecraft in fullscreen mode")
    p.add_argument("--resolution", type=str, default=None,
                   help="Custom window resolution WxH (e.g. 1920x1080)")
    p.add_argument("--gamemode", action="store_true",
                   help="(Linux) Wrap game launch with Feral GameMode (gamemoderun)")
    p.add_argument("--mangohud", action="store_true",
                   help="(Linux) Enable MangoHud overlay (mangohud)")
    p.add_argument("--timeout", type=int, default=None,
                   help="Launch timeout in seconds (0 to disable)")
    p.add_argument("--no-wait", action="store_true",
                   help="Detach immediately after launching Minecraft")
    p.add_argument("--share-crash", action="store_true",
                   help="Automatically upload crash log to https://mclo.gs and print URL")
    return p


def _status(msg):
    print(f"[botyaraMC] {msg}", flush=True)


def run_cli(args):
    cfg = cfgmod.load()
    if args.lang in ("ru", "en"):
        cfg["language"] = args.lang
    lang = cfg.get("language", "ru")
    en = (lang == "en")

    if args.mc_dir:
        cfg["mc_dir"] = args.mc_dir
    if args.isolation in ("none", "family", "version"):
        cfg["isolation_mode"] = args.isolation
    if args.gamemode:
        cfg["use_gamemode"] = True
    if args.mangohud:
        cfg["use_mangohud"] = True

    mc_dir = mc.find_minecraft_dir(cfg.get("mc_dir", ""))

    if args.detect_java:
        javas = jvm.detect_java_installations(mc_dir)
        if not javas:
            _status("No Java found on system (Mojang runtime will be downloaded automatically)."
                    if en else "Java в системе не найдена (при запуске скачается рантайм от Mojang).")
            return 0
        _status(f"Detected Java installations: {len(javas)}" if en else f"Найдено установок Java: {len(javas)}")
        for j in javas:
            print(f"  - {j['label']}  ->  {j['path']}")
        return 0

    if args.nick is not None:
        cfg["nickname"] = args.nick
    if args.play:
        ok_nick, err_nick = i18n.validate_nickname(cfg.get("nickname", ""), lang=lang)
        if not ok_nick:
            prefix = "Error:" if en else "Ошибка:"
            print(f"{prefix} {err_nick} (--nick Steve)", file=sys.stderr)
            return 1

    if args.sync_only and args.play:
        print("Error: --sync-only and --play are mutually exclusive." if en
              else "Ошибка: --sync-only и --play нельзя использовать вместе.", file=sys.stderr)
        return 1

    if args.server:
        parsed = parse_hostport(args.server)
        if not parsed:
            msg = f"Error: invalid server address: {args.server}" if en else f"Ошибка: некорректный адрес сервера: {args.server}"
            print(msg, file=sys.stderr)
            return 1
        cfgmod.add_or_select_server(cfg, parsed[0], parsed[1])
        # Сохраняем id сервера сразу: без этого кэш манифеста при следующем
        # запуске оказывался у несуществующего id и офлайн-режим ломался.
        cfgmod.save(cfg)

    if args.ram is not None:
        cfg["auto_ram"] = False
        ram_cap = cfgmod.max_selectable_ram_mb()
        cfg["ram_mb"] = max(1024, min(int(args.ram), ram_cap))
        if int(args.ram) > ram_cap:
            _status(f"RAM capped to {ram_cap} MB (system limit)." if en
                    else f"RAM ограничена до {ram_cap} МБ (лимит системы).")
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
            print("Error: resolution must be WxH (e.g. 1920x1080)" if en else "Ошибка: разрешение должно быть вида 1920x1080", file=sys.stderr)
            return 1
        cfg["window_mode"] = "custom"
        cfg["window_width"], cfg["window_height"] = int(m.group(1)), int(m.group(2))

    if args.timeout is not None:
        cfg["launch_timeout"] = max(0, int(args.timeout))

    host, port = cfg.get("sync_host", ""), cfg.get("sync_port", DEFAULT_PORT)
    srv_id = cfg.get("active_server_id") or None
    cached = cfgmod.load_cache(server_id=srv_id)
    manifest = None
    if host:
        try:
            _status(f"Connecting to sync server {host}:{port}…" if en else f"Подключаемся к sync-серверу {host}:{port}…")
            manifest = sync.fetch_manifest(
                host, port, cached=cached, cached_etag=(cached or {}).get("_etag"))
        except Exception as e:
            log.warning("sync-сервер %s:%s не ответил: %s", host, port, e)

    if manifest is None:
        _status("Searching for sync server on LAN / Radmin VPN…" if en else "Ищем sync-сервер в локальной сети / Radmin VPN…")
        candidates = discovery.discover_all(2.2)
        matched = cfgmod.match_discovered_server(cfg, candidates)
        if matched:
            fh, fp, _fname, _entry = matched
            try:
                manifest = sync.fetch_manifest(
                    fh, fp, cached=cached, cached_etag=(cached or {}).get("_etag"))
                host, port = fh, fp
                _status(f"Found server {host}:{port}" if en else f"Найден сервер {host}:{port}")
                # Запоминаем найденный адрес, чтобы он не «слетал» между запусками
                cfgmod.save(cfg)
            except Exception:
                log.exception("найденный сервер не отдал манифест")

    live = manifest is not None
    if live:
        cfgmod.save_cache(manifest, server_id=srv_id)
    else:
        manifest = cfgmod.load_cache(server_id=srv_id)
        if manifest:
            _status("Server offline — using cached manifest." if en else "Сервер недоступен — используем сохранённый кэш манифеста.")

    if manifest is None:
        print("Error: sync server unreachable and local cache is empty." if en else "Ошибка: sync-сервер недоступен и локальный кэш пуст.", file=sys.stderr)
        return 1

    if live:
        plan = sync.plan_sync(
            manifest, mc_dir,
            is_host=cfg.get("is_host", False),
            server_mods_dir=cfg.get("server_mods_dir", ""),
            cfg=cfg,
        )
        if plan["total_bytes"] > 0:
            sz = sync.format_size(plan["total_bytes"], lang=lang)
            _status(
                f"To download: {sz} (mods: {plan['mods_count']}, resourcepacks: {plan['rp_count']})"
                if en else
                f"К загрузке: {sz} (модов: {plan['mods_count']}, ресурспаков: {plan['rp_count']})"
            )
        else:
            _status("All mods and resourcepacks are up to date (0 B)." if en else "Все моды и ресурспаки уже актуальны (0 Б).")

        last_pct = [-1]

        def on_prog(frac):
            pct = int(frac * 100)
            if pct >= last_pct[0] + 20 or pct == 100:
                last_pct[0] = pct
                _status(f"Sync: {pct}%" if en else f"Синхронизация: {pct}%")

        ok = sync.sync_all(
            host, port, manifest, mc_dir,
            is_host=cfg.get("is_host", False),
            server_mods_dir=cfg.get("server_mods_dir", ""),
            on_progress=on_prog,
            lang=lang,
            cfg=cfg,
        )
        if not ok:
            _status("Warning: some files failed to sync (see launcher.log)." if en else "Предупреждение: часть файлов не удалось синхронизировать (см. launcher.log).")

    _status(f"Checking Minecraft {manifest['mc_version']} ({manifest['loader']})…" if en else f"Проверяем Minecraft {manifest['mc_version']} ({manifest['loader']})…")
    vid = mc.ensure_version(
        mc_dir, manifest["mc_version"], manifest["loader"],
        cfg=cfg, server_java_version=manifest.get("java_version"),
    )

    if args.sync_only and not args.play:
        _status(f"Done! {vid} installed and synced." if en else f"Готово! Версия {vid} установлена и файлы синхронизированы.")
        return 0

    ram_mb = cfgmod.effective_ram_mb(cfg)
    srv = manifest.get("server") or {}
    client_folder = manifest.get("client_folder", "")
    game_dir = cfgmod.resolve_game_dir(mc_dir, client_folder, cfg=cfg, manifest=manifest)
    log_path = cfgmod.config_dir() / "game.log"
    start_time = time.time()
    _status(
        f"Launching {vid} | nick: {cfg['nickname']} | RAM: {ram_mb} MB | folder: {game_dir.name}"
        if en else
        f"Запускаем {vid} | ник: {cfg['nickname']} | RAM: {ram_mb} МБ | папка: {game_dir.name}"
    )
    proc = mc.launch(
        mc_dir, vid, cfg["nickname"],
        srv.get("host"), srv.get("port"),
        ram_mb, log_path,
        cfg=cfg, server_java_version=manifest.get("java_version"),
        auto_join=bool(srv.get("auto_join", True)),
        client_folder=client_folder,
        manifest=manifest,
    )
    _status(f"Process started (PID {proc.pid})." if en else f"Процесс запущен (PID {proc.pid}).")

    if args.no_wait:
        return 0

    stopped_by_signal = [False]

    def _forward_stop(signum, _frame):
        stopped_by_signal[0] = True
        _status(f"Signal {signum} received, terminating game…" if en else f"Получен сигнал {signum}, завершаем игру…")
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
            on_ready=lambda: _status("Minecraft initialized! 🎮" if en else "Игра успешно инициализирована! 🎮"),
        )
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)

    if stopped_by_signal[0]:
        _status("Stopped by signal." if en else "Игра остановлена по сигналу.")
        return 0

    full_log, has_cr, _ = crash.collect_session_log(game_dir, log_path, start_time, lang=lang)
    if crash.is_crash(rc, full_log, has_crash_file=has_cr, timed_out=timed_out):
        report = crash.parse_crash(full_log, exit_code=rc, timed_out=timed_out, lang=lang)
        print(f"\n[CRASH] {report['title']} (exit code: {rc})", file=sys.stderr)
        print(f"  {report['summary']}", file=sys.stderr)
        if report["exception"]:
            print(f"  Exception: {report['exception']}", file=sys.stderr)
        if report["suspected_mods"]:
            print(f"  Suspected mods: {', '.join(report['suspected_mods'])}", file=sys.stderr)
        for tip in report["solutions"]:
            print(f"  * {tip}", file=sys.stderr)
        if args.share_crash:
            try:
                res = crash.upload_to_mclogs(
                    full_log,
                    mc_version=manifest["mc_version"],
                    loader=manifest["loader"],
                    exit_code=rc,
                    lang=lang,
                )
                print(f"  mclo.gs URL: {res['url']}", file=sys.stderr)
            except Exception as e:
                print(f"  mclo.gs upload failed: {e}", file=sys.stderr)
        return 124 if timed_out else 2

    _status("Minecraft closed normally." if en else "Игра закрыта штатно.")
    return 0
