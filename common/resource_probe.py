"""Cross-platform process and host resource evidence for formal experiments."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


GNU_RSS_RE = re.compile(r"(?m)^\s*Maximum resident set size \(kbytes\):\s*(\d+)\s*$")
BSD_RSS_RE = re.compile(r"(?m)^\s*(\d+)\s+maximum resident set size\s*$")
GNU_USER_RE = re.compile(r"(?m)^\s*User time \(seconds\):\s*([0-9.]+)\s*$")
GNU_SYS_RE = re.compile(r"(?m)^\s*System time \(seconds\):\s*([0-9.]+)\s*$")


def measured_command(command: Sequence[str]) -> tuple[list[str], str]:
    """Return a command wrapped by the platform's auditable time implementation."""

    time_path = Path("/usr/bin/time")
    normalized = [str(item) for item in command]
    if not time_path.is_file():
        return normalized, "wall-only"
    if sys.platform.startswith("linux"):
        return [str(time_path), "-v", *normalized], "gnu-time-v"
    if sys.platform == "darwin":
        return [str(time_path), "-l", *normalized], "bsd-time-l"
    return normalized, "wall-only"


def parse_time_evidence(stderr: str, backend: str) -> dict[str, int | float | str | None]:
    """Parse RSS and CPU time without conflating Linux KiB with macOS bytes."""

    max_rss_bytes: int | None = None
    user_cpu_sec: float | None = None
    system_cpu_sec: float | None = None
    if backend == "gnu-time-v":
        match = GNU_RSS_RE.search(stderr)
        if match:
            max_rss_bytes = int(match.group(1)) * 1024
        user_match = GNU_USER_RE.search(stderr)
        system_match = GNU_SYS_RE.search(stderr)
        user_cpu_sec = float(user_match.group(1)) if user_match else None
        system_cpu_sec = float(system_match.group(1)) if system_match else None
    elif backend == "bsd-time-l":
        match = BSD_RSS_RE.search(stderr)
        if match:
            max_rss_bytes = int(match.group(1))
    return {
        "measurement_backend": backend,
        "max_rss_bytes": max_rss_bytes,
        "user_cpu_sec": user_cpu_sec,
        "system_cpu_sec": system_cpu_sec,
    }


def _read_first(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _linux_memory_bytes() -> int | None:
    payload = _read_first(Path("/proc/meminfo"))
    if not payload:
        return None
    match = re.search(r"(?m)^MemTotal:\s*(\d+)\s+kB\s*$", payload)
    return int(match.group(1)) * 1024 if match else None


def _linux_cpu_brand() -> str | None:
    payload = _read_first(Path("/proc/cpuinfo"))
    if not payload:
        return None
    match = re.search(r"(?m)^model name\s*:\s*(.+?)\s*$", payload)
    return match.group(1) if match else None


def _sysctl_value(key: str) -> str | None:
    try:
        proc = subprocess.run(
            ["sysctl", "-n", key],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _optional_command(command: Sequence[str]) -> dict[str, Any]:
    if shutil.which(str(command[0])) is None:
        return {"available": False, "command": list(command), "stdout": None}
    proc = subprocess.run(
        list(command),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return {
        "available": True,
        "command": list(command),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-16000:].strip(),
    }


def collect_host_evidence(root: Path) -> dict[str, Any]:
    """Collect reproducible CPU, memory, disk, NUMA, and threading evidence."""

    memory_bytes: int | None = None
    cpu_brand: str | None = None
    if sys.platform.startswith("linux"):
        memory_bytes = _linux_memory_bytes()
        cpu_brand = _linux_cpu_brand()
    elif sys.platform == "darwin":
        raw_memory = _sysctl_value("hw.memsize")
        memory_bytes = int(raw_memory) if raw_memory and raw_memory.isdigit() else None
        cpu_brand = _sysctl_value("machdep.cpu.brand_string")

    disk = shutil.disk_usage(root)
    thread_environment = {
        key: os.environ.get(key)
        for key in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "RAYON_NUM_THREADS",
            "UV_THREADPOOL_SIZE",
        )
    }
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_architecture": platform.architecture()[0],
        "cpu_brand": cpu_brand,
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": memory_bytes,
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "thread_environment": thread_environment,
        "linux_lscpu": _optional_command(["lscpu"]),
        "numa": _optional_command(["numactl", "--hardware"]),
    }
