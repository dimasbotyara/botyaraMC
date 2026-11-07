"""UDP-ответчик автообнаружения: клиент кричит BOTYARAMC? - мы отвечаем."""
import json
import socket
import threading

MAGIC = b"BOTYARAMC?"


def start(get_cfg):
    def run():
        cfg0 = get_cfg()
        port = cfg0["discovery_port"]
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
        except OSError as e:
            if cfg0.get("language") == "en":
                print(f"[!] Auto-discovery failed to bind (UDP {port}): {e}")
            else:
                print(f"[!] Автообнаружение не запустилось (UDP {port}): {e}")
            return
        while True:
            try:
                data, addr = s.recvfrom(256)
                if data.strip() == MAGIC:
                    cur = get_cfg()
                    reply = {
                        "app": "botyaraMC",
                        "http_port": cur["http_port"],
                        "server_name": cur.get("server_name", "botyaraMC"),
                    }
                    s.sendto(json.dumps(reply, ensure_ascii=False).encode("utf-8"), addr)
            except OSError:
                continue

    threading.Thread(target=run, daemon=True).start()
