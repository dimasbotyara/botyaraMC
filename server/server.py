"""botyaraMC sync-server. Запуск: python server.py"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import discovery
import mods_index as M
import srv_config as C


class Handler(BaseHTTPRequestHandler):
    server_version = "botyaraMC-sync"

    def log_message(self, fmt, *args):  # тишина в консоли
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/ping":
                self._json({"app": "botyaraMC"})
            elif path == "/manifest":
                cfg = C.load()
                self._json({
                    "app": "botyaraMC",
                    "mc_version": cfg["mc_version"],
                    "loader": cfg["loader"],
                    "server": {"host": cfg["minecraft_server"], "port": cfg["minecraft_port"]},
                    "mods": M.scan(),
                })
            elif path.startswith("/mods/"):
                p = M.resolve(unquote(path[len("/mods/"):]))
                if p is None:
                    self._json({"error": "not found"}, 404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/java-archive")
                self.send_header("Content-Length", str(p.stat().st_size))
                self.end_headers()
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(1 << 16)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            else:
                self._json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def local_ips():
    try:
        return sorted(set(socket.gethostbyname_ex(socket.gethostname())[2]))
    except OSError:
        return []


def main():
    first_run = C.ensure_files()
    cfg = C.load()
    if first_run:
        print("[i] Первый запуск: создал config.txt и папку mods/. Поправь config.txt под себя!")

    discovery.start(C.load)
    httpd = ThreadingHTTPServer(("0.0.0.0", cfg["http_port"]), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    print("=" * 52)
    print(" botyaraMC sync-server запущен 🚀")
    print(f" HTTP: {cfg['http_port']}   Автообнаружение (UDP): {cfg['discovery_port']}")
    for ip in local_ips():
        print(f"   твой IP: {ip}   (в Radmin VPN обычно 26.x.x.x)")
    print(f" Minecraft {cfg['mc_version']} / {cfg['loader']}  ->  {cfg['minecraft_server']}:{cfg['minecraft_port']}")
    print(" Кидай .jar в папку mods/ - клиенты подтянут сами. Ctrl+C - выход.")
    print("=" * 52)

    prev = {m["name"]: m["sha256"] for m in M.scan()}
    print(f"[i] Модов сейчас: {len(prev)}")
    try:
        while True:
            time.sleep(3)
            cur = {m["name"]: m["sha256"] for m in M.scan()}
            for n in sorted(cur.keys() - prev.keys()):
                print(f"[+] добавлен: {n}")
            for n in sorted(prev.keys() - cur.keys()):
                print(f"[-] удалён:   {n}")
            for n in sorted(k for k in cur.keys() & prev.keys() if cur[k] != prev[k]):
                print(f"[~] изменён:  {n}")
            prev = cur
    except KeyboardInterrupt:
        print("\nПока! 👋")
        httpd.shutdown()


if __name__ == "__main__":
    main()
