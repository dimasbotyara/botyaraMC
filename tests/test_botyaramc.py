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
def test_java_detect_jvm_presets_ram_and_window_modes(isolated_env):
    mc_dir = isolated_env["mc_dir"]

    # 7. Автодетект системной Java
    javas = jvm.detect_java_installations(mc_dir)
    assert isinstance(javas, list)
    assert len(javas) >= 1
    assert javas[0]["major"] >= 8

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
    cfg["java_path"] = javas[0]["path"]
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

        # Wizard (все 3 шага)
        for step in (1, 2, 3):
            app.show("wizard", step)
            app.update()

        # Настройки
        app.show("settings")
        app.update()

        # Главное окно
        app.show("main")
        app.update()

        # Диалог папок, хоткеев, краш-репорта и полного лога
        app._open_folders_dialog()
        app.update()
        app._on_hotkey_escape()

        app._open_hotkeys_dialog()
        app.update()
        app._on_hotkey_escape()

        import tkinter as tk
        pvar = tk.StringVar(value="G1GC")
        app._open_presets_editor({}, pvar, lambda _n: None)
        app.update()
        app._on_hotkey_escape()

        rep = crash.parse_crash("java.lang.OutOfMemoryError: Java heap space", exit_code=1)
        app._open_crash_dialog(rep, "Full crash log text", {"mc_version": "1.20.1", "loader": "fabric"})
        app.update()
        app._open_log_window("Full crash log text", mc_version="1.20.1", loader="fabric", exit_code=1)
        app.update()
    finally:
        app.destroy()
