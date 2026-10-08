"""
Background Job Manager Tool for Agentic Shell Environments.

This module provides a standalone execution tool designed to be invoked by a
master LLM agent. It detaches commands from the controlling terminal, redirects
I/O, tracks processes via background monitoring threads, and issues asynchronous
alerts upon completion without blocking the main execution thread.
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import uuid


def _send_system_alert(pid: int, command: str, exit_code: int) -> None:
    """
    Triggers a system-level asynchronous alert stating whether the process
    completed successfully or with errors.

    Notification strategy:
      1. Linux desktop: `notify-send` (if desktop notification daemon is available).
      2. Linux headless: Write directly to `/dev/tty` (controlling terminal) with ASCII bell.
      3. Fallback: Write alert message to `sys.stderr`.
    """
    if exit_code == 0:
        status_label = "SUCCESS"
        status_desc = "finished successfully (exit code 0)"
        urgency = "normal"
    elif exit_code < 0:
        # Process was terminated by a signal on POSIX
        try:
            sig_name = signal.Signals(-exit_code).name
            status_label = f"KILLED ({sig_name})"
            status_desc = f"terminated by signal {sig_name} (code {exit_code})"
        except (ValueError, AttributeError):
            status_label = f"KILLED (signal {-exit_code})"
            status_desc = f"terminated by signal {-exit_code}"
        urgency = "critical"
    else:
        status_label = f"FAILED ({exit_code})"
        status_desc = f"finished with errors (exit code {exit_code})"
        urgency = "critical"

    cmd_preview = (command[:60] + "...") if len(command) > 60 else command
    alert_title = f"Background Job [{pid}] {status_label}"
    alert_body = f"Command: {cmd_preview}\nResult: {status_desc}"

    alert_sent = False

    # 1. Desktop GUI Notification (Linux notify-send)
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                [
                    "notify-send",
                    "-u", urgency,
                    "-a", "Background Job Manager",
                    alert_title,
                    alert_body,
                ],
                check=False,
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            alert_sent = True
        except Exception:
            pass

    # 2. Controlling Terminal write for headless Linux environments (/dev/tty)
    # /dev/tty directly reaches the interactive terminal of the session, even
    # when stdout/stderr of worker processes are redirected elsewhere.
    try:
        with open("/dev/tty", "w", encoding="utf-8") as tty:
            # \a emits an ASCII bell to audibly/visually notify the operator
            tty.write(f"\r\n\a[ALERT] {alert_title}: {status_desc} | Command: {cmd_preview}\r\n")
            tty.flush()
            alert_sent = True
    except (OSError, IOError):
        # /dev/tty is unavailable in non-POSIX environments, daemonized services, or subshells without tty
        pass

    # 3. Graceful fallback if neither GUI notification nor /dev/tty was dispatched
    if not alert_sent:
        try:
            sys.stderr.write(f"\r\n[ALERT] {alert_title}: {status_desc} | Command: {cmd_preview}\r\n")
            sys.stderr.flush()
        except Exception:
            pass


def _monitor_job(
    proc: subprocess.Popen[Any],
    pid: int,
    command: str,
    log_path: Path,
) -> None:
    """
    Lightweight, non-blocking monitoring routine running inside a daemon thread.
    
    Waits for process termination, writes a completion record into the log file,
    and dispatches a system-level asynchronous alert.
    """
    # Wait for the child process to terminate (blocks only this background thread)
    exit_code = proc.wait()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Append completion metadata to the log file for auditing
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            status_msg = "SUCCESS (code 0)" if exit_code == 0 else f"ERROR (exit code {exit_code})"
            f.write(f"\n--- [Job {pid} completed: {status_msg} at {timestamp}] ---\n")
    except Exception:
        pass

    # Trigger system-level asynchronous alert
    _send_system_alert(pid=pid, command=command, exit_code=exit_code)


def run_background_job(command: str, log_file: Optional[str] = None) -> str:
    """
    Executes a shell command in the background, completely detached from the current terminal session.

    Replicates fork(), setsid(), and nohup semantics using standard library `subprocess`:
      - Detaches from controlling terminal/session via start_new_session=True (calls setsid() on POSIX).
      - Closes stdin via subprocess.DEVNULL (prevents waiting for user input).
      - Redirects stdout and stderr to the specified log file.
      - Returns immediately with PID and log path without blocking the caller.
      - Spawns a dedicated monitoring thread to alert upon process exit.

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


# Standard JSON tool schema definition for LLM function calling
BACKGROUND_JOB_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_background_job",
        "description": (
            "Executes a shell command in the background, completely detached from the current "
            "terminal session (replicates fork(), setsid(), and nohup). Standard output and standard "
            "error are redirected to the specified log file. The process does not wait for stdin. "
            "Returns immediately with the PID and log file location. A background monitoring thread "
            "tracks the process and triggers a system alert when it finishes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command string to execute in the background.",
                },
                "log_file": {
                    "type": "string",
                    "description": (
                        "Optional file path where stdout and stderr will be redirected. "
                        "If omitted, a default timestamped log file is automatically created."
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


if __name__ == "__main__":
    import json
    import time

    print("=== Background Job Manager Tool Schema ===")
    print(json.dumps(BACKGROUND_JOB_TOOL_SCHEMA, indent=2))
    print("\n=== Test Execution ===")

    # Run a quick background command to demonstrate functionality
    test_cmd = (
        f'"{sys.executable}" -c '
        '"import time; print(\'Running background task step 1...\'); '
        'time.sleep(1); print(\'Finished background task step 2.\')"'
        if platform.system() != "Windows"
        else "echo Running background job step 1... & timeout /t 1 /nobreak >nul & echo Finished background job step 2."
    )
    result = run_background_job(test_cmd, log_file="sample_job.log")
    print(f"Tool Output: {result}")

    print("Main thread continuing immediately without blocking...")
    # Wait briefly for demo purposes so we can observe log completion
    time.sleep(2)

    if Path("sample_job.log").exists():
        print("\n=== Generated Log Content ===")
        print(Path("sample_job.log").read_text(encoding="utf-8"))
        Path("sample_job.log").unlink()
