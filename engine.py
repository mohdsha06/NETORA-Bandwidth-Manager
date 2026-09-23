from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set

import psutil
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("netora.engine")
IS_WINDOWS: bool = sys.platform == "win32"

def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class TokenBucket:
    def __init__(self, rate_kbps: int):
        self.rate = float(rate_kbps * 1024)
        self.capacity = self.rate
        self.tokens = self.capacity
        self.last_check = time.perf_counter()
        self.lock = threading.Lock()

    def update_rate(self, rate_kbps: int) -> None:
        with self.lock:
            self.rate = float(rate_kbps * 1024)
            self.capacity = self.rate

    def consume(self, num_bytes: int) -> float:
        with self.lock:
            now = time.perf_counter()
            elapsed = now - self.last_check
            self.last_check = now

            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens >= num_bytes:
                self.tokens -= num_bytes
                return 0.0

            deficit = num_bytes - self.tokens
            delay = deficit / self.rate
            self.tokens = 0.0
            return delay


class BandwidthLimiter:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.target_pid: int | None = None
        self.target_name: str = ""
        self.dl_limit_kbps: int | None = None
        self.ul_limit_kbps: int | None = None

        self.dl_bucket: TokenBucket | None = None
        self.ul_bucket: TokenBucket | None = None

        self._active_ports: Set[int] = set()
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._port_thread: threading.Thread | None = None
        self._handle: Any | None = None
        self.last_error = ""

    def apply_limits(self, pid: int, name: str, dl_kbps: int | None, ul_kbps: int | None) -> bool:
        if not is_admin():
            self.last_error = "Administrator privileges required."
            return False

        with self.lock:
            self.target_pid = pid
            self.target_name = name
            self.dl_limit_kbps = dl_kbps
            self.ul_limit_kbps = ul_kbps

            self.dl_bucket = TokenBucket(dl_kbps) if dl_kbps else None
            self.ul_bucket = TokenBucket(ul_kbps) if ul_kbps else None

        self._start_threads()
        return True

    def clear_limits(self) -> None:
        with self.lock:
            self.target_pid = None
            self.target_name = ""
            self.dl_limit_kbps = None
            self.ul_limit_kbps = None
            self.dl_bucket = None
            self.ul_bucket = None
            self._active_ports.clear()
        self._stop_capture()

    def get_active_limit_for(self, pid: int) -> dict[str, int]:
        with self.lock:
            if self.target_pid == pid:
                res = {}
                if self.dl_limit_kbps: res["download"] = self.dl_limit_kbps
                if self.ul_limit_kbps: res["upload"] = self.ul_limit_kbps
                return res
        return {}

    def _get_target_ports(self) -> Set[int]:
        ports: Set[int] = set()
        with self.lock:
            pid = self.target_pid
        if pid is None:
            return ports

        try:
            p = psutil.Process(pid)
            for conn in p.net_connections(kind="inet"):
                if conn.laddr and conn.laddr.port:
                    ports.add(conn.laddr.port)
        except Exception:
            pass
        return ports

    def _start_threads(self) -> None:
        if self._port_thread and self._port_thread.is_alive():
            return

        self._stop_event.clear()
        self._port_thread = threading.Thread(target=self._port_monitor_loop, name="Netora-PortMonitor", daemon=True)
        self._port_thread.start()

    def _port_monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            current_ports = self._get_target_ports()
            with self.lock:
                changed = current_ports != self._active_ports
                self._active_ports = current_ports

            if changed and current_ports:
                self._restart_divert_with_ports(current_ports)
            elif not current_ports and self._handle:
                self._stop_capture()

            time.sleep(0.5)

    def _restart_divert_with_ports(self, ports: Set[int]) -> None:
        import pydivert

        self._stop_capture()
        port_list = " or ".join(f"(tcp.DstPort == {p} or tcp.SrcPort == {p} or udp.DstPort == {p} or udp.SrcPort == {p})" for p in sorted(ports))
        filter_str = f"ip and ({port_list})"

        try:
            handle = pydivert.WinDivert(filter_str)
            handle.open()
            self._handle = handle
            self._capture_thread = threading.Thread(target=self._divert_loop, args=(handle,), daemon=True)
            self._capture_thread.start()
            logger.info("WinDivert active on target ports: %s", ports)
        except Exception as exc:
            self.last_error = f"WinDivert open error: {exc}"
            logger.error(self.last_error)

    def _stop_capture(self) -> None:
        handle = self._handle
        self._handle = None
        if handle:
            try:
                handle.close()
            except Exception:
                pass

    def _divert_loop(self, handle: Any) -> None:
        while not self._stop_event.is_set() and self._handle == handle:
            try:
                packet = handle.recv()
            except Exception:
                break

            if packet is None:
                continue

            try:
                is_inbound = getattr(packet, "is_inbound", False)
                packet_len = len(packet.raw)

                if is_inbound and self.dl_bucket:
                    delay = self.dl_bucket.consume(packet_len)
                    if delay > 0.0:
                        time.sleep(delay)

                elif not is_inbound and self.ul_bucket:
                    delay = self.ul_bucket.consume(packet_len)
                    if delay > 0.0:
                        time.sleep(delay)

                packet.recalculate_checksums()
                handle.send(packet)
            except Exception:
                try:
                    handle.send(packet)
                except Exception:
                    pass

    def close(self) -> None:
        self._stop_event.set()
        self._stop_capture()


