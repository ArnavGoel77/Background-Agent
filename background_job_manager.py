"""
Background Job Manager Agent (Agent 5) for Agentic Shell Environments.

Domain: Process & CPU Management
Functionality: Handles shell process detachment, standard output redirection,
               and asynchronous completion notifications with output previews.

Modular Architecture:
  - alerts.py: Multi-tier alerts (desktop GUI, /dev/tty + ASCII bell, stderr) with output preview.
  - job_status.py: Dedicated get_job_status, read_job_logs, and list_background_jobs tools.
  - schemas.py: JSON function-calling schema definitions for LLM integration.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Subsystem imports
from alerts import extract_log_preview, send_system_alert
from job_status import (
    get_job_status,
    list_background_jobs,
    read_job_logs,
    register_job,
    update_job_completion,
)
from schemas import (
    AGENT_TOOLS_SCHEMA,
    BACKGROUND_JOB_TOOL_SCHEMA,
    GET_JOB_STATUS_SCHEMA,
    LIST_BACKGROUND_JOBS_SCHEMA,
    READ_JOB_LOGS_SCHEMA,
)


def _monitor_job(
    proc: subprocess.Popen[Any],
    pid: int,
    command: str,
    log_path: Path,
) -> None:
    """
    Lightweight, non-blocking monitoring routine running inside a daemon thread.
    
    Waits for process termination, extracts the final output preview from the log file,
    writes completion metadata, updates job tracking, and dispatches an alert with the preview.
    """
    # Wait for the child process to terminate (blocks only this background thread)
    exit_code = proc.wait()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Extract immediate output preview for the alert before writing the completion footer
    output_preview = extract_log_preview(log_path, max_lines=5)

    # Append completion metadata to the log file for auditing
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            status_msg = "SUCCESS (code 0)" if exit_code == 0 else f"ERROR (exit code {exit_code})"
            f.write(f"\n--- [Job {pid} completed: {status_msg} at {timestamp}] ---\n")
    except Exception:
        pass

    # Update in-memory job tracking
    update_job_completion(pid, exit_code)

    # Trigger system-level asynchronous alert including the output preview
    send_system_alert(
        pid=pid,
        command=command,
        exit_code=exit_code,
        output_preview=output_preview,
    )


def run_background_job(command: str, log_file: Optional[str] = None) -> str:
    """
    Executes a shell command in the background, completely detached from the current terminal session.

    Replicates fork(), setsid(), and nohup semantics using standard library `subprocess`:
      - Detaches from controlling terminal/session via start_new_session=True (calls setsid() on POSIX).
      - Closes stdin via subprocess.DEVNULL (prevents waiting for user input).
      - Redirects stdout and stderr to the specified log file.
      - Returns immediately with PID and log path without blocking the caller.
      - Spawns a dedicated monitoring thread to alert with an output preview upon process exit.

    Args:
        command: The shell command string to execute in the background.
        log_file: Optional path to the log file. If omitted, defaults to a timestamped file in /tmp or .logs.

    Returns:
        A confirmation string containing the newly created process ID (PID) and log file path.
    """
    if not command or not command.strip():
        raise ValueError("The 'command' parameter cannot be empty.")

    # Resolve destination log file path
    if log_file and log_file.strip():
        resolved_log_path = Path(log_file.strip()).expanduser().resolve()
    else:
        # Default fallback log directory (/tmp on POSIX, current directory .logs otherwise)
        tmp_dir = Path("/tmp")
        base_dir = tmp_dir if tmp_dir.is_dir() else Path.cwd() / ".logs"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_suffix = uuid.uuid4().hex[:6]
        resolved_log_path = (base_dir / f"bg_job_{timestamp}_{unique_suffix}.log").resolve()

    # Ensure parent directory of log file exists
    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)

    # Open log file in append mode (combines stdout and stderr)
    log_handle = open(resolved_log_path, "a", encoding="utf-8")

    try:
        is_windows = platform.system() == "Windows"

        popen_kwargs: Dict[str, Any] = {
            "args": command,
            "shell": True,
            "stdin": subprocess.DEVNULL,       # Prevents process from waiting for stdin
            "stdout": log_handle,              # Redirects stdout to log file
            "stderr": subprocess.STDOUT,       # Redirects stderr to same log file
        }

        if is_windows:
            # Windows process detachment flags
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            if hasattr(subprocess, "DETACHED_PROCESS"):
                creationflags |= subprocess.DETACHED_PROCESS
            popen_kwargs["creationflags"] = creationflags
        else:
            # POSIX detachment:
            # start_new_session=True invokes os.setsid() in child before exec.
            # This creates a new session, sets process group ID to child PID,
            # and completely detaches from the controlling terminal (setsid + nohup behavior).
            popen_kwargs["start_new_session"] = True
            popen_kwargs["close_fds"] = True

            # Use bash if available, else system default shell
            bash_bin = shutil.which("bash")
            if bash_bin:
                popen_kwargs["executable"] = bash_bin

        # Spawn the background process
        proc = subprocess.Popen(**popen_kwargs)

    finally:
        # Close the file handle in the parent process.
        # The child process holds its own inherited duplicate handle to the file.
        log_handle.close()

    # Register job into the tracker database
    register_job(proc.pid, command, resolved_log_path)

    # Spawn lightweight, non-blocking monitoring thread
    monitor_thread = threading.Thread(
        target=_monitor_job,
        args=(proc, proc.pid, command, resolved_log_path),
        daemon=True,
        name=f"JobMonitor-{proc.pid}",
    )
    monitor_thread.start()

    # Return immediately to the caller
    return (
        f"Background job started successfully (PID: {proc.pid}). "
        f"Logs are being written to: {resolved_log_path.as_posix()}"
    )


# ============================================================================
# LLM TOOL DISPATCHER & REGISTRY
# ============================================================================

TOOL_REGISTRY = {
    "run_background_job": run_background_job,
    "get_job_status": get_job_status,
    "read_job_logs": read_job_logs,
    "list_background_jobs": list_background_jobs,
}


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    Executes a tool selected by the master LLM with its parsed arguments.

    Args:
        tool_name: Name of the function chosen by the LLM.
        arguments: Dictionary of keyword arguments parsed by the LLM.

    Returns:
        String result of the tool invocation.
    """
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool '{tool_name}'. Available: {list(TOOL_REGISTRY.keys())}")

    func = TOOL_REGISTRY[tool_name]
    return str(func(**arguments))


