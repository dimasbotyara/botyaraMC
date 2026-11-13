"""botyaraMC sync-server. Запуск: python server.py | Настройка TUI: python tui.py"""
import collections
import hashlib
import json
import os
import re
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import discovery
import mods_index as M
import srv_config as C

# start и end могут быть пустыми: bytes=500- (хвост), bytes=-500 (последние N байт).
# Мультирейнджи (bytes=0-1,5-9) не матчатся и потому игнорируются (отдаём 200 целиком).
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _log_err(msg):
    print(f"[!] {msg}", file=sys.stderr, flush=True)


class RateLimiter:
    """Потокобезопасный скользящий лимит запросов за 60 секунд на один IP."""

    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()
        self._last_gc = 0.0

    def allow(self, ip, limit_per_min):
        if not limit_per_min or limit_per_min <= 0:
            return True
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            if now - self._last_gc > 120.0:
                self._last_gc = now
                stale = [k for k, dq in self._hits.items() if not dq or dq[-1] < cutoff]
                for k in stale:
                    del self._hits[k]
            dq = self._hits.get(ip)
            if dq is None:
                dq = collections.deque()
                self._hits[ip] = dq
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit_per_min:
                return False
            dq.append(now)
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


def _etag_match(inm_header, etag):
    """If-None-Match: '*' или список тегов (с опциональным префиксом W/)."""
    inm = (inm_header or "").strip()
    if not inm:
        return False
    if inm == "*":
        return True
    for tag in inm.split(","):
        tag = tag.strip()
        if tag.startswith("W/"):
            tag = tag[2:]
        if tag == etag:
            return True
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "botyaraMC-sync"
    sys_version = ""            # не светим версию Python в заголовке Server
    protocol_version = "HTTP/1.1"  # keep-alive: одно TCP-соединение на много запросов
    timeout = 60                # «мертвые» соединения не держат потоки вечно

    def log_message(self, fmt, *args):  # тишина в консоли
        pass

    def send_response(self, code, message=None):
        self._resp_started = True
        super().send_response(code, message)

    def _json(self, obj, code=200, head_only=False, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if extra_headers:
            for hk, hv in extra_headers.items():
                self.send_header(hk, hv)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _json_cached(self, obj, head_only=False, extra_headers=None):
        """JSON с ETag: повторный запрос с If-None-Match получает лёгкий 304 вместо тела."""
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        etag = f'"{hashlib.sha1(body).hexdigest()}"'
        if _etag_match(self.headers.get("If-None-Match"), etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        self._json(obj, head_only=head_only, extra_headers={**(extra_headers or {}), "ETag": etag})

    def _send_416(self, total):
        self.send_response(416)
        self.send_header("Content-Range", f"bytes */{total}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_file(self, path, content_type, head_only=False):
        """Раздача файла: Range/206 + суффиксные байты, ETag/If-Range, 304 и защита от усечения."""
        try:
            f = open(path, "rb")
        except OSError:
            self._json({"error": "not found"}, 404, head_only=head_only)
            return

        with f:
            st = os.fstat(f.fileno())
            total = st.st_size
            etag = f'"{total:x}-{st.st_mtime_ns:x}"'

            if _etag_match(self.headers.get("If-None-Match"), etag):
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return

            range_hdr = (self.headers.get("Range") or "").strip()
            start, end, status, partial = 0, max(0, total - 1), 200, False

            if range_hdr:
                # If-Range не совпал -> файл менялся, безопаснее отдать целиком (200)
                if_range = (self.headers.get("If-Range") or "").strip()
                if if_range and if_range != etag:
                    range_hdr = ""
            if range_hdr:
                if total == 0:
                    self._send_416(0)
                    return
                m = _RANGE_RE.match(range_hdr)
                if not m or (not m.group(1) and not m.group(2)):
                    # мульти-рейндж и синтаксический мусор: по RFC 7233 игнорируем -> 200
                    range_hdr = ""
                elif not m.group(1):  # суффиксный рейндж bytes=-N (последние N байт)
                    suffix = int(m.group(2))
                    if suffix <= 0:
                        self._send_416(total)
                        return
                    start, end, partial = max(0, total - suffix), total - 1, True
                else:
                    start = int(m.group(1))
                    if start >= total:
                        self._send_416(total)
                        return
                    end = min(int(m.group(2)), total - 1) if m.group(2) else total - 1
                    if start > end:  # синтаксически неверный рейндж -> игнорируем (RFC 7233)
                        start, end, partial = 0, total - 1, False
                    else:
                        partial = True
                status = 206 if partial else 200

            length = (end - start + 1) if total > 0 else 0
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", etag)
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            if head_only or length == 0:
                return

            remaining = length
            if start:
                f.seek(start)
            while remaining > 0:
                chunk = f.read(min(1 << 16, remaining))
                if not chunk:
                    # Файл «съёжился» под нами (заменили на месте): обещанный Content-Length
                    # уже не собрать — рвём соединение, чтобы клиент не посчитал ответ целым.
                    self.close_connection = True
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _handle(self, head_only=False):
        path = self.path.split("?", 1)[0]
        self._resp_started = False
        en = False
        try:
            cfg = C.load()
            en = cfg.get("language") == "en"
            client_ip = self.client_address[0] if self.client_address else "unknown"
            if not rate_limiter.allow(client_ip, cfg.get("rate_limit_per_min", 300)):
                self._json(
                    {"error": "rate limit exceeded, please retry shortly"},
                    code=429,
                    head_only=head_only,
                    extra_headers={"Retry-After": "4"},
                )
                return

            if path == "/ping":
                self._json(
                    {"app": "botyaraMC", "server_name": cfg["server_name"]},
                    head_only=head_only,
                )
            elif path == "/manifest":
                manifest = {
                    "app": "botyaraMC",
                    "server_name": cfg["server_name"],
                    "client_folder": cfg["client_folder"],
                    "mc_version": cfg["mc_version"],
                    "loader": cfg["loader"],
                    "java_version": cfg["java_version"],
                    "mods_hidden": cfg["hide_mods"] != "none",
                    "delete_user_mods": bool(cfg["delete_user_mods"]),
                    "server": {
                        "host": cfg["minecraft_server"],
                        "port": cfg["minecraft_port"],
                        "auto_join": bool(cfg["auto_join"]),
                    },
                    "mods": M.scan_mods(cfg),
                    "resourcepacks": M.scan_resourcepacks(),
                    "background": M.scan_background(cfg),
                }
                self._json_cached(manifest, head_only=head_only)
            elif path == "/background":
                p, mime = M.resolve_background(cfg)
                if p is None:
                    self._json({"error": "not found"}, 404, head_only=head_only)
                    return
                self._serve_file(p, mime, head_only=head_only)
            elif path.startswith("/mods/"):
                p = M.resolve_mod(unquote(path[len("/mods/"):]), cfg)
                if p is None:
                    self._json({"error": "not found"}, 404, head_only=head_only)
                    return
                self._serve_file(p, "application/java-archive", head_only=head_only)
            elif path.startswith("/resourcepacks/"):
                p = M.resolve_resourcepack(unquote(path[len("/resourcepacks/"):]))
                if p is None:
                    self._json({"error": "not found"}, 404, head_only=head_only)
                    return
                self._serve_file(p, "application/zip", head_only=head_only)
            else:
                self._json({"error": "not found"}, 404, head_only=head_only)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            # Файл пропал/перезаписался прямо во время запроса, диск недоступен и т.п.:
            # честный 500 вместо молча оборванного соединения + строчка в stderr для диагностики.
            _log_err(f"request error on {path}: {e.__class__.__name__}: {e}")
            if not getattr(self, "_resp_started", False):
                try:
                    self._json({"error": "internal server error"}, 500, head_only=head_only)
                except OSError:
                    pass

    def do_GET(self):
        self._handle(head_only=False)

    def do_HEAD(self):
        self._handle(head_only=True)


def local_ips():
    try:
        return sorted(set(socket.gethostbyname_ex(socket.gethostname())[2]))
    except OSError:
        return []


def _print_diff(label_ru, label_en, prev, cur, en=False):
    lbl = label_en if en else label_ru
    added = "added" if en else "добавлен"
    removed = "removed" if en else "удалён"
    changed = "updated" if en else "изменён"
    for n in sorted(cur.keys() - prev.keys()):
        print(f"[+] {lbl} {added}: {n}")
    for n in sorted(prev.keys() - cur.keys()):
        print(f"[-] {lbl} {removed}: {n}")
    for n in sorted(k for k in cur.keys() & prev.keys() if cur[k] != prev[k]):
        print(f"[~] {lbl} {changed}: {n}")


def main():
    first_run = C.ensure_files()
    cfg = C.load()
    en = cfg.get("language") == "en"
    if first_run:
        if en:
            print("[i] First run: created config.txt, mods/ & resourcepacks/. Run `python tui.py` to configure!")
        else:
            print("[i] Первый запуск: созданы config.txt, mods/ и resourcepacks/. Запусти `python tui.py` для настройки!")

    discovery.start(C.load)
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", cfg["http_port"]), Handler)
    except OSError as e:
        if en:
            print(f"[!] Failed to bind HTTP port {cfg['http_port']}: {e}")
        else:
            print(f"[!] Не удалось занять HTTP-порт {cfg['http_port']}: {e}")
        sys.exit(1)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def _sigterm(_signum, _frame):
        raise KeyboardInterrupt  # аккуратный выход по systemctl stop / kill

    try:
        signal.signal(signal.SIGTERM, _sigterm)
    except (ValueError, OSError):
        pass  # signal доступен только в главном потоке

    java_str = f"Java {cfg['java_version']}" if cfg["java_version"] else "Java auto"
    rl = cfg["rate_limit_per_min"]
    rl_str = f"{rl}/min" if rl else "off"
    folder_str = cfg["client_folder"] or "client-default"
    mc_srv_raw = str(cfg.get("minecraft_server") or "auto").strip()
    is_auto_srv = mc_srv_raw.lower() in ("", "auto", "127.0.0.1", "localhost", "0.0.0.0")
    bg_meta = M.scan_background(cfg)

    print("=" * 60)
    if en:
        print(f" botyaraMC sync-server [{cfg['server_name']}] is running 🚀")
        print(f" HTTP: {cfg['http_port']} (Range + RateLimit {rl_str})   UDP: {cfg['discovery_port']}")
        for ip in local_ips():
            print(f"   your IP: {ip}   (Radmin VPN is usually 26.x.x.x)")
        if cfg["auto_join"]:
            aj = f"auto (same host):{cfg['minecraft_port']}" if is_auto_srv else f"{mc_srv_raw}:{cfg['minecraft_port']}"
        else:
            aj = "disabled"
        print(f" Minecraft {cfg['mc_version']} / {cfg['loader']} ({java_str})  |  Auto-Join: {aj}")
        bg_str = bg_meta["name"] if bg_meta else ("ready (drop background.png)" if cfg.get("serve_background", True) else "off")
        print(f" Folder: {folder_str}  |  Cloak: {cfg['hide_mods']}  |  Strict mods: {cfg['delete_user_mods']}  |  BG: {bg_str}")
        print(" Drop .jar into mods/ & .zip into resourcepacks/. Ctrl+C to stop.")
    else:
        print(f" botyaraMC sync-server [{cfg['server_name']}] запущен 🚀")
        print(f" HTTP: {cfg['http_port']} (Range + лимит {rl_str})   UDP: {cfg['discovery_port']}")
        for ip in local_ips():
            print(f"   твой IP: {ip}   (в Radmin VPN обычно 26.x.x.x)")
        if cfg["auto_join"]:
            aj = f"авто (по адресу синка):{cfg['minecraft_port']}" if is_auto_srv else f"{mc_srv_raw}:{cfg['minecraft_port']}"
        else:
            aj = "выкл"
        print(f" Minecraft {cfg['mc_version']} / {cfg['loader']} ({java_str})  |  Автовход: {aj}")
        bg_str = bg_meta["name"] if bg_meta else ("готов (положи background.png)" if cfg.get("serve_background", True) else "выкл")
        print(f" Папка: {folder_str}  |  Скрытие: {cfg['hide_mods']}  |  Строгие моды: {cfg['delete_user_mods']}  |  Фон: {bg_str}")
        print(" Кидай .jar в mods/ и .zip в resourcepacks/. Ctrl+C - выход.")
    print("=" * 60)

    prev_mods = M.scan_real_mods()
    prev_rp = {r["name"]: r["sha256"] for r in M.scan_resourcepacks()}
    if en:
        print(f"[i] Active mods: {len(prev_mods)} | Resourcepacks: {len(prev_rp)}")
    else:
        print(f"[i] Модов сейчас: {len(prev_mods)} | Ресурспаков: {len(prev_rp)}")
    try:
        while True:
            time.sleep(3)
            try:
                en = C.load().get("language") == "en"
                cur_mods = M.scan_real_mods()
                cur_rp = {r["name"]: r["sha256"] for r in M.scan_resourcepacks()}
            except Exception as e:
                # Нет доступа к диску и т.п. — не роняем весь сервер из-за монитор-цикла
                _log_err(f"monitor loop: {e.__class__.__name__}: {e}")
                time.sleep(2)
                continue
            _print_diff("мод", "mod", prev_mods, cur_mods, en=en)
            _print_diff("ресурспак", "resourcepack", prev_rp, cur_rp, en=en)
            prev_mods, prev_rp = cur_mods, cur_rp
    except KeyboardInterrupt:
        print("\nBye! 👋" if en else "\nПока! 👋")
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
