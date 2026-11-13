"""UDP-ответчик автообнаружения: клиент кричит BOTYARAMC? - мы отвечаем.

Ответы лимитируются по IP: мультикаст-флуд не превращает сервер в UDP-амлификатор."""
import collections
import json
import socket
import threading
import time

MAGIC = b"BOTYARAMC?"
_REPLIES_PER_MIN = 30        # ответов одному IP в минуту (клиенту хватает с запасом)
_MAX_TRACKED_IPS = 4096      # защита карты от спуфинга случайных адресов


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

        hits = collections.defaultdict(collections.deque)
        last_gc = time.monotonic()
        while True:
            try:
                data, addr = s.recvfrom(256)
                if data.strip() != MAGIC:
                    continue
                now = time.monotonic()
                if now - last_gc > 120.0:
                    last_gc = now
                    for ip, dq in list(hits.items()):
                        if not dq or dq[-1] < now - 60.0:
                            del hits[ip]
                dq = hits[addr[0]]
                while dq and dq[0] < now - 60.0:
                    dq.popleft()
                if len(dq) >= _REPLIES_PER_MIN or len(hits) > _MAX_TRACKED_IPS:
                    continue
                dq.append(now)
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
