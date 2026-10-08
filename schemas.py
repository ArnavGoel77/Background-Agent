"""
Tool Schemas and LLM Function Calling Registry.

Defines the JSON schema specifications conforming to OpenAI / Anthropic / Gemini
function calling formats for all tools exposed by the Background Job Manager Agent.
"""

from __future__ import annotations

from typing import Any, Dict, List


RUN_BACKGROUND_JOB_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_background_job",
        "description": (
            "Executes a shell command in the background, completely detached from the current "
            "terminal session using fork(), setsid(), and nohup semantics. Standard output and "
            "standard error are redirected to the specified log file. Stdin is closed. "
            "Returns immediately with the PID and log path without blocking the agent. "
            "A background monitoring thread automatically tracks completion and emits an alert "
            "with an immediate output preview when the job finishes."
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

GET_JOB_STATUS_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_job_status",
        "description": (
            "Inspects the status, runtime information, and recent output lines of a "
            "running or completed background job."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "Process ID (PID) of the background job to inspect.",
                },
                "tail_lines": {
                    "type": "integer",
                    "description": "Number of trailing log lines to preview (default: 5).",
                },
            },
            "required": ["pid"],
            "additionalProperties": False,
        },
    },
}

READ_JOB_LOGS_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_job_logs",
        "description": (
            "Reads log output from a background job by PID or explicit log file path, "
            "allowing the LLM to inspect intermediate or final execution results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "Optional process ID of the job whose log file to inspect.",
                },
                "log_file": {
                    "type": "string",
                    "description": "Optional direct path to the log file.",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of trailing lines to read (default: 20; 0 for full log).",
                },
            },
            "additionalProperties": False,
        },
    },
}

LIST_BACKGROUND_JOBS_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_background_jobs",
        "description": (
            "Lists all background jobs tracked during the current session, showing their "
            "PIDs, commands, start times, and execution statuses."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}

# Master list of all tools exposed by Agent 5
AGENT_TOOLS_SCHEMA: List[Dict[str, Any]] = [
    RUN_BACKGROUND_JOB_SCHEMA,
    GET_JOB_STATUS_SCHEMA,
    READ_JOB_LOGS_SCHEMA,
    LIST_BACKGROUND_JOBS_SCHEMA,
]

# Backwards compatible alias
BACKGROUND_JOB_TOOL_SCHEMA = RUN_BACKGROUND_JOB_SCHEMA
