"""
Security Guardrail and Command Sanitization Subsystem for Background Job Manager Agent.

Implements the Security & Guardrail Framework (Review 2, Chapter 3.3):
  - Pre-execution command sanitization and regex-based blacklisting of destructive commands.
  - Intercepts malicious, destructive, or runaway system commands before process spawn.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple


class SecurityViolationError(ValueError):
    """Raised when a command violates security guardrail policies."""
    pass


# Compiled regex patterns for blacklisted destructive commands
BLACKLIST_RULES: List[Tuple[str, re.Pattern[str], str]] = [
    (
        "ROOT_FILESYSTEM_DELETION",
        re.compile(
            r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f*(\s+--no-preserve-root)?\s+(/\s*$|/\*|~\s*$|~\*|\.\s*$)",
            re.IGNORECASE,
        ),
        "Recursive deletion of root, home, or current directory (rm -rf /)",
    ),
    (
        "NO_PRESERVE_ROOT",
        re.compile(r"--no-preserve-root", re.IGNORECASE),
        "Explicit bypass of root filesystem protection (--no-preserve-root)",
    ),
    (
        "FORK_BOMB",
        re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE),
        "Denial-of-Service bash fork bomb (:(){ :|:& };:)",
    ),
    (
        "DISK_FORMAT",
        re.compile(r"\b(mkfs(\.[a-zA-Z0-9]+)?|fdisk|parted)\s+/dev/\S+", re.IGNORECASE),
        "Direct disk partition or filesystem formatting",
    ),
    (
        "RAW_DISK_OVERWRITE",
        re.compile(r"\bdd\s+.*of=(/dev/|\\\\\\.\\)[a-zA-Z0-9]+", re.IGNORECASE),
        "Direct raw disk block overwrite via dd",
    ),
    (
        "WINDOWS_SYSTEM_FORMAT",
        re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),
        "Drive format command on Windows",
    ),
    (
        "WINDOWS_ROOT_DELETION",
        re.compile(r"\b(rd|del)\s+/[sS]\s+/[qQ]\s+[a-zA-Z]:\\", re.IGNORECASE),
        "Recursive root drive wipe on Windows",
    ),
    (
        "CRITICAL_SYSTEM_PERMISSIONS",
        re.compile(r"\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?777\s+(/\s*$|/etc|/boot|/usr)", re.IGNORECASE),
        "Unrestricted recursive permission grant on critical root paths",
    ),
    (
        "OVERWRITE_SYSTEM_AUTH",
        re.compile(r"[>|>>]\s*(/etc/shadow|/etc/passwd|/etc/sudoers)", re.IGNORECASE),
        "Attempt to overwrite critical system authentication files",
    ),
]


def check_command_safety(command: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Evaluates whether a command is safe to execute against the blacklist rules.

    Args:
        command: The shell command string to validate.

    Returns:
        A tuple of (is_safe, rule_name, rule_description).
        If safe, returns (True, None, None).
    """
    if not command or not command.strip():
        return False, "EMPTY_COMMAND", "Command string cannot be empty."

    cmd_normalized = command.strip()

    for rule_name, pattern, description in BLACKLIST_RULES:
        if pattern.search(cmd_normalized):
            return False, rule_name, description

    return True, None, None


def validate_command(command: str) -> None:
    """
    Validates a command against destructive command blacklists.
    Raises SecurityViolationError if a blacklisted pattern is detected.

    Args:
        command: The shell command to validate.

    Raises:
        SecurityViolationError: If the command is deemed destructive or unsafe.
    """
    is_safe, rule_name, description = check_command_safety(command)
    if not is_safe:
        raise SecurityViolationError(
            f"Command execution blocked by Security Guardrail [{rule_name}]: {description}."
        )
