"""Полный набор автотестов для botyaraMC (сервер + лаунчер + CLI + краш-парсер + UI)."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
LAUNCHER_DIR = ROOT / "launcher"

sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(LAUNCHER_DIR))

import config as cfgmod  # noqa: E402
import crash  # noqa: E402
import jvm  # noqa: E402
import mc  # noqa: E402
import mods_index as M  # noqa: E402
import server as srv_http  # noqa: E402
import srv_config as C  # noqa: E402
import sync  # noqa: E402


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """Изолирует папки сервера и конфига лаунчера во временной директории."""
    cfg_dir = tmp_path / "launcher_cfg"
    cfg_dir.mkdir()
    monkeypatch.setenv("BOTYARAMC_CONFIG_DIR", str(cfg_dir))

    srv_base = tmp_path / "srv"
    srv_base.mkdir()
    mods_dir = srv_base / "mods"
    rp_dir = srv_base / "resourcepacks"
    cfg_file = srv_base / "config.txt"
    salt_file = srv_base / ".hide_salt"

    monkeypatch.setattr(C, "BASE", srv_base)
    monkeypatch.setattr(C, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(C, "MODS_DIR", mods_dir)
    monkeypatch.setattr(C, "RESOURCEPACKS_DIR", rp_dir)
    monkeypatch.setattr(C, "SALT_FILE", salt_file)
    monkeypatch.setattr(M, "MODS_DIR", mods_dir)
    monkeypatch.setattr(M, "RESOURCEPACKS_DIR", rp_dir)

    C.ensure_files()
    srv_http.rate_limiter.reset()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv_http.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    mc_dir = tmp_path / "dot_minecraft"
    mc_dir.mkdir()

    yield {
        "tmp": tmp_path,
        "port": port,
        "mods_dir": mods_dir,
        "rp_dir": rp_dir,
        "cfg_file": cfg_file,
        "mc_dir": mc_dir,
        "cfg_dir": cfg_dir,
    }
    httpd.shutdown()


# ------------------------------------------------------------------
# 1, 2, 3: Суммарный размер, синк ресурспаков (add-only), докачка .part
# ------------------------------------------------------------------
def test_plan_size_resumable_download_and_resourcepacks(isolated_env):
    port = isolated_env["port"]
    mods_dir = isolated_env["mods_dir"]
    rp_dir = isolated_env["rp_dir"]
    mc_dir = isolated_env["mc_dir"]

    mod_bytes = os.urandom(150_000)
    rp_bytes = os.urandom(90_000)
    (mods_dir / "sodium.jar").write_bytes(mod_bytes)
    (rp_dir / "server_pack.zip").write_bytes(rp_bytes)

    # Пользовательский ресурспак + совпадающее имя (которое НЕЛЬЗЯ затирать!)
    client_rp = mc_dir / "resourcepacks"
    client_rp.mkdir(parents=True)
    (client_rp / "my_custom_pack.zip").write_bytes(b"USER_CUSTOM_RP")
    (rp_dir / "existing_user.zip").write_bytes(b"SERVER_VERSION_DO_NOT_OVERWRITE")
    (client_rp / "existing_user.zip").write_bytes(b"USER_OWN_VERSION")

    mf = sync.fetch_manifest("127.0.0.1", port)
    assert len(mf["mods"]) == 1
    assert len(mf["resourcepacks"]) == 2

    # 1. Проверяем расчёт суммарного размера (existing_user.zip уже есть -> не качается!)
    plan = sync.plan_sync(mf, mc_dir)
    assert plan["mods_count"] == 1
    assert plan["rp_count"] == 1
    assert plan["total_bytes"] == len(mod_bytes) + len(rp_bytes)
    assert "КБ" in sync.format_size(plan["total_bytes"])
    assert sync.format_size(45 * 1024 * 1024) == "45 МБ"

    # 3. Имитируем прерванную на середине загрузку (50 000 байт уже лежат в .part)
    client_mods = mc_dir / "mods"
    client_mods.mkdir(parents=True)
    dst_mod = client_mods / "sodium.jar"
    part_file = client_mods / "sodium.jar.part"
    meta_file = client_mods / "sodium.jar.part.sha256"
    part_file.write_bytes(mod_bytes[:50_000])
    meta_file.write_text(hashlib.sha256(mod_bytes).hexdigest() + "\n", encoding="utf-8")

    # План должен уменьшиться ровно на 50 000 байт!
    plan_resumed = sync.plan_sync(mf, mc_dir)
    assert plan_resumed["total_bytes"] == (len(mod_bytes) - 50_000) + len(rp_bytes)

    # Проверяем прямой HTTP Range-запрос к серверу (206 Partial Content)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mods/sodium.jar",
        headers={"Range": "bytes=50000-"},
    )
    with urllib.request.urlopen(req) as r:
        assert r.status == 206
        tail = r.read()
        assert tail == mod_bytes[50_000:]

    # Полный синк докачивает оставшийся хвост и не трогает РП пользователя
    downloaded_chunks_sum = [0]
    ok = sync.sync(
        "127.0.0.1", port, mf["mods"], [client_mods],
        on_bytes=lambda n: downloaded_chunks_sum.__setitem__(0, downloaded_chunks_sum[0] + n),
    )
    assert ok is True
    # По сети должно было скачаться только недостающие 100 000 байт, а не все 150 000!
    assert downloaded_chunks_sum[0] == len(mod_bytes) - 50_000
    assert dst_mod.read_bytes() == mod_bytes
    assert not part_file.exists()

    ok_rp = sync.sync_resourcepacks("127.0.0.1", port, mf["resourcepacks"], client_rp)
    assert ok_rp is True
    assert (client_rp / "server_pack.zip").read_bytes() == rp_bytes
    assert (client_rp / "my_custom_pack.zip").read_bytes() == b"USER_CUSTOM_RP"
    assert (client_rp / "existing_user.zip").read_bytes() == b"USER_OWN_VERSION"

    # Удаляем ресурспак с сервера -> у клиента он остаётся нетронутым!
    (rp_dir / "server_pack.zip").unlink()
    mf2 = sync.fetch_manifest("127.0.0.1", port)
    sync.sync_resourcepacks("127.0.0.1", port, mf2["resourcepacks"], client_rp)
    assert (client_rp / "server_pack.zip").is_file()


# ------------------------------------------------------------------
# 4: Скрытие модов на сервере (words, hash и выборочный список)
# ------------------------------------------------------------------
def test_server_hide_mods_words_and_hash(isolated_env):
    port = isolated_env["port"]
    mods_dir = isolated_env["mods_dir"]
    cfg_file = isolated_env["cfg_file"]
    mc_dir = isolated_env["mc_dir"]

    secret_data = b"SUPER_SECRET_MOD_JAR"
    public_data = b"PUBLIC_MOD_JAR"
    (mods_dir / "secret_anticheat.jar").write_bytes(secret_data)
    (mods_dir / "jei.jar").write_bytes(public_data)

    # Режим words для всех модов
    cfg_file.write_text("hide_mods = words\njava_version = 21\n", encoding="utf-8")
    mf_words = sync.fetch_manifest("127.0.0.1", port)
    assert mf_words["mods_hidden"] is True
    assert mf_words["java_version"] == 21
    names_words = [m["name"] for m in mf_words["mods"]]
    assert "secret_anticheat.jar" not in names_words
    assert "jei.jar" not in names_words
    assert all(n.count("-") == 3 and n.endswith(".jar") for n in names_words)

    # Прямой запрос по настоящему имени должен отдавать 404!
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/mods/secret_anticheat.jar")
    assert exc_info.value.code == 404

    # Синхронизация скачивает скрытые моды под новыми именами
    assert sync.sync_all("127.0.0.1", port, mf_words, mc_dir) is True
    installed_1 = {p.name for p in (mc_dir / "mods").glob("*.jar")}
    assert installed_1 == set(names_words)

    # Переключаем сервер в режим hash -> клиент переименует локально по SHA-256 (0 байт по сети!)
    cfg_file.write_text("hide_mods = hash\n", encoding="utf-8")
    mf_hash = sync.fetch_manifest("127.0.0.1", port)
    names_hash = [m["name"] for m in mf_hash["mods"]]
    assert all(n.startswith("mod_") and n.endswith(".jar") for n in names_hash)

    plan_switch = sync.plan_sync(mf_hash, mc_dir)
    assert plan_switch["total_bytes"] == 0  # переиспользуются локальные файлы по SHA-256!

    assert sync.sync_all("127.0.0.1", port, mf_hash, mc_dir) is True
    installed_2 = {p.name for p in (mc_dir / "mods").glob("*.jar")}
    assert installed_2 == set(names_hash)

    # Выборочное скрытие: скрываем только secret_anticheat.jar, а jei.jar остаётся открытым!
    cfg_file.write_text("hide_mods = words\nhide_mods_list = secret_anticheat.jar\n", encoding="utf-8")
    mf_sel = sync.fetch_manifest("127.0.0.1", port)
    names_sel = [m["name"] for m in mf_sel["mods"]]
    assert "jei.jar" in names_sel
    assert "secret_anticheat.jar" not in names_sel
    assert len(names_sel) == 2


def test_real_midstream_disconnect_and_auto_resume(isolated_env):
    """Сервер обрывает TCP-соединение на половине файла -> клиент сохраняет .part и докачивает с Range!"""
    payload = os.urandom(120_000)
    sha = hashlib.sha256(payload).hexdigest()
    calls = []

    class FlakyRangeHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = self.headers.get("Range")
            calls.append(rng)
            if len(calls) == 1:
                # 1-я попытка: обещаем 120 000 байт, но обрываем сокет после 45 000!
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload[:45_000])
                self.wfile.flush()
                return
            # 2-я попытка: клиент должен прислать Range: bytes=45000-
            assert rng == "bytes=45000-"
            tail = payload[45_000:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes 45000-{len(payload) - 1}/{len(payload)}")
            self.send_header("Content-Length", str(len(tail)))
            self.end_headers()
            self.wfile.write(tail)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), FlakyRangeHandler)
    fport = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        dst = isolated_env["tmp"] / "flaky.jar"
        tmp = sync._download_resumable(
            f"http://127.0.0.1:{fport}/mods/flaky.jar",
            sha, len(payload), dst,
        )
        assert len(calls) == 2
        assert calls[0] is None
        assert calls[1] == "bytes=45000-"
        assert tmp.read_bytes() == payload
    finally:
        srv.shutdown()


# ------------------------------------------------------------------
# 7, 8, 9, 10: Автодетект Java, JVM-пресеты, Авто-RAM, Разрешение/Fullscreen
# ------------------------------------------------------------------
def _fake_java_probe(monkeypatch, fake_path):
    """Подмена probe_java для раннеров без обнаруженной системной Java."""
    monkeypatch.setattr(jvm, "probe_java",
                        lambda p: {"path": str(p), "major": 21, "label": "Java 21 • Fake"})


def test_java_detect_jvm_presets_ram_and_window_modes(isolated_env, monkeypatch):
    mc_dir = isolated_env["mc_dir"]

    # 7. Автодетект системной Java (на голых раннерах её может не быть — не падаем)
    javas = jvm.detect_java_installations(mc_dir)
    assert isinstance(javas, list)
    assert (not javas) or javas[0]["major"] >= 8

    # 9. Авто-RAM
    cfg = cfgmod.load()
    cfg["auto_ram"] = True
    auto_mb = cfgmod.effective_ram_mb(cfg)
    assert 2048 <= auto_mb <= 10240

    cfg["auto_ram"] = False
    cfg["ram_mb"] = 6144
    assert cfgmod.effective_ram_mb(cfg) == 6144

    # 8. JVM-пресеты (Aikar's, ZGC на Java 21 vs Java 11, свой пресет + доп. параметры)
    cfg["jvm_preset"] = "Aikar's Flags"
    cfg["extra_jvm_args"] = "-Dfile.encoding=UTF-8 -Dfoo=bar"
    args_aikar = jvm.build_jvm_arguments(cfg, 6144, java_major=21)
    assert "-Xmx6144M" in args_aikar
    assert "-XX:+ParallelRefProcEnabled" in args_aikar
    assert "-Dfile.encoding=UTF-8" in args_aikar

    cfg["jvm_preset"] = "ZGC"
    args_zgc21 = jvm.build_jvm_arguments(cfg, 4096, java_major=21)
    assert "-XX:+UseZGC" in args_zgc21
    assert "-XX:+ZGenerational" in args_zgc21

    # На старой Java 11 ZGC безопасно откатывается на G1GC
    args_zgc11 = jvm.build_jvm_arguments(cfg, 4096, java_major=11)
    assert "-XX:+UseG1GC" in args_zgc11
    assert "-XX:+UseZGC" not in args_zgc11

    # Пользовательский пресет
    cfg["custom_jvm_presets"] = {"МойПресет": "-XX:+UseG1GC -Dcustom.flag=1"}
    cfg["jvm_preset"] = "МойПресет"
    args_custom = jvm.build_jvm_arguments(cfg, 4096, java_major=17)
    assert "-Dcustom.flag=1" in args_custom

    # 10. Создаём тестовый client.json и проверяем Fullscreen / Своё разрешение / QuickPlay 1.20+
    ver_dir = mc_dir / "versions" / "1.20.1"
    ver_dir.mkdir(parents=True)
    fake_client = {
        "id": "1.20.1",
        "type": "release",
        "mainClass": "net.minecraft.client.main.Main",
        "libraries": [],
        "arguments": {
            "game": [
                "--username", "${auth_player_name}",
                "--uuid", "${auth_uuid}",
                {
                    "rules": [{"action": "allow", "features": {"has_custom_resolution": True}}],
                    "value": ["--width", "${resolution_width}", "--height", "${resolution_height}"],
                },
                {
                    "rules": [{"action": "allow", "features": {"is_quick_play_multiplayer": True}}],
                    "value": ["--quickPlayMultiplayer", "${quickPlayMultiplayer}"],
                },
            ],
            "jvm": ["-cp", "${classpath}"],
        },
    }
    (ver_dir / "1.20.1.json").write_text(json.dumps(fake_client), encoding="utf-8")

    cfg["java_mode"] = "manual"
    if javas:
        cfg["java_path"] = javas[0]["path"]
    else:
        fake_java = mc_dir / "fake_java" / "java"
        fake_java.parent.mkdir(parents=True, exist_ok=True)
        fake_java.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_java.chmod(0o755)
        _fake_java_probe(monkeypatch, fake_java)
        cfg["java_path"] = str(fake_java)
    cfg["window_mode"] = "fullscreen"
    cmd_fs = mc.build_command(mc_dir, "1.20.1", "Steve", server="26.1.2.3", port=25565, cfg=cfg)
    assert "--fullscreen" in cmd_fs
    assert "--quickPlayMultiplayer" in cmd_fs
    assert "26.1.2.3:25565" in cmd_fs

    cfg["window_mode"] = "custom"
    cfg["window_width"] = 1920
    cfg["window_height"] = 1080
    cmd_res = mc.build_command(mc_dir, "1.20.1", "Steve", cfg=cfg)
    assert "--width" in cmd_res and "1920" in cmd_res
    assert "--height" in cmd_res and "1080" in cmd_res


# ------------------------------------------------------------------
# 12, 13: Таймаут запуска + Краш-репорт-парсер + отправка на mclo.gs
# ------------------------------------------------------------------
def test_launch_timeout_and_crash_parser_and_mclogs(isolated_env, monkeypatch):
    tmp = isolated_env["tmp"]
    log_path = tmp / "game.log"

    # 12. Тест таймаута запуска на зависшем процессе
    with open(log_path, "wb") as lf:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=lf, stderr=subprocess.STDOUT,
        )
    rc, timed_out = mc.monitor_launch(proc, log_path, timeout_sec=1)
    assert timed_out is True
    rep_to = crash.parse_crash(log_path.read_text("utf-8"), exit_code=rc, timed_out=True)
    assert "таймаут" in rep_to["title"].lower()

    # 13a. OutOfMemoryError
    oom_log = "Exception in thread \"Render thread\" java.lang.OutOfMemoryError: Java heap space"
    rep_oom = crash.parse_crash(oom_log, exit_code=1)
    assert "OutOfMemoryError" in rep_oom["title"]

    # 13b. Неверная версия Java (class file version 65.0 -> Java 21)
    jv_log = (
        "java.lang.UnsupportedClassVersionError: net/fabricmc/loader/impl/launch/knot/KnotClient "
        "has been compiled by a more recent version of the Java Runtime (class file version 65.0)"
    )
    rep_jv = crash.parse_crash(jv_log, exit_code=1)
    assert "Java 21" in rep_jv["title"]

    # 13c. Конфликт модов / Mixin
    mix_log = (
        "org.spongepowered.asm.mixin.transformer.throwables.MixinTransformerError: "
        "An unexpected critical error was encountered in sodium-extra.mixins.json"
    )
    rep_mix = crash.parse_crash(mix_log, exit_code=1)
    assert "Mixin" in rep_mix["title"]
    assert "sodium-extra" in rep_mix["suspected_mods"]

    # 13d. Отправка на mclo.gs (поднимаем локальный мок mclo.gs API v1)
    received = {}

    class MockMclogsHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            ln = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(ln).decode("utf-8"))
            received.update(payload)
            resp = {
                "success": True,
                "id": "AbCd123",
                "url": "https://mclo.gs/AbCd123",
                "raw": "https://api.mclo.gs/1/raw/AbCd123",
                "errors": 1,
            }
            body = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    mock_srv = ThreadingHTTPServer(("127.0.0.1", 0), MockMclogsHandler)
    mport = mock_srv.server_address[1]
    threading.Thread(target=mock_srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(crash, "MCLOGS_POST_URL", f"http://127.0.0.1:{mport}/1/log")
        raw_log = "Path /home/secretuser/.minecraft --accessToken my_secret_token_123\nCrash!"
        res = crash.upload_to_mclogs(raw_log, mc_version="1.20.1", loader="fabric", exit_code=1)
        assert res["url"] == "https://mclo.gs/AbCd123"
        assert received["source"] == "botyaraMC"
        # Проверяем, что имя пользователя ОС и токен замаскированы перед отправкой!
        assert "secretuser" not in received["content"]
        assert "my_secret_token_123" not in received["content"]
        assert any(m["key"] == "mc_version" and m["value"] == "1.20.1" for m in received["metadata"])
    finally:
        mock_srv.shutdown()


# ------------------------------------------------------------------
# 11: CLI Auto-play без UI (--play --nick Steve)
# ------------------------------------------------------------------
def test_cli_autoplay_headless(isolated_env, monkeypatch):
    import cli

    port = isolated_env["port"]
    mc_dir = isolated_env["mc_dir"]
    mods_dir = isolated_env["mods_dir"]
    (mods_dir / "testmod.jar").write_bytes(b"JAR_BYTES_CLI")

    # Мокаем ensure_version и launch, чтобы не ходить в интернет к Mojang
    monkeypatch.setattr(mc, "ensure_version", lambda *a, **kw: "1.20.1")

    def fake_launch(mc_d, vid, nick, srv, prt, ram, log_path, **kw):
        Path(log_path).write_text("[Render thread/INFO]: LWJGL Version: 3.3.2\nAll good!\n", encoding="utf-8")
        return subprocess.Popen([sys.executable, "-c", "pass"])

    monkeypatch.setattr(mc, "launch", fake_launch)

    args = cli.build_parser().parse_args([
        "--play",
        "--nick", "Steve_CLI",
        "--server", f"127.0.0.1:{port}",
        "--mc-dir", str(mc_dir),
        "--auto-ram",
        "--timeout", "10",
    ])
    code = cli.run_cli(args)
    assert code == 0
    assert (mc_dir / "mods" / "testmod.jar").read_bytes() == b"JAR_BYTES_CLI"


# ------------------------------------------------------------------
# Smoke-тест всех окон UI (Wizard, Main, Settings, Crash, LogViewer, Folders, Presets)
# ------------------------------------------------------------------
@pytest.mark.skipif(
    sys.platform.startswith("linux") and not os.environ.get("DISPLAY"),
    reason="Требуется X11 / Xvfb для проверки виджетов CustomTkinter на Linux",
)
def test_ui_views_and_dialogs_smoke(isolated_env):
    import tkinter as tk
    import ui

    cfg = cfgmod.load()
    cfg["nickname"] = "DimasBot"
    cfg["sync_host"] = "127.0.0.1"
    cfg["sync_port"] = isolated_env["port"]
    cfg["mc_dir"] = str(isolated_env["mc_dir"])
    cfg["setup_done"] = True
    cfgmod.save(cfg)

    try:
        app = ui.App()
    except tk.TclError as e:
        pytest.skip(f"Графический дисплей недоступен в окружении CI: {e}")
    try:
        app.update()
        # Переключение тем на лету
        for tname in ("Gruvbox", "Ayu", "Monokai", "Catppuccin Latte", "Catppuccin Mocha"):
            app.apply_theme(tname)
            app.update()

        # Wizard (все 4 шага: язык -> ник -> тема -> сервер) на RU и EN
        for lang_code in ("ru", "en"):
            app.cfg["language"] = lang_code
            for step in (1, 2, 3, 4):
                app.show("wizard", step)
                app.update()

        # Настройки: проверяем отсутствие SegmentedButton и работу автосохранения
        app.show("settings")
        app.update()

        def _collect_classes(w):
            res = [type(w).__name__]
            for ch in w.winfo_children():
                res.extend(_collect_classes(ch))
            return res

        assert "CTkSegmentedButton" not in _collect_classes(app.view)

        # Диалог добавления сервера и подтверждения выхода из аккаунта
        app._open_add_server_dialog(lambda: None)
        app.update()
        app._on_hotkey_escape()

        app._confirm_signout_dialog()
        app.update()
        app._on_hotkey_escape()

        # Главное окно: прогрессбар скрыт по умолчанию, плавный hover кнопки ИГРАТЬ и автосмена приветствий
        app.show("main")
        app.update()
        assert app.progress.winfo_manager() == ""
        assert ui.GREETING_ROTATE_MS == 10 * 60 * 1000
        old_g = app._greeting
        app._rotate_greeting()
        app.update()
        assert app._greeting != old_g
        assert app.greeting_lbl.cget("text") == app._greeting
        assert app._greeting_job is not None
        app._animate_play_hover(1.0)
        app.update()
        app._animate_play_hover(0.0)
        app.update()

        # Диалог папок, хоткеев, краш-репорта и полного лога
        app._open_folders_dialog()
        app.update()
        app._on_hotkey_escape()

        app._open_hotkeys_dialog()
        app.update()
        app._on_hotkey_escape()

        pvar = tk.StringVar(value="G1GC")
        app._open_presets_editor({}, pvar, lambda _n: None)
        app.update()
        app._on_hotkey_escape()

        rep = crash.parse_crash("java.lang.OutOfMemoryError: Java heap space", exit_code=1, lang="en")
        assert "OutOfMemoryError" in rep["title"]
        app._open_crash_dialog(rep, "Full crash log text", {"mc_version": "1.20.1", "loader": "fabric"})
        app.update()
        app._open_log_window("Full crash log text", mc_version="1.20.1", loader="fabric", exit_code=1)
        app.update()
    finally:
        app.destroy()


# ------------------------------------------------------------------
# Новые тесты: old-mods, кэш mods/botyaraMC, delete_user_mods, rate-limit,
#              TUI/config RU+EN, client_folder, auto_join, валидация ника и ассеты
# ------------------------------------------------------------------
def test_old_mods_stash_multi_server_and_delete_user_mods(isolated_env):
    port = isolated_env["port"]
    mods_dir = isolated_env["mods_dir"]
    cfg_file = isolated_env["cfg_file"]
    mc_dir = isolated_env["mc_dir"]

    client_mods = mc_dir / "mods"
    client_mods.mkdir(parents=True)
    # До первого запуска botyaraMC в папке mods уже лежат старые чужие моды и подпапки
    (client_mods / "legacy_optifine.jar").write_bytes(b"LEGACY_MOD_1")
    (client_mods / "legacy_map.jar.disabled").write_bytes(b"LEGACY_DISABLED")
    (client_mods / "legacy_sub").mkdir()
    (client_mods / "legacy_sub" / "cfg.txt").write_text("hi", encoding="utf-8")

    mod_a = b"SERVER1_MOD_A_CONTENT"
    mod_b = b"SHARED_MOD_B_CONTENT"
    mod_c = b"SERVER2_MOD_C_CONTENT"
    (mods_dir / "mod_a.jar").write_bytes(mod_a)
    (mods_dir / "mod_b.jar").write_bytes(mod_b)

    mf1 = sync.fetch_manifest("127.0.0.1", port)
    assert sync.sync_all("127.0.0.1", port, mf1, mc_dir) is True

    # 1. Всё изначальное содержимое mods/ переехало в mods/old-mods/
    assert not (client_mods / "legacy_optifine.jar").exists()
    assert not (client_mods / "legacy_map.jar.disabled").exists()
    assert not (client_mods / "legacy_sub").exists()
    assert (client_mods / "old-mods" / "legacy_optifine.jar").read_bytes() == b"LEGACY_MOD_1"
    assert (client_mods / "old-mods" / "legacy_map.jar.disabled").read_bytes() == b"LEGACY_DISABLED"
    assert (client_mods / "old-mods" / "legacy_sub" / "cfg.txt").read_text("utf-8") == "hi"
    assert (client_mods / "mod_a.jar").read_bytes() == mod_a
    assert (client_mods / "mod_b.jar").read_bytes() == mod_b

    # 2. Переключаемся на "Сервер 2" (где вместо mod_a нужен mod_c) -> mod_a уходит в запас mods/botyaraMC/
    (mods_dir / "mod_a.jar").unlink()
    (mods_dir / "mod_c.jar").write_bytes(mod_c)
    mf2 = sync.fetch_manifest("127.0.0.1", port)
    assert sync.sync_all("127.0.0.1", port, mf2, mc_dir) is True

    assert not (client_mods / "mod_a.jar").exists()
    assert (client_mods / "botyaraMC" / "mod_a.jar").read_bytes() == mod_a
    assert (client_mods / "mod_c.jar").read_bytes() == mod_c

    # 3. Возвращаемся на "Сервер 1" -> mod_a достаётся из mods/botyaraMC/ без скачивания (0 байт по сети)!
    plan_back = sync.plan_sync(mf1, mc_dir)
    assert plan_back["total_bytes"] == 0
    assert sync.sync_all("127.0.0.1", port, mf2_to_1 := mf1, mc_dir) is True
    assert (client_mods / "mod_a.jar").read_bytes() == mod_a
    assert (client_mods / "botyaraMC" / "mod_c.jar").read_bytes() == mod_c

    # 4. Проверяем настройку delete_user_mods: false сохраняет моды игрока, true — удаляет
    (client_mods / "user_minimap.jar").write_bytes(b"USER_MINIMAP")
    cfg_file.write_text("delete_user_mods = false\n", encoding="utf-8")
    mf_keep = sync.fetch_manifest("127.0.0.1", port)
    assert mf_keep["delete_user_mods"] is False
    sync.sync_all("127.0.0.1", port, mf_keep, mc_dir)
    assert (client_mods / "user_minimap.jar").is_file()

    cfg_file.write_text("delete_user_mods = true\n", encoding="utf-8")
    mf_del = sync.fetch_manifest("127.0.0.1", port)
    assert mf_del["delete_user_mods"] is True
    sync.sync_all("127.0.0.1", port, mf_del, mc_dir)
    assert not (client_mods / "user_minimap.jar").exists()


def test_rate_limiting_server_config_tui_auto_join_and_client_folder(isolated_env, monkeypatch):
    import tui

    port = isolated_env["port"]
    cfg_file = isolated_env["cfg_file"]
    mc_dir = isolated_env["mc_dir"]

    # Проверяем двуязычное сохранение конфига сервера и TUI-валидаторы
    srv_cfg = C.load()
    srv_cfg.update({
        "language": "en",
        "server_name": "Cosy Friends SMP",
        "client_folder": "cosy_smp",
        "auto_join": False,
        "rate_limit_per_min": 5,
    })
    C.save(srv_cfg, lang="en")
    raw_txt = cfg_file.read_text("utf-8")
    assert "botyaraMC sync-server configuration" in raw_txt
    assert tui._validate_port("25456", "en") is True
    assert isinstance(tui._validate_port("99999", "en"), str)

    # Проверяем /manifest: поля server_name, client_folder, auto_join и rate limit (429)
    srv_http.rate_limiter.reset()
    mf = sync.fetch_manifest("127.0.0.1", port)
    assert mf["server_name"] == "Cosy Friends SMP"
    assert mf["client_folder"] == "cosy_smp"
    assert mf["server"]["auto_join"] is False

    # Исчерпываем лимит 5 запросов/мин с одного IP -> получаем 429 Too Many Requests
    got_429 = False
    for _ in range(8):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=3).read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                got_429 = True
                assert e.headers.get("Retry-After") is not None
                break
    assert got_429 is True

    # Возвращаем нормальный лимит
    srv_cfg["rate_limit_per_min"] = 300
    C.save(srv_cfg, lang="ru")
    srv_http.rate_limiter.reset()

    # Проверяем изолированную папку клиента (.minecraft/instances/cosy_smp) и auto_join
    resolved = cfgmod.resolve_game_dir(mc_dir, "cosy_smp")
    assert resolved == mc_dir / "instances" / "cosy_smp"

    ver_dir = mc_dir / "versions" / "1.20.1"
    ver_dir.mkdir(parents=True, exist_ok=True)
    fake_client = {
        "id": "1.20.1",
        "type": "release",
        "mainClass": "net.minecraft.client.main.Main",
        "libraries": [],
        "arguments": {
            "game": [
                "--username", "${auth_player_name}",
                "--gameDir", "${game_directory}",
                {
                    "rules": [{"action": "allow", "features": {"is_quick_play_multiplayer": True}}],
                    "value": ["--quickPlayMultiplayer", "${quickPlayMultiplayer}"],
                },
            ],
            "jvm": ["-cp", "${classpath}"],
        },
    }
    (ver_dir / "1.20.1.json").write_text(json.dumps(fake_client), encoding="utf-8")

    javas = jvm.detect_java_installations(mc_dir)
    lcfg = cfgmod.load()
    lcfg["java_mode"] = "manual"
    if javas:
        lcfg["java_path"] = javas[0]["path"]
    else:
        fake_java2 = mc_dir / "fake_java" / "java"
        fake_java2.parent.mkdir(parents=True, exist_ok=True)
        fake_java2.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_java2.chmod(0o755)
        _fake_java_probe(monkeypatch, fake_java2)
        lcfg["java_path"] = str(fake_java2)
    lcfg["sync_host"] = "26.55.66.77"

    # auto_join=False -> НЕТ --quickPlayMultiplayer
    cmd_no_join = mc.build_command(
        mc_dir, "1.20.1", "Steve",
        server="127.0.0.1", port=25565, cfg=lcfg,
        auto_join=False, client_folder="cosy_smp",
    )
    assert "--quickPlayMultiplayer" not in cmd_no_join
    assert str(resolved) in cmd_no_join

    # auto_join=True и server=127.0.0.1 при внешнем sync_host -> подставляется 26.55.66.77:25565!
    cmd_join = mc.build_command(
        mc_dir, "1.20.1", "Steve",
        server="127.0.0.1", port=25565, cfg=lcfg,
        auto_join=True, client_folder="cosy_smp",
    )
    assert "--quickPlayMultiplayer" in cmd_join
    assert "26.55.66.77:25565" in cmd_join


def test_nickname_validation_greetings_multi_server_signout_and_assets(isolated_env):
    import cli
    import i18n

    # Проверяем строгую валидацию IP/хоста (неполный IPv4 при посимвольном вводе не считается валидным)
    assert cli.parse_hostport("2") is None
    assert cli.parse_hostport("26.12.") is None
    assert cli.parse_hostport("26.12.34.999") is None
    assert cli.parse_hostport("26.12.34.56") == ("26.12.34.56", 25456)
    assert cli.parse_hostport("play.example.com:25500") == ("play.example.com", 25500)

    # 14. Строгая валидация ника (3-16 символов, только a-zA-Z0-9_, без пробелов и дефисов)
    assert i18n.validate_nickname("Steve_2026", "ru")[0] is True
    assert i18n.validate_nickname("abc", "en")[0] is True
    for bad in ("", "ab", "a" * 17, "Steve 1", " Steve", "Steve-1", "Steve.1", "Стив", "nick!"):
        ok_ru, msg_ru = i18n.validate_nickname(bad, "ru")
        ok_en, msg_en = i18n.validate_nickname(bad, "en")
        assert ok_ru is False and msg_ru
        assert ok_en is False and msg_en

    # 7. Приветствия зависят от времени суток (утро/день/вечер/ночь), без майнкрафт-тематики
    assert i18n.get_time_period(8) == "morning"
    assert i18n.get_time_period(14) == "afternoon"
    assert i18n.get_time_period(19) == "evening"
    assert i18n.get_time_period(2) == "night"

    mc_words = ("крипер", "алмаз", "кирк", "незер", "эндер", "creeper", "diamond", "pickaxe", "nether", "enderm")
    for lg in ("ru", "en"):
        for period, templates in i18n.GREETINGS_BY_TIME[lg].items():
            assert len(templates) >= 25
            for tpl in templates:
                low_tpl = tpl.lower()
                assert not any(w in low_tpl for w in mc_words), f"Minecraft reference in {period}: {tpl}"

    seen_morning = {i18n.random_greeting("Dimas", "ru", hour=9) for _ in range(30)}
    seen_night = {i18n.random_greeting("Dimas", "en", hour=2) for _ in range(30)}
    assert len(seen_morning) >= 8
    assert len(seen_night) >= 8
    # При пустом имени {name} аккуратно убирается без лишних запятых
    no_name = i18n.format_greeting_template("Доброе утро, {name}!", "")
    assert no_name == "Доброе утро!"

    # 12 & 13. Мульти-серверы и выход из аккаунта со сбросом серверов
    cfg = cfgmod.load()
    cfg["nickname"] = "Dimas"
    cfg["setup_done"] = True
    s1 = cfgmod.add_or_select_server(cfg, "26.1.1.1", 25456, name="Vanilla+")
    s2 = cfgmod.add_or_select_server(cfg, "26.2.2.2", 25456, name="Create Tech")
    assert len(cfg["servers"]) == 2
    assert cfg["active_server_id"] == s2["id"]
    assert cfg["sync_host"] == "26.2.2.2"

    cfgmod.add_or_select_server(cfg, "26.1.1.1", 25456)
    assert cfg["active_server_id"] == s1["id"]
    assert cfg["sync_host"] == "26.1.1.1"

    cfgmod.remove_server(cfg, s1["id"])
    assert len(cfg["servers"]) == 1
    assert cfg["sync_host"] == "26.2.2.2"

    cfgmod.reset_account_and_servers(cfg)
    assert cfg["setup_done"] is False
    assert cfg["nickname"] == ""
    assert cfg["servers"] == []
    assert cfg["sync_host"] == ""

    # 10 & 18. Проверяем русский баннер (без "Range-докачка") и иконку 1080x1080
    ru_svg = ROOT / "assets" / "banner.ru.svg"
    ru_png = ROOT / "assets" / "banner.ru.png"
    ico_1080 = ROOT / "assets" / "icon_1080p.png"
    svg_text = ru_svg.read_text("utf-8")
    assert ru_svg.is_file() and "Минималистичный лаунчер" in svg_text
    assert "Умная докачка" in svg_text and "Range-докачка" not in svg_text
    assert ru_png.is_file() and ru_png.stat().st_size > 10_000
    assert ico_1080.is_file()
    ihdr = ico_1080.read_bytes()[16:24]
    w = int.from_bytes(ihdr[0:4], "big")
    h = int.from_bytes(ihdr[4:8], "big")
    assert (w, h) == (1080, 1080)



# ============================================================
# Регрессии по внешнему ревью (хост-режим, rename, дубли, mll)
# ============================================================

def test_regression_host_validation_and_rename_signatures(tmp_path, monkeypatch):
    """Ревью #1/#2: сигнатуры config-функций и вызовы из UI должны совпадать."""
    cfg_dir = tmp_path / "cfg"; cfg_dir.mkdir()
    monkeypatch.setenv("BOTYARAMC_CONFIG_DIR", str(cfg_dir))
    cfg = cfgmod.load()
    cfgmod.add_or_select_server(cfg, "127.0.0.1", 25456, name="TestSrv")
    sid = cfg["active_server_id"]
    mc_dir = tmp_path / ".minecraft"; mc_dir.mkdir()
    host_dir = tmp_path / "hostmods"; host_dir.mkdir()

    # validate_unique_host_dir(cfg, server_id, candidate_dir) — без TypeError
    ok, _dup = cfgmod.validate_unique_host_dir(cfg, sid, str(host_dir))
    assert ok is True
    # is_sync_server_own_mods_dir(path) — ровно 1 аргумент
    assert cfgmod.is_sync_server_own_mods_dir(str(host_dir)) is False

    # rename_server_folder(cfg, mc_dir, name, server_id=...) -> (True, Path)
    ok_r, res_r = cfgmod.rename_server_folder(cfg, mc_dir, "MyPack", server_id=sid)
    assert ok_r is True and Path(res_r).name == "MyPack"
    srv = cfgmod.active_server(cfgmod.load())
    assert srv["custom_folder"] == "MyPack"
    # плохое имя и занятая папка возвращают (False, код), а не падают
    ok_b, code_b = cfgmod.rename_server_folder(cfg, mc_dir, "bad/name", server_id=sid)
    assert ok_b is False and code_b == "bad_name"


