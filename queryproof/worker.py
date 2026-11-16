"""Disposable subprocess; the supervisor terminates timeout and cancelled work."""
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from decimal import Decimal


def _limits():
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    elif os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                        ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IoCounters), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        limits.process_memory = 768 * 1024**2
        if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
            raise OSError(ctypes.get_last_error(), "Could not establish query-worker memory limit")
        # The process owns this anonymous handle until exit; closing it early removes the limit.


def _serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    raise TypeError(type(value).__name__)


def _peak_memory():
    if os.name == "posix":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if sys.platform == "linux" else 1)
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
            "peak_working_set", "working_set", "peak_paged_pool", "paged_pool", "peak_nonpaged_pool", "nonpaged_pool", "pagefile", "peak_pagefile")]
    counters = Counters()
    counters.size = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.size):
        return None
    return counters.peak_working_set


def execute(snapshot, queries, cancel_event=None, timeout=10):
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("Review cancelled.")
    process = subprocess.Popen([sys.executable, "-X", "faulthandler", "-m", "queryproof.worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    payload = json.dumps({"snapshot": snapshot, "queries": queries}).encode()
    started = time.monotonic()
    try:
        first = True
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Review cancelled; the query worker was terminated.")
            if sys.platform == "linux":
                try:
                    with open(f"/proc/{process.pid}/status") as status:
                        resident = next((int(line.split()[1]) * 1024 for line in status if line.startswith("VmRSS:")), 0)
                    if resident > 768 * 1024**2:
                        raise MemoryError("Query worker exceeded the 768 MB resident-memory budget and was terminated.")
                except FileNotFoundError:
                    pass
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError(f"Query worker exceeded {timeout:g} seconds and was terminated.")
            try:
                stdout, stderr = process.communicate(input=payload if first else None, timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                first = False
        if process.returncode:
            raise RuntimeError(f"Query worker exited with code {process.returncode}: " + stderr.decode(errors="replace")[-1000:])
        response = json.loads(stdout)
        if "error" in response:
            raise ValueError(response["error"])
        return response["results"]
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def main():
    import duckdb
    # Linux RSS is supervised by the parent: DuckDB reserves a large sparse virtual arena.
    _limits()
    request = json.load(sys.stdin)
    connection = duckdb.connect(config={
        "enable_external_access": "false", "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false", "allow_unsigned_extensions": "false",
        "memory_limit": "256MB", "threads": "1", "max_temp_directory_size": "0B",
    })
    try:
        for name, table in request["snapshot"]["tables"].items():
            from .importer import identifier, TYPE
            identifier(name)
            for column in table["columns"]:
                identifier(column["name"])
                if not TYPE.fullmatch(column["type"]):
                    raise ValueError("Invalid snapshot type")
            columns = ", ".join(f'"{c["name"]}" {c["type"]}' for c in table["columns"])
            connection.execute(f'CREATE TABLE "{name}" ({columns})')
            if table["rows"]:
                slots = ",".join("unnest(?)" for _ in table["columns"])
                for offset in range(0, len(table["rows"]), 10_000):
                    batch = table["rows"][offset:offset + 10_000]
                    connection.execute(f'INSERT INTO "{name}" SELECT {slots}', [[row[c["name"]] for row in batch] for c in table["columns"]])
        connection.execute("SET lock_configuration = true")
        results = []
        for query in request["queries"]:
            cursor = connection.execute(query)
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            results.append({"columns": columns, "rows": rows, "row_count": len(rows)})
        for result in results:
            result["worker_peak_rss_bytes"] = _peak_memory()
        print(json.dumps({"results": results}, default=_serialize))
    except Exception as error:
        print(json.dumps({"error": str(error)}))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
