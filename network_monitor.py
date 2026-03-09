"""
NetWatch - Network Monitor Core Engine
Handles process/connection enumeration, bandwidth tracking, and IP lookups.
"""

import ipaddress
import psutil
import socket
import time
import threading
import requests
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class ConnectionInfo:
    pid: int
    process_name: str
    local_addr: str
    local_port: int
    remote_ip: str
    remote_port: int
    status: str
    domain: str = ""
    company: str = ""
    country: str = ""
    download_rate: float = 0.0   # bytes/sec
    upload_rate: float = 0.0     # bytes/sec
    total_sent: int = 0
    total_recv: int = 0

    @property
    def key(self) -> str:
        return f"{self.pid}:{self.local_port}:{self.remote_ip}:{self.remote_port}"


@dataclass
class ProcessBandwidth:
    """Tracks cumulative bytes per process to calculate deltas."""
    bytes_sent: int = 0
    bytes_recv: int = 0
    timestamp: float = field(default_factory=time.time)
    send_rate: float = 0.0
    recv_rate: float = 0.0


# ─── IP Lookup Cache ──────────────────────────────────────────────────────────

class IPLookupCache:
    """
    Thread-safe cache for IP → (domain, company, country) lookups.
    Uses ip-api.com (free, no key needed, 45 req/min limit).
    """

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()

    def get(self, ip: str) -> Optional[dict]:
        with self._lock:
            return self._cache.get(ip)

    def lookup_async(self, ip: str, callback):
        """Trigger a background lookup if not already cached/pending."""
        with self._lock:
            if ip in self._cache or ip in self._pending:
                return
            self._pending.add(ip)

        thread = threading.Thread(
            target=self._do_lookup,
            args=(ip, callback),
            daemon=True
        )
        thread.start()

    def _do_lookup(self, ip: str, callback):
        result = {"domain": "", "company": "", "country": ""}
        try:
            # Reverse DNS
            try:
                hostname = socket.gethostbyaddr(ip)[0]
                result["domain"] = hostname
            except Exception:
                result["domain"] = ip

            # IP org/country via ip-api.com
            resp = requests.get(
                f"http://ip-api.com/json/{ip}?fields=org,country,countryCode",
                timeout=4
            )
            if resp.status_code == 200:
                data = resp.json()
                org = data.get("org", "")
                # Strip ASN prefix like "AS15169 Google LLC" → "Google LLC"
                if org and " " in org:
                    parts = org.split(" ", 1)
                    if parts[0].startswith("AS") and parts[0][2:].isdigit():
                        org = parts[1]
                result["company"] = org
                result["country"] = data.get("countryCode", "")

        except Exception:
            pass
        finally:
            with self._lock:
                self._cache[ip] = result
                self._pending.discard(ip)
            callback(ip, result)


# ─── Bandwidth Tracker ────────────────────────────────────────────────────────

class BandwidthTracker:
    """
    Tracks per-process bandwidth by sampling psutil's io_counters.
    """

    def __init__(self):
        self._prev: dict[int, ProcessBandwidth] = {}
        self._rates: dict[int, tuple[float, float]] = {}  # pid → (recv_rate, send_rate)
        self._lock = threading.Lock()

    def sample(self):
        """Take one snapshot of all process io_counters."""
        now = time.time()
        new_prev = {}

        for proc in psutil.process_iter(["pid", "io_counters"]):
            try:
                pid = proc.info["pid"]
                counters = proc.info["io_counters"]
                if counters is None:
                    continue

                sent = counters.bytes_sent if hasattr(counters, "bytes_sent") else counters.write_bytes
                recv = counters.bytes_recv if hasattr(counters, "bytes_recv") else counters.read_bytes

                new_prev[pid] = ProcessBandwidth(
                    bytes_sent=sent,
                    bytes_recv=recv,
                    timestamp=now
                )

                with self._lock:
                    prev = self._prev.get(pid)
                    if prev:
                        dt = now - prev.timestamp
                        if dt > 0:
                            send_rate = max(0, (sent - prev.bytes_sent) / dt)
                            recv_rate = max(0, (recv - prev.bytes_recv) / dt)
                            self._rates[pid] = (recv_rate, send_rate)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        with self._lock:
            self._prev = new_prev

    def get_rates(self, pid: int) -> tuple[float, float]:
        """Returns (download_bytes_per_sec, upload_bytes_per_sec)."""
        with self._lock:
            return self._rates.get(pid, (0.0, 0.0))


# ─── Main Monitor ─────────────────────────────────────────────────────────────

