"""
Model Context Protocol (MCP) Server for the Background Job Manager Agent (Agent 5).

Domain: Process & CPU Management (Linux Agentic Shell Project)
Architecture:
  - Exposes process detachment, monitoring, inspection, termination, and log reading
    tools to the Parent Shell via the Model Context Protocol (MCP).
  - The Background Agent contains NO internal LLM; it acts as a specialized execution
    and monitoring engine for the central Parent Shell LLM.
  - Communicates over standard input/output (stdio) transport using JSON-RPC.
"""

from __future__ import annotations

import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from background_job_manager import run_background_job as _run_background_job
from job_status import (
    get_job_status as _get_job_status,
    list_background_jobs as _list_background_jobs,
    read_job_logs as _read_job_logs,
    stop_background_job as _stop_background_job,
)

# Initialize FastMCP Server instance
mcp = FastMCP("background-job-manager")


@mcp.tool()
def run_background_job(command: str, log_file: Optional[str] = None) -> str:
    """
    Executes a shell command in the background, completely detached from the current
    terminal session using fork(), setsid(), and nohup semantics. Standard output
    and standard error are redirected to the specified log file. Stdin is closed.
    Returns immediately with the PID and log path without blocking the agent.
    A background monitoring thread automatically tracks completion and emits an alert
    with an immediate output preview when the job finishes.
    """
    return _run_background_job(command=command, log_file=log_file)


@mcp.tool()
def get_job_status(pid: int, tail_lines: int = 5) -> str:
    """
    Inspects the execution status, runtime duration, and trailing output lines
    of a running or completed background job.
    """
    return _get_job_status(pid=pid, tail_lines=tail_lines)


@mcp.tool()
def stop_background_job(pid: int, force: bool = False) -> str:
    """
    Terminates an active background job process by PID. Supports both graceful
    termination (SIGTERM / taskkill) and forced kill (SIGKILL / taskkill /F).
    """
    return _stop_background_job(pid=pid, force=force)


@mcp.tool()
def read_job_logs(
    pid: Optional[int] = None,
    log_file: Optional[str] = None,
    lines: int = 20,
) -> str:
    """
    Reads log output from a background job by either PID or explicit log file path,
    allowing the Parent Shell LLM to inspect intermediate or final execution results.
    """
    return _read_job_logs(pid=pid, log_file=log_file, lines=lines)


@mcp.tool()
def list_background_jobs() -> str:
    """
    Lists all background jobs tracked during the current session, showing their
    PIDs, commands, start times, and execution statuses.
    """
    return _list_background_jobs()


if __name__ == "__main__":
    # Expose server over stdio transport so the Parent Shell can connect as an MCP client
    mcp.run(transport="stdio")
