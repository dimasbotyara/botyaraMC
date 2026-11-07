"""botyaraMC sync-server. Запуск: python server.py | Настройка TUI: python tui.py"""
import collections
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import discovery
import mods_index as M
import srv_config as C

_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")


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


class Handler(BaseHTTPRequestHandler):
    server_version = "botyaraMC-sync"

    def log_message(self, fmt, *args):  # тишина в консоли
        pass

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

    def _serve_file(self, path, content_type, head_only=False):
        try:
            total = path.stat().st_size
        except OSError:
            self._json({"error": "not found"}, 404, head_only=head_only)
            return

        range_hdr = (self.headers.get("Range") or "").strip()
        start, end, status = 0, max(0, total - 1), 200

        if range_hdr and total > 0:
            m = _RANGE_RE.match(range_hdr)
            if not m:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start = int(m.group(1))
            end = min(int(m.group(2)), total - 1) if m.group(2) else total - 1
            if start >= total or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        elif range_hdr and total == 0:
            self.send_response(416)
            self.send_header("Content-Range", "bytes */0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        length = (end - start + 1) if total > 0 else 0
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if head_only or length == 0:
            return

        remaining = length
        with open(path, "rb") as f:
            if start:
                f.seek(start)
            while remaining > 0:
                chunk = f.read(min(1 << 16, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _handle(self, head_only=False):
        path = self.path.split("?", 1)[0]
        try:
            cfg = C.load()
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
                self._json({
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
                }, head_only=head_only)
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
    httpd = ThreadingHTTPServer(("0.0.0.0", cfg["http_port"]), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    java_str = f"Java {cfg['java_version']}" if cfg["java_version"] else "Java auto"
    rl = cfg["rate_limit_per_min"]
    rl_str = f"{rl}/min" if rl else "off"
    folder_str = cfg["client_folder"] or ".minecraft"

    print("=" * 60)
    if en:
        print(f" botyaraMC sync-server [{cfg['server_name']}] is running 🚀")
        print(f" HTTP: {cfg['http_port']} (Range + RateLimit {rl_str})   UDP: {cfg['discovery_port']}")
        for ip in local_ips():
            print(f"   your IP: {ip}   (Radmin VPN is usually 26.x.x.x)")
        aj = f"{cfg['minecraft_server']}:{cfg['minecraft_port']}" if cfg["auto_join"] else "disabled"
        print(f" Minecraft {cfg['mc_version']} / {cfg['loader']} ({java_str})  |  Auto-Join: {aj}")
        print(f" Folder: {folder_str}  |  Cloak: {cfg['hide_mods']}  |  Delete user mods: {cfg['delete_user_mods']}")
        print(" Drop .jar into mods/ & .zip into resourcepacks/. Ctrl+C to stop.")
    else:
        print(f" botyaraMC sync-server [{cfg['server_name']}] запущен 🚀")
        print(f" HTTP: {cfg['http_port']} (Range + лимит {rl_str})   UDP: {cfg['discovery_port']}")
        for ip in local_ips():
            print(f"   твой IP: {ip}   (в Radmin VPN обычно 26.x.x.x)")
        aj = f"{cfg['minecraft_server']}:{cfg['minecraft_port']}" if cfg["auto_join"] else "выкл"
        print(f" Minecraft {cfg['mc_version']} / {cfg['loader']} ({java_str})  |  Автовход: {aj}")
        print(f" Папка: {folder_str}  |  Скрытие: {cfg['hide_mods']}  |  Удалять чужие моды: {cfg['delete_user_mods']}")
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
            en = C.load().get("language") == "en"
            cur_mods = M.scan_real_mods()
            cur_rp = {r["name"]: r["sha256"] for r in M.scan_resourcepacks()}
            _print_diff("мод", "mod", prev_mods, cur_mods, en=en)
            _print_diff("ресурспак", "resourcepack", prev_rp, cur_rp, en=en)
            prev_mods, prev_rp = cur_mods, cur_rp
    except KeyboardInterrupt:
        print("\nBye! 👋" if en else "\nПока! 👋")
        httpd.shutdown()


if __name__ == "__main__":
    main()