class NetworkMonitor:
    """
    Core monitoring engine. Polls connections, enriches with IP data,
    tracks bandwidth. Designed to be run in a background thread.
    """

    def __init__(self, refresh_interval: float = 2.0):
        self.refresh_interval = refresh_interval
        self.ip_cache = IPLookupCache()
        self.bw_tracker = BandwidthTracker()
        self._connections: list[ConnectionInfo] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.on_update = None   # callback: (list[ConnectionInfo]) → None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_connections(self) -> list[ConnectionInfo]:
        with self._lock:
            return list(self._connections)

    def _is_private(self, ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip).is_private
        except ValueError:
            return False

    def _loop(self):
        while self._running:
            self.bw_tracker.sample()
            connections = self._collect_connections()

            with self._lock:
                self._connections = connections

            if self.on_update:
                self.on_update(connections)

            time.sleep(self.refresh_interval)

    def _collect_connections(self) -> list[ConnectionInfo]:
        seen_pids: set[int] = set()
        results: list[ConnectionInfo] = []

        try:
            raw_conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, PermissionError):
            raw_conns = []

        # Build pid → process name map
        pid_names: dict[int, str] = {}
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pid_names[proc.info["pid"]] = proc.info["name"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        def _ip(addr):   return addr.ip   if hasattr(addr, "ip")   else addr[0]
        def _port(addr): return addr.port if hasattr(addr, "port") else addr[1]

        # Deduplicate by (pid, remote_ip) — show one row per process per remote
        seen_keys: set[str] = set()

        for conn in raw_conns:
            if not conn.raddr:
                continue
            if conn.pid is None:
                continue

            remote_ip   = _ip(conn.raddr)
            remote_port = _port(conn.raddr)

            if not remote_ip:
                continue
            if self._is_private(remote_ip):
                continue
            if conn.status not in ("ESTABLISHED", "SYN_SENT", "CLOSE_WAIT"):
                continue

            dedup_key = f"{conn.pid}:{remote_ip}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            proc_name = pid_names.get(conn.pid, "Unknown")
            # Strip .exe suffix for cleaner display
            if proc_name.endswith(".exe"):
                proc_name = proc_name[:-4]

            dl_rate, ul_rate = self.bw_tracker.get_rates(conn.pid)

            info = ConnectionInfo(
                pid=conn.pid,
                process_name=proc_name,
                local_addr=_ip(conn.laddr)   if conn.laddr else "",
                local_port=_port(conn.laddr) if conn.laddr else 0,
                remote_ip=remote_ip,
                remote_port=remote_port,
                status=conn.status,
                download_rate=dl_rate,
                upload_rate=ul_rate,
            )

            # Enrich from cache or trigger async lookup
            cached = self.ip_cache.get(remote_ip)
            if cached:
                info.domain = cached.get("domain", remote_ip)
                info.company = cached.get("company", "")
                info.country = cached.get("country", "")
            else:
                info.domain = remote_ip
                self.ip_cache.lookup_async(remote_ip, self._on_ip_resolved)

            results.append(info)

        # Sort: by process name, then remote IP
        results.sort(key=lambda c: (c.process_name.lower(), c.remote_ip))
        return results

    def _on_ip_resolved(self, ip: str, data: dict):
        """Called when an async IP lookup completes — triggers a UI refresh."""
        if self.on_update:
            conns = self.get_connections()
            # Patch the resolved data into any matching connection
            for c in conns:
                if c.remote_ip == ip:
                    c.domain = data.get("domain", ip)
                    c.company = data.get("company", "")
                    c.country = data.get("country", "")
            if self.on_update:
                self.on_update(conns)


# ─── Formatting Helpers ───────────────────────────────────────────────────────

def fmt_rate(bps: float) -> str:
    """Format bytes/sec into human-readable string."""
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps/1024:.1f} KB/s"
    elif bps < 1024 ** 3:
        return f"{bps/1024**2:.1f} MB/s"
    else:
        return f"{bps/1024**3:.1f} GB/s"


def fmt_domain(conn: ConnectionInfo, max_len: int = 35) -> str:
    """Return the best available domain label, truncated."""
    label = conn.domain if conn.domain and conn.domain != conn.remote_ip else conn.remote_ip
    return label[:max_len] + "…" if len(label) > max_len else label


def fmt_company(conn: ConnectionInfo, max_len: int = 22) -> str:
    label = conn.company if conn.company else "—"
    return label[:max_len] + "…" if len(label) > max_len else label