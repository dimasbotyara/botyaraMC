"""botyaraMC sync-server. Запуск: python server.py"""
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


class Handler(BaseHTTPRequestHandler):
    server_version = "botyaraMC-sync/2.0"

    def log_message(self, fmt, *args):  # тишина в консоли
        pass

    def _json(self, obj, code=200, head_only=False):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
            if path == "/ping":
                self._json({"app": "botyaraMC"}, head_only=head_only)
            elif path == "/manifest":
                cfg = C.load()
                self._json({
                    "app": "botyaraMC",
                    "mc_version": cfg["mc_version"],
                    "loader": cfg["loader"],
                    "java_version": cfg["java_version"],
                    "mods_hidden": cfg["hide_mods"] != "none",
                    "server": {
                        "host": cfg["minecraft_server"],
                        "port": cfg["minecraft_port"],
                    },
                    "mods": M.scan_mods(cfg),
                    "resourcepacks": M.scan_resourcepacks(),
                }, head_only=head_only)
            elif path.startswith("/mods/"):
                cfg = C.load()
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


def _print_diff(label, prev, cur):
    for n in sorted(cur.keys() - prev.keys()):
        print(f"[+] {label} добавлен: {n}")
    for n in sorted(prev.keys() - cur.keys()):
        print(f"[-] {label} удалён:   {n}")
    for n in sorted(k for k in cur.keys() & prev.keys() if cur[k] != prev[k]):
        print(f"[~] {label} изменён:  {n}")


def main():
    first_run = C.ensure_files()
    cfg = C.load()
    if first_run:
        print("[i] Первый запуск: созданы config.txt, mods/ и resourcepacks/. Поправь config.txt под себя!")

    discovery.start(C.load)
    httpd = ThreadingHTTPServer(("0.0.0.0", cfg["http_port"]), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    java_str = f"Java {cfg['java_version']}" if cfg["java_version"] else "Java auto"
    hide_str = cfg["hide_mods"]
    print("=" * 58)
    print(" botyaraMC sync-server запущен 🚀")
    print(f" HTTP: {cfg['http_port']} (Range-докачка вкл)   UDP: {cfg['discovery_port']}")
    for ip in local_ips():
        print(f"   твой IP: {ip}   (в Radmin VPN обычно 26.x.x.x)")
    print(f" Minecraft {cfg['mc_version']} / {cfg['loader']} ({java_str})"
          f"  ->  {cfg['minecraft_server']}:{cfg['minecraft_port']}")
    print(f" Скрытие модов: {hide_str}")
    print(" Кидай .jar в mods/ и .zip в resourcepacks/ - клиенты подтянут сами. Ctrl+C - выход.")
    print("=" * 58)

    prev_mods = M.scan_real_mods()
    prev_rp = {r["name"]: r["sha256"] for r in M.scan_resourcepacks()}
    print(f"[i] Модов сейчас: {len(prev_mods)} | Ресурспаков: {len(prev_rp)}")
    try:
        while True:
            time.sleep(3)
            cur_mods = M.scan_real_mods()
            cur_rp = {r["name"]: r["sha256"] for r in M.scan_resourcepacks()}
            _print_diff("мод", prev_mods, cur_mods)
            _print_diff("ресурспак", prev_rp, cur_rp)
            prev_mods, prev_rp = cur_mods, cur_rp
    except KeyboardInterrupt:
        print("\nПока! 👋")
        httpd.shutdown()


if __name__ == "__main__":
    main()
