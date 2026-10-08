"""
Alerting Subsystem for Background Job Manager Agent.

Handles system-level asynchronous notifications (GUI notifications, /dev/tty terminal
bell writes, and stderr fallback) with an immediate output preview extracted from
the background job's log file.
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional


def extract_log_preview(log_path: Path, max_lines: int = 5, max_chars: int = 400) -> str:
    """
    Extracts the last few lines from a log file to serve as a preview in alerts.
    
    Args:
        log_path: Path to the target log file.
        max_lines: Maximum number of trailing lines to include (default: 5).
        max_chars: Character limit to prevent oversized alerts.

    Returns:
        Formatted string containing the output preview, or an empty note if no output exists.
    """
    if not log_path or not log_path.exists():
        return "(no log output available)"

    try:
        content = log_path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            return "(log file is empty)"

        lines = content.splitlines()
        # Filter out completion separator headers if they were already written
        relevant_lines = [line for line in lines if not line.startswith("--- [Job ")]
        if not relevant_lines:
            relevant_lines = lines

        preview_lines = relevant_lines[-max(1, max_lines):]
        preview_text = "\n".join(preview_lines)

        if len(preview_text) > max_chars:
            preview_text = "..." + preview_text[-(max_chars - 3):]

        return preview_text
    except Exception as err:
        return f"(unable to read log preview: {err})"


def send_system_alert(
    pid: int,
    command: str,
    exit_code: int,
    output_preview: Optional[str] = None,
) -> None:
    """
    Dispatches an asynchronous alert when a job finishes, including the output preview.

    Notification cascade:
      1. Linux desktop: `notify-send` (if desktop notification daemon is available).
      2. Linux headless/SSH: Direct write to `/dev/tty` with an ASCII bell (`\\a`).
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

    preview_section = f"\nOutput Preview:\n{output_preview}" if output_preview else ""
    alert_body = f"Command: {cmd_preview}\nResult: {status_desc}{preview_section}"

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
    try:
        with open("/dev/tty", "w", encoding="utf-8") as tty:
            # \a emits an ASCII bell to audibly notify the operator
            tty.write(f"\r\n\a[ALERT] {alert_title}: {status_desc}\r\nCommand: {cmd_preview}{preview_section}\r\n")
            tty.flush()
            alert_sent = True
    except (OSError, IOError):
        pass

    # 3. Graceful fallback if neither GUI notification nor /dev/tty was dispatched
    if not alert_sent:
        try:
            sys.stderr.write(f"\r\n[ALERT] {alert_title}: {status_desc}\r\nCommand: {cmd_preview}{preview_section}\r\n")
            sys.stderr.flush()
        except Exception:
            pass
