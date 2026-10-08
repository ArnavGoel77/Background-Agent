"""
Job Tracking and Status Inspection Subsystem for Background Job Manager Agent.

Provides dedicated inspection tools (get_job_status, read_job_logs, list_jobs)
allowing the master LLM to inspect running or completed background jobs and tail logs.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


_LOCK = threading.Lock()
_JOBS: Dict[int, Dict[str, Any]] = {}


def is_pid_alive(pid: int) -> bool:
    """
    Checks whether a process with the given PID is currently active.
    Utilizes Linux /proc/[pid] when available, with os.kill(pid, 0) as fallback.
    """
    if pid <= 0:
        return False

    # 1. Linux /proc filesystem check
    proc_path = Path(f"/proc/{pid}")
    if proc_path.exists():
        return True

    # 2. Cross-platform signal check (signal 0 verifies existence without killing)
    try:
        os.kill(pid, 0)
        return True
    except OSError as err:
        # errno 1 (EPERM) indicates the process exists but belongs to another user
        return getattr(err, "errno", None) == 1


def register_job(pid: int, command: str, log_path: Path) -> None:
    """Registers a newly spawned background job into the tracking database."""
    with _LOCK:
        _JOBS[pid] = {
            "pid": pid,
            "command": command,
            "log_path": log_path,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None,
            "status": "RUNNING",
            "exit_code": None,
        }


def update_job_completion(pid: int, exit_code: int) -> None:
    """Updates a job's status and exit code upon process termination."""
    with _LOCK:
        if pid in _JOBS:
            _JOBS[pid]["status"] = "COMPLETED" if exit_code == 0 else f"FAILED (exit {exit_code})"
            _JOBS[pid]["exit_code"] = exit_code
            _JOBS[pid]["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_job_info(pid: int) -> Optional[Dict[str, Any]]:
    """Retrieves metadata dictionary for a tracked PID."""
    with _LOCK:
        return _JOBS.get(pid)


# ============================================================================
# LLM TOOLS: get_job_status & read_job_logs
# ============================================================================

def get_job_status(pid: int, tail_lines: int = 5) -> str:
    """
    Retrieves the execution status, runtime metrics, and trailing output of a background job.

    Args:
        pid: The process ID (PID) of the background job to inspect.
        tail_lines: Number of trailing log lines to include in the preview (default: 5).

    Returns:
        A human-readable status report for the LLM.
    """
    if pid <= 0:
        return f"Error: Invalid PID {pid}. PID must be a positive integer."

    job = get_job_info(pid)
    alive = is_pid_alive(pid)

    if job is not None:
        cmd = job["command"]
        start_time = job["start_time"]
        end_time = job["end_time"] or ("Still running" if alive else "Unknown")
        status = "RUNNING" if alive else job["status"]
        log_path: Optional[Path] = job["log_path"]
    else:
        # Untracked or external PID
        cmd = "(External / Untracked Process)"
        start_time = "Unknown"
        end_time = "Still running" if alive else "Terminated"
        status = "RUNNING" if alive else "TERMINATED"
        log_path = None

    report_lines: List[str] = [
        f"=== Job Status Report: PID {pid} ===",
        f"Status: {status}",
        f"Command: {cmd}",
        f"Started: {start_time}",
        f"Finished: {end_time}",
    ]

    if log_path:
        report_lines.append(f"Log File: {log_path.as_posix()}")
        if log_path.exists():
            try:
                content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if content:
                    preview = content[-max(1, tail_lines):]
                    report_lines.append(f"\nRecent Output (last {len(preview)} lines):")
                    report_lines.extend(f"  > {line}" for line in preview)
                else:
                    report_lines.append("\nRecent Output: (Log file is currently empty)")
            except Exception as err:
                report_lines.append(f"\nRecent Output: (Unable to read log file: {err})")
        else:
            report_lines.append("\nRecent Output: (Log file has not yet been created on disk)")
    else:
        report_lines.append("Log File: (No log file associated with this PID)")

    return "\n".join(report_lines)


def read_job_logs(
    pid: Optional[int] = None,
    log_file: Optional[str] = None,
    lines: int = 20,
) -> str:
    """
    Reads the logs of a background job by either PID or explicit log file path.

    Args:
        pid: Optional process ID to look up the associated log file.
        log_file: Optional direct path to the log file.
        lines: Number of trailing lines to return (default: 20; 0 returns the full log).

    Returns:
        The requested log contents or an informative error message.
    """
    target_path: Optional[Path] = None

    if log_file and log_file.strip():
        target_path = Path(log_file.strip()).expanduser().resolve()
    elif pid is not None and pid > 0:
        job = get_job_info(pid)
        if job and job.get("log_path"):
            target_path = job["log_path"]
        else:
            return f"Error: No tracked log file found for PID {pid}."
    else:
        return "Error: You must provide either a valid 'pid' or 'log_file' path."

    if not target_path.exists():
        return f"Log file does not exist at: {target_path.as_posix()}"

    try:
        raw_content = target_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not raw_content:
            return f"Log file at {target_path.as_posix()} is currently empty."

        if lines > 0:
            selected_lines = raw_content[-lines:]
            header = f"=== Log Output ({target_path.name}) - Last {len(selected_lines)} of {len(raw_content)} lines ==="
        else:
            selected_lines = raw_content
            header = f"=== Log Output ({target_path.name}) - Full ({len(selected_lines)} lines) ==="

        return header + "\n" + "\n".join(selected_lines)
    except Exception as err:
        return f"Failed to read log file {target_path.as_posix()}: {err}"


def list_background_jobs() -> str:
    """Lists all background jobs tracked by this agent during the session."""
    with _LOCK:
        jobs = list(_JOBS.values())

    if not jobs:
        return "No background jobs currently registered in this session."

    rows = []
    rows.append(f"{'PID':<8} {'STATUS':<15} {'STARTED':<20} {'COMMAND'}")
    rows.append("-" * 75)

    for j in jobs:
        pid = j["pid"]
        alive = is_pid_alive(pid)
        status = "RUNNING" if alive else j.get("status", "TERMINATED")
        start = j.get("start_time", "-")
        cmd = j.get("command", "-")
        if len(cmd) > 30:
            cmd = cmd[:27] + "..."
        rows.append(f"{pid:<8} {status:<15} {start:<20} {cmd}")

    return "\n".join(rows)