class QoSController:
    def __init__(self) -> None:
        self.limiter = BandwidthLimiter()
        self.last_error = ""

    def apply_limits(self, pid: int, name: str, dl_kbps: int | None, ul_kbps: int | None) -> bool:
        ok = self.limiter.apply_limits(pid, name, dl_kbps, ul_kbps)
        self.last_error = self.limiter.last_error
        return ok

    def clear_limits(self) -> None:
        self.limiter.clear_limits()

    def get_limits(self, pid: int) -> dict[str, int]:
        return self.limiter.get_active_limit_for(pid)

    def close(self) -> None:
        self.limiter.close()


class NetworkMonitorWorker(QThread):
    stats_updated = pyqtSignal(dict)

    def __init__(self, qos: QoSController, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.qos = qos
        self._stop_event = threading.Event()
        self._prev_nic_io: Optional[Any] = None
        self._prev_ts: float = 0.0
        self._prev_conn_counts: Dict[int, int] = {}

    def stop(self) -> None:
        self._stop_event.set()
        self.requestInterruption()
        self.quit()
        self.wait(1500)

    def _get_primary_nic_io(self) -> Any:
        try:
            nics = psutil.net_io_counters(pernic=True)
            candidates = {
                name: io for name, io in nics.items()
                if not any(v in name.lower() for v in ["loopback", "vethernet", "wsl", "docker", "bluetooth"])
            }
            if candidates:
                return max(candidates.values(), key=lambda x: x.bytes_recv + x.bytes_sent)
        except Exception:
            pass
        return psutil.net_io_counters()

    def run(self) -> None:
        self._prev_nic_io = self._get_primary_nic_io()
        self._prev_ts = time.monotonic()

        while not self._stop_event.wait(1.0):
            if self.isInterruptionRequested():
                break
            try:
                stats = self._sample()
                self.stats_updated.emit(stats)
            except Exception:
                continue

    def _sample(self) -> dict[str, Any]:
        now = time.monotonic()
        nic_io = self._get_primary_nic_io()
        dt = max(0.001, now - self._prev_ts)

        if self._prev_nic_io:
            total_down = max(0.0, (nic_io.bytes_recv - self._prev_nic_io.bytes_recv) / dt)
            total_up = max(0.0, (nic_io.bytes_sent - self._prev_nic_io.bytes_sent) / dt)
        else:
            total_down = total_up = 0.0

        self._prev_nic_io = nic_io
        self._prev_ts = now

        active_pids: Dict[int, int] = {}
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.pid:
                    active_pids[conn.pid] = active_pids.get(conn.pid, 0) + 1
        except Exception:
            pass

        processes: List[Dict[str, Any]] = []
        target_pid = self.qos.limiter.target_pid

        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pid = int(proc.info["pid"])
                if pid not in active_pids and pid != target_pid:
                    continue

                name = proc.info.get("name") or "Unknown"
                path = proc.info.get("exe") or ""
                limits = self.qos.get_limits(pid)

                p_down = total_down if (pid == target_pid or len(active_pids) == 1) else (total_down / max(1, len(active_pids)))
                p_up = total_up if (pid == target_pid or len(active_pids) == 1) else (total_up / max(1, len(active_pids)))

                processes.append({
                    "pid": pid,
                    "name": name,
                    "path": path,
                    "down_bps": p_down,
                    "up_bps": p_up,
                    "limit_details": limits,
                })
            except Exception:
                continue

        processes.sort(key=lambda x: (x["down_bps"], x["up_bps"]), reverse=True)

        return {
            "total_down_bps": total_down,
            "total_up_bps": total_up,
            "processes": processes,
        }