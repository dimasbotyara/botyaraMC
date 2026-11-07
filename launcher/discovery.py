"""Автообнаружение sync-сервера: UDP-broadcast по всем интерфейсам (в т.ч. Radmin VPN)."""
import ipaddress
import json
import select
import socket
import time

DISCOVERY_PORT = 25457
MAGIC = b"BOTYARAMC?"


def _targets():
    out = []
    try:
        import psutil
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and a.netmask and not a.address.startswith("127."):
                    try:
                        net = ipaddress.IPv4Network(f"{a.address}/{a.netmask}", strict=False)
                    except ValueError:
                        continue
                    out.append((a.address, str(net.broadcast_address)))
    except Exception:
        pass
    if not out:
        out.append(("0.0.0.0", "255.255.255.255"))
    return out


def discover(timeout=2.5, port=DISCOVERY_PORT):
    """Возвращает (host, http_port) первого ответившего сервера или None."""
    socks = []
    for local, bcast in _targets():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind((local, 0))
            for dest in {bcast, "255.255.255.255"}:
                try:
                    s.sendto(MAGIC, (dest, port))
                except OSError:
                    pass
            socks.append(s)
        except OSError:
            continue
    try:  # сервер на этом же компе
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(MAGIC, ("127.0.0.1", port))
        socks.append(s)
    except OSError:
        pass

    found = None
    deadline = time.time() + timeout
    while socks and not found and time.time() < deadline:
        try:
            ready, _, _ = select.select(socks, [], [], 0.2)
        except (OSError, ValueError):
            break
        for s in ready:
            try:
                data, addr = s.recvfrom(1024)
                info = json.loads(data.decode("utf-8"))
                if info.get("app") == "botyaraMC":
                    found = (addr[0], int(info.get("http_port", 25456)))
                    break
            except (OSError, ValueError):
                continue
    for s in socks:
        s.close()
    return found