if __name__ == "__main__":
    import json
    import time

    print("=== Agent 5 Tools Schemas for Master LLM ===")
    print(json.dumps(AGENT_TOOLS_SCHEMA, indent=2))
    print("\n=== Test Execution ===")

    # Run a test command that produces distinct output lines
    test_cmd = (
        f'"{sys.executable}" -c '
        '"import time; print(\'Step 1: Fetching database records...\'); '
        'time.sleep(1); print(\'Step 2: Database dump completed with 4200 records.\')"'
        if platform.system() != "Windows"
        else "echo Step 1: Fetching database records... & timeout /t 1 /nobreak >nul & echo Step 2: Database dump completed with 4200 records."
    )

    result = run_background_job(test_cmd, log_file="sample_job.log")
    print(f"Tool Output: {result}")
    
    # Extract PID
    pid = int(result.split("PID: ")[1].split(")")[0])

    print("\n[Inspection Tool] Checking status while running:")
    print(get_job_status(pid, tail_lines=2))

    print("\nWaiting for background execution to complete...")
    time.sleep(2)

    print("\n[Inspection Tool] Checking status after completion:")
    print(get_job_status(pid, tail_lines=3))

    print("\n[Inspection Tool] Reading job logs:")
    print(read_job_logs(pid=pid, lines=5))

    if Path("sample_job.log").exists():
        Path("sample_job.log").unlink()
