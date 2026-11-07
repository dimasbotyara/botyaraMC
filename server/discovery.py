"""UDP-ответчик автообнаружения: клиент кричит BOTYARAMC? - мы отвечаем."""
import json
import socket
import threading

MAGIC = b"BOTYARAMC?"


def start(get_cfg):
    def run():
        port = get_cfg()["discovery_port"]
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
        except OSError as e:
            print(f"[!] Автообнаружение не запустилось (UDP {port}): {e}")
            return
        while True:
            try:
                data, addr = s.recvfrom(256)
                if data.strip() == MAGIC:
                    reply = {"app": "botyaraMC", "http_port": get_cfg()["http_port"]}
                    s.sendto(json.dumps(reply).encode(), addr)
            except OSError:
                continue

    threading.Thread(target=run, daemon=True).start()