def test_regression_no_duplicate_methods_in_ui():
    """Ревью #7: в классе App не должно быть продублированных методов."""
    import ast
    tree = ast.parse((LAUNCHER_DIR / "ui.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            dups = {n for n in names if names.count(n) > 1}
            assert not dups, f"дубли методов в {node.name}: {dups}"


def test_regression_server_name_sanitized_for_config_txt():
    """Ревью #8: перевод строки в имени сервера не должен ломать config.txt."""
    out = C.render_config({"server_name": "Cool\nServer = hacked", "language": "en"}, lang="en")
    name_lines = [ln for ln in out.splitlines() if ln.startswith("server_name")]
    assert name_lines == ["server_name = Cool Server = hacked"]


def test_regression_quick_play_json_features(tmp_path):
    """Ревью #14: quickPlay определяется по JSON-features, а не по подстроке."""
    vdir = tmp_path / "versions" / "1.20.1"; vdir.mkdir(parents=True)
    (vdir / "1.20.1.json").write_text(json.dumps(
        {"features": {"is_quick_play_multiplayer": True}}), encoding="utf-8")
    assert mc._supports_quick_play_multiplayer(tmp_path, "1.20.1") is True
    (vdir / "1.20.1.json").write_text(json.dumps(
        {"comment": "is_quick_play_multiplayer mentioned in a comment"}), encoding="utf-8")
    assert mc._supports_quick_play_multiplayer(tmp_path, "1.20.1") is False


def test_regression_tui_validators_not_swapped():
    """Внешнее замечание: валидатор версии не должен стоять на имени сервера."""
    import tui as srv_tui
    # Имя сервера — обычная строка, НЕ обязана выглядеть как версия
    assert srv_tui.validate_server_name("My Server") is True
    assert srv_tui.validate_server_name("Сервер друзей") is True
    assert srv_tui.validate_server_name("   ") == "!"
    # Версия Minecraft — строгий формат
    assert srv_tui.validate_mc_version("1.20.1") is True
    assert srv_tui.validate_mc_version("1.21") is True
    assert srv_tui.validate_mc_version("My Server") == "!"
    assert srv_tui.validate_mc_version("") == "!"


def test_regression_alias_map_is_stable_when_mods_added(tmp_path, monkeypatch):
    """Ревью-2 #1: алиас скрытого мода не должен меняться при добавлении соседних модов."""
    import mods_index as MI
    mods_dir = tmp_path / "mods"; mods_dir.mkdir()
    monkeypatch.setattr(MI, "MODS_DIR", mods_dir)
    monkeypatch.setattr(MI, "_ALIASES_FILE", tmp_path / ".hide_aliases.json")
    monkeypatch.setattr(MI.C, "get_hide_salt", lambda: "test-salt")
    MI._cache.clear()
    cfg = {"hide_mods": "words", "hide_mods_list": []}
    for name in ("alpha.jar", "beta.jar", "gamma.jar"):
        (mods_dir / name).write_bytes(b"jar-" + name.encode())
    first = {m["name"] for m in MI.scan_mods(cfg)}
    assert len(first) == 3 and not ({"alpha.jar", "beta.jar", "gamma.jar"} & first)
    (mods_dir / "aaa-new.jar").write_bytes(b"jar-new")  # сортируется первым
    second = {m["name"] for m in MI.scan_mods(cfg)}
    assert first <= second and len(second) == 4  # старые алиасы не перетасовались


def test_regression_hide_list_with_comma_roundtrip():
    """Ревью-2 #3: имя мода с запятой переживает render->load через JSON."""
    assert C.parse_hide_list(C.format_hide_list(["foo,bar.jar", "x.jar"])) == ["foo,bar.jar", "x.jar"]
    assert C.parse_hide_list("a.jar, b.jar") == ["a.jar", "b.jar"]  # старый формат
    out = C.render_config({"hide_mods_list": ["foo,bar.jar"], "language": "en"}, lang="en")
    assert 'hide_mods_list = ["foo,bar.jar"]' in out


# ------------------------------------------------------------------
# 12: HTTP/1.1 keep-alive, ETag/304, суффиксные Range и If-Range
# ------------------------------------------------------------------
def test_server_http11_etag_suffix_range_and_keepalive(isolated_env):
    import http.client

    port = isolated_env["port"]
    mods_dir = isolated_env["mods_dir"]
    data = b"A" * 100_000 + b"B" * 50_000
    (mods_dir / "range.jar").write_bytes(data)

    # Суффиксный Range bytes=-N (последние N байт, RFC 7233)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mods/range.jar", headers={"Range": "bytes=-5000"})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206
        assert r.read() == data[-5000:]

    # bytes=-0 неудовлетворим -> 416
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/mods/range.jar", headers={"Range": "bytes=-0"}))
    assert ei.value.code == 416

    # ETag + If-None-Match -> лёгкий 304 без тела
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/mods/range.jar") as r1:
        etag = r1.headers.get("ETag")
        r1.read()
    assert etag
    with pytest.raises(urllib.error.HTTPError) as ei2:
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/mods/range.jar", headers={"If-None-Match": etag}))
    assert ei2.value.code == 304

    # If-Range с чужим ETag: файл менялся -> безопасная полная отдача 200
    req3 = urllib.request.Request(
        f"http://127.0.0.1:{port}/mods/range.jar",
        headers={"Range": "bytes=100000-", "If-Range": '"stale-etag"'})
    with urllib.request.urlopen(req3) as r3:
        assert r3.status == 200
        assert r3.read() == data

    # Мульти-рейндж не поддерживается и не должен давать 416: игнорируем -> 200
    req4 = urllib.request.Request(
        f"http://127.0.0.1:{port}/mods/range.jar", headers={"Range": "bytes=0-1,5-9"})
    with urllib.request.urlopen(req4) as r4:
        assert r4.status == 200
        assert r4.read() == data

    # keep-alive: два запроса через одно TCP-соединение (HTTP/1.1)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/ping")
    resp1 = conn.getresponse()
    assert resp1.status == 200 and resp1.read()
    conn.request("GET", "/ping")
    resp2 = conn.getresponse()
    assert resp2.status == 200 and resp2.read()
    conn.close()

    # /manifest тоже кэшируется по ETag
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/manifest") as rm:
        metag = rm.headers.get("ETag")
        rm.read()
    assert metag
    with pytest.raises(urllib.error.HTTPError) as ei3:
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/manifest", headers={"If-None-Match": metag}))
    assert ei3.value.code == 304


# ------------------------------------------------------------------
# 13: Валидация манифеста, кэш манифестов + кросс-запусковый кэш SHA-256
# ------------------------------------------------------------------
_STUB = {"body": {}}


def test_manifest_validation_cache_and_hash_persistence(isolated_env):
    # save_cache/load_cache roundtrip с ETag (офлайн-режим CLI зависит от стабильного id)
    mf = {"app": "botyaraMC", "server_name": "S", "mc_version": "1.20.1", "loader": "fabric",
          "client_folder": "", "delete_user_mods": False,
          "server": {"host": "127.0.0.1", "port": 25565, "auto_join": True},
          "mods": [], "resourcepacks": [], "background": None, "java_version": None,
          "mods_hidden": False, "_etag": '"abc123"'}
    cfgmod.save_cache(mf, server_id="srvA")
    loaded = cfgmod.load_cache(server_id="srvA")
    assert loaded and loaded["mc_version"] == "1.20.1" and loaded["_etag"] == '"abc123"'
    assert cfgmod.load_cache(server_id="srvB") is None  # чужой кэш не подтекает

    # Заглушка сервера для валидации fetch_manifest
    class StubHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps(_STUB["body"]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd2 = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    stub_port = httpd2.server_address[1]
    t2 = threading.Thread(target=httpd2.serve_forever, daemon=True)
    t2.start()
    try:
        # Манифест без mc_version отвергается (раньше падал KeyError дальше по коду)
        _STUB["body"] = {"app": "botyaraMC", "loader": "fabric", "mods": []}
        with pytest.raises(ValueError):
            sync.fetch_manifest("127.0.0.1", stub_port)

        # Одна кривая запись не убивает весь список; битый порт -> дефолт
        _STUB["body"] = {
            "app": "botyaraMC", "mc_version": "1.20.1", "loader": "fabric",
            "mods": ["oops", 42,
                     {"name": "good.jar", "sha256": "A" * 64, "size": 5}],
            "server": {"port": "bad"},
        }
        mf2 = sync.fetch_manifest("127.0.0.1", stub_port)
        assert [m["name"] for m in mf2["mods"]] == ["good.jar"]
        assert mf2["server"]["port"] == 25565
    finally:
        httpd2.shutdown()

    # Кросс-запусковый кэш SHA-256: файл не пересчитывается после flush + reload
    hdir = isolated_env["mc_dir"] / "hcache"
    hdir.mkdir(parents=True, exist_ok=True)
    hp = hdir / "mod.jar"
    hp.write_bytes(b"CACHE_ME_BYTES")
    sha1 = sync.file_sha256(hp)
    sync.flush_hash_cache()
    assert (isolated_env["cfg_dir"] / "hash_cache.json").is_file()
    sync._hash_cache.clear()
    sync._disk_hash_cache = None  # имитация нового запуска процесса
    assert sync.file_sha256(hp) == sha1
    hp.write_bytes(b"CHANGED CONTENT")
    assert sync.file_sha256(hp) != sha1
    sync.flush_hash_cache()


# ------------------------------------------------------------------
# 14: Параллельные загрузки + паритет защиты пользовательских модов
# ------------------------------------------------------------------
def test_parallel_downloads_and_user_mod_parity(isolated_env):
    port = isolated_env["port"]
    mods_dir = isolated_env["mods_dir"]
    mc_dir = isolated_env["mc_dir"]
    names = [f"pmod{i}.jar" for i in range(8)]
    for i, n in enumerate(names):
        (mods_dir / n).write_bytes(bytes([65 + i]) * (10_000 + i))

    mf = sync.fetch_manifest("127.0.0.1", port)
    assert len(mf["mods"]) == 8
    client_mods = mc_dir / "mods"
    client_mods.mkdir()
    got = [0]
    ok = sync.sync("127.0.0.1", port, mf["mods"], [client_mods],
                   on_bytes=lambda n: got.__setitem__(0, got[0] + n))
    assert ok is True
    for i, n in enumerate(names):
        assert (client_mods / n).read_bytes() == bytes([65 + i]) * (10_000 + i)
    assert got[0] == sum(10_000 + i for i in range(8))  # по сети ушло ровно столько байт

    # Файл игрока jei.jar (добавленный ПОСЛЕ первого синка) уезжает в old-mods/
    # вместо молчаливой перезаписи — паритет с ресурспаками.
    (client_mods / "jei.jar").write_bytes(b"USER_JEI_V1")
    (mods_dir / "jei.jar").write_bytes(b"SERVER_JEI_V1")
    mf3 = sync.fetch_manifest("127.0.0.1", port)
    ok3 = sync.sync("127.0.0.1", port, mf3["mods"], [client_mods])
    assert ok3 is True
    assert (client_mods / "jei.jar").read_bytes() == b"SERVER_JEI_V1"
    moved = list((client_mods / "old-mods").glob("jei*.jar"))
    assert any(m.read_bytes() == b"USER_JEI_V1" for m in moved)


# ------------------------------------------------------------------
# 15: IPv6 в parse_hostport / resolve_mc_server_target + sanitize_client_folder
# ------------------------------------------------------------------
def test_ipv6_parsing_and_folder_sanitize():
    import cli

    assert cli.parse_hostport("[::1]:25456") == ("[::1]", 25456)
    assert cli.parse_hostport("[2001:db8::1]") == ("[2001:db8::1]", 25456)
    assert cli.parse_hostport("26::1") is None          # bare IPv6 больше не склеивается в host:port
    assert cli.parse_hostport("host:abc") is None
    assert cli.parse_hostport("26.12.34.56:1234") == ("26.12.34.56", 1234)
    assert cli.parse_hostport("play.example.com") == ("play.example.com", 25456)

    h, p = mc.resolve_mc_server_target("[::1]:25565", 1)
    assert (h, p) == ("::1", 25565)
    h2, p2 = mc.resolve_mc_server_target("26.12.34.56:30000", 1)
    assert (h2, p2) == ("26.12.34.56", 30000)

    # Windows-зарезервированные имена и хвостовые точки не проходят санитизацию
    assert cfgmod.sanitize_client_folder("con") == ""
    assert cfgmod.sanitize_client_folder("nul") == ""
    assert cfgmod.sanitize_client_folder("com1") == ""
    assert cfgmod.sanitize_client_folder("pack.") == ""
    assert cfgmod.sanitize_client_folder("Fabric-1.16") == "Fabric-1.16"


# ------------------------------------------------------------------
# 16: Валидация config.txt сервера, кэш load() и права на соль
# ------------------------------------------------------------------
def test_server_config_validation_and_cache(isolated_env):
    cfg_file = isolated_env["cfg_file"]
    cfg_file.write_text(
        "http_port = 0\ndiscovery_port = 70000\n"
        "minecraft_server = 'not a (valid) addr!!'\nrate_limit_per_min = -5\n",
        encoding="utf-8",
    )
    cfg = C.load()
    assert cfg["http_port"] == 25456      # 0/70000 -> дефолт вместо случайного порта
    assert cfg["discovery_port"] == 25457
    assert cfg["minecraft_server"] == "auto"  # мусор не уезжает клиентам
    assert cfg["rate_limit_per_min"] == 300

    # load() возвращает копию: мутации вызывающего не портят кэш
    cfg["server_name"] = "MUTATED"
    cfg2 = C.load()
    assert cfg2["server_name"] != "MUTATED"

    # Соль cloaking приватная (0600) и стабильна между вызовами
    C._salt_cache.clear()
    s1 = C.get_hide_salt()
    s2 = C.get_hide_salt()
    assert s1 == s2 and len(s1) >= 16
    if not sys.platform.startswith("win"):
        assert (C.SALT_FILE.stat().st_mode & 0o777) == 0o600


# ------------------------------------------------------------------
# 17: Параллельные записи config.json + robustness i18n / crash
# ------------------------------------------------------------------
def test_concurrent_config_save_and_i18n_robustness(isolated_env):
    import i18n

    cfg = cfgmod.load()
    cfg["nickname"] = "starter"
    cfgmod.save(cfg)

    errs = []

    def writer(i):
        try:
            c2 = cfgmod.load()
            c2["nickname"] = f"user{i}"
            cfgmod.save(c2)
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errs == []
    final = cfgmod.load()
    assert final["nickname"].startswith("user")  # config.json не порвался

    # tr(): битый плейсхолдер не роняет построение UI
    assert i18n.tr("en", "no_such_key_xyz") == "no_such_key_xyz"
    assert i18n.tr("en", "log_lines", wrong_kwarg=1) == "{n} lines"
    assert i18n.tr("en", "log_lines", n=7) == "7 lines"

    # Приветствие без ника не оставляет хвост перед пунктуацией
    assert i18n.format_greeting_template("Morning {name} is the best {name}!") == "Morning is the best!"
    assert sync.format_size(45 * 1024 * 1024, lang="en") == "45 MB"


def test_crash_privacy_and_mclogs_json_robustness(monkeypatch):
    # Пути без хвостового разделителя и не-C: диски тоже скрабятся
    scrubbed = crash.sanitize_and_truncate_for_mclogs(
        "user.home=/home/john\nCannot access C:\\Users\\John\npath=D:\\Users\\Ann\\x.txt")
    assert "/home/john" not in scrubbed
    assert "/home/********" in scrubbed
    assert "Users\\John" not in scrubbed and "Users\\Ann" not in scrubbed

    # 200 с HTML (кэптивный портал) -> внятный RuntimeError, а не сырой JSONDecodeError
    class FakeHtmlResp:
        headers = {}

        def read(self):
            return b"<html>Sign in to wifi</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(crash.urllib.request, "urlopen", lambda req, timeout=0: FakeHtmlResp())
    with pytest.raises(RuntimeError, match="non-JSON|не-JSON"):
        crash.upload_to_mclogs("log text", lang="en")

    # Токен удаления сохраняется: без него лог с личными данными не убрать с mclo.gs
    class FakeJsonResp(FakeHtmlResp):
        def read(self):
            return json.dumps({
                "success": True, "url": "https://mclo.gs/abc", "id": "abc",
                "raw": "https://api.mclo.gs/1/raw/abc", "errors": 0, "token": "TOK123",
            }).encode("utf-8")

    monkeypatch.setattr(crash.urllib.request, "urlopen", lambda req, timeout=0: FakeJsonResp())
    res = crash.upload_to_mclogs("log text", lang="en")
    assert res["url"] == "https://mclo.gs/abc"
    assert res["delete_token"] == "TOK123"


def test_unsupported_loader_fails_loudly(isolated_env):
    # optifine/мусорные загрузчики честно падают, а не ставят молча ваниллу
    with pytest.raises(RuntimeError):
        mc.ensure_version(isolated_env["mc_dir"], "1.20.1", "optifine")


# ------------------------------------------------------------------
# 18: Встроенные шрифты (Inter / JetBrains Mono) — файлы, лицензии, загрузчик
# ------------------------------------------------------------------
def test_bundled_fonts_files_licenses_and_loader(isolated_env, tmp_path):
    import fonts

    assert fonts.FONTS_DIR.is_dir()
    for name in fonts.FONT_FILES:
        p = fonts.FONTS_DIR / name
        assert p.is_file() and p.stat().st_size > 50_000
        assert p.read_bytes()[:4] == b"\x00\x01\x00\x00"  # валидный TTF

    for lic in ("OFL-Inter.txt", "OFL-JetBrainsMono.txt"):
        text = (fonts.FONTS_DIR / lic).read_text(encoding="utf-8", errors="ignore")
        assert "Open Font License" in text

    # Загрузчик: не падает и помечает себя загруженным (фолбэк на системные шрифты безопасен)
    assert fonts.ensure_loaded() is True
    assert fonts.ensure_loaded() is True  # идемпотентно

    # Linux-установка во временную директорию: файлы копируются 1:1
    dst_root = tmp_path / "userfonts"
    fonts._install_linux([fonts.FONTS_DIR / n for n in fonts.FONT_FILES], target_dir=dst_root / "fonts" / "botyaraMC")
    for name in fonts.FONT_FILES:
        copied = dst_root / "fonts" / "botyaraMC" / name
        assert copied.is_file()
        assert copied.stat().st_size == (fonts.FONTS_DIR / name).stat().st_size

    # resolve_families вне Tk возвращает безопасные фолбэки
    ui_fam, mono_fam = fonts.resolve_families(None)
    assert ui_fam is None and mono_fam is None
