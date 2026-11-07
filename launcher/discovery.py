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


def discover_all(timeout=2.0, port=DISCOVERY_PORT, stop_on_first=False):
    """Возвращает список [(host, http_port, server_name), ...] ответивших серверов."""
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

    results = []
    seen = set()
    deadline = time.time() + timeout
    while socks and time.time() < deadline:
        if stop_on_first and results:
            break
        try:
            ready, _, _ = select.select(socks, [], [], 0.15)
        except (OSError, ValueError):
            break
        for s in ready:
            try:
                data, addr = s.recvfrom(1024)
                info = json.loads(data.decode("utf-8"))
                if info.get("app") == "botyaraMC":
                    item = (
                        addr[0],
                        int(info.get("http_port", 25456)),
                        str(info.get("server_name") or "").strip(),
                    )
                    key = (item[0], item[1])
                    if key not in seen:
                        seen.add(key)
                        results.append(item)
                        if stop_on_first:
                            break
            except (OSError, ValueError):
                continue
    for s in socks:
        s.close()
    return results


def discover_full(timeout=2.5, port=DISCOVERY_PORT):
    """Возвращает (host, http_port, server_name) первого ответившего сервера или None."""
    res = discover_all(timeout=timeout, port=port, stop_on_first=True)
    return res[0] if res else None


def discover(timeout=2.5, port=DISCOVERY_PORT):
    """Возвращает (host, http_port) первого ответившего сервера или None."""
    res = discover_full(timeout=timeout, port=port)
    return (res[0], res[1]) if res else None
