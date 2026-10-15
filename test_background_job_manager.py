"""
Unit tests for the Background Job Manager Agent (Agent 5).

Verifies:
  - Process detachment and non-blocking return.
  - Multi-tier alert generation with immediate output preview.
  - get_job_status, read_job_logs, and list_background_jobs inspection tools.
  - stop_background_job process termination tool.
  - Security guardrails & regex blacklist for destructive commands.
  - execute_tool LLM dispatcher.
"""

import asyncio
import os
import pathlib
import platform
import time
import unittest
import uuid

from alerts import extract_log_preview
from background_job_manager import (
    AGENT_TOOLS_SCHEMA,
    BACKGROUND_JOB_TOOL_SCHEMA,
    execute_tool,
    get_job_status,
    list_background_jobs,
    read_job_logs,
    run_background_job,
    stop_background_job,
)
from job_status import is_pid_alive
from mcp_server import mcp as mcp_instance
from security import SecurityViolationError, check_command_safety, validate_command


class TestBackgroundJobManager(unittest.TestCase):
    def setUp(self):
        # Unique log file per test to prevent Windows file-locking collisions
        self.unique_id = uuid.uuid4().hex[:6]
        self.test_log = pathlib.Path(f"test_run_{self.unique_id}.log")

    def tearDown(self):
        # Gracefully cleanup temporary log files
        if hasattr(self, "test_log") and self.test_log.exists():
            for _ in range(3):
                try:
                    self.test_log.unlink()
                    break
                except OSError:
                    time.sleep(0.1)

    def test_schema_validity(self):
        """Verify the JSON tool schemas adhere to LLM function calling spec."""
        self.assertEqual(len(AGENT_TOOLS_SCHEMA), 5)
        tool_names = [t["function"]["name"] for t in AGENT_TOOLS_SCHEMA]
        expected_names = [
            "run_background_job",
            "get_job_status",
            "read_job_logs",
            "list_background_jobs",
            "stop_background_job",
        ]
        self.assertEqual(tool_names, expected_names)
        self.assertEqual(BACKGROUND_JOB_TOOL_SCHEMA["function"]["name"], "run_background_job")

    def test_empty_command_raises(self):
        """Verify empty command string raises ValueError."""
        with self.assertRaises(ValueError):
            run_background_job("")
        with self.assertRaises(ValueError):
            run_background_job("   ")

    def test_successful_execution_and_output_preview(self):
        """Verify execution, immediate return, and output preview extraction."""
        start_time = time.time()
        ret = run_background_job("echo Line 1 Output & echo Line 2 Output", log_file=str(self.test_log))
        duration = time.time() - start_time

        # Ensure call returned almost instantaneously (< 0.25s)
        self.assertLess(duration, 0.25)
        self.assertIn("PID:", ret)
        self.assertIn(self.test_log.name, ret)

        # Allow background process and thread to finish
        time.sleep(1.0)
        self.assertTrue(self.test_log.exists())
        content = self.test_log.read_text(encoding="utf-8")
        self.assertIn("Line 1 Output", content)
        self.assertIn("completed: SUCCESS", content)

        # Verify output preview extraction
        preview = extract_log_preview(self.test_log, max_lines=2)
        self.assertIn("Line 2 Output", preview)

    def test_get_job_status_tool(self):
        """Verify get_job_status inspects runtime state and log preview."""
        ret = run_background_job("echo Processing records...", log_file=str(self.test_log))
        pid = int(ret.split("PID: ")[1].split(")")[0])

        report = get_job_status(pid, tail_lines=3)
        self.assertIn(f"Job Status Report: PID {pid}", report)
        self.assertIn("echo Processing records...", report)

        time.sleep(1.0)
        final_report = get_job_status(pid)
        self.assertIn("COMPLETED", final_report)

    def test_read_job_logs_tool(self):
        """Verify read_job_logs reads logs by PID or direct path."""
        ret = run_background_job("echo Log Entry Alpha & echo Log Entry Beta", log_file=str(self.test_log))
        pid = int(ret.split("PID: ")[1].split(")")[0])

        time.sleep(1.0)

        # 1. Read by PID
        logs_by_pid = read_job_logs(pid=pid, lines=5)
        self.assertIn("Log Entry Alpha", logs_by_pid)
        self.assertIn("Log Entry Beta", logs_by_pid)

        # 2. Read by log file path
        logs_by_path = read_job_logs(log_file=str(self.test_log), lines=5)
        self.assertIn("Log Entry Beta", logs_by_path)

    def test_list_background_jobs_tool(self):
        """Verify list_background_jobs returns tracked job table."""
        run_background_job("echo ListableJob", log_file=str(self.test_log))
        listing = list_background_jobs()
        self.assertIn("PID", listing)
        self.assertIn("STATUS", listing)
        self.assertIn("ListableJob", listing)

    def test_stop_background_job_tool(self):
        """Verify stop_background_job terminates an active long-running process."""
        # Spawn a long-running process
        cmd = "ping -n 15 127.0.0.1 >nul" if platform.system() == "Windows" else "sleep 15"
        ret = run_background_job(cmd, log_file=str(self.test_log))
        pid = int(ret.split("PID: ")[1].split(")")[0])

        # Verify process is initially running
        self.assertTrue(is_pid_alive(pid))

        # Stop process
        result_msg = stop_background_job(pid, force=True)
        self.assertIn("Successfully", result_msg)

        # Verify process terminated
        time.sleep(0.5)
        self.assertFalse(is_pid_alive(pid))

    def test_security_guardrail_blocks_destructive_commands(self):
        """Verify regex blacklist blocks high-risk and destructive system commands."""
        destructive_cmds = [
            "rm -rf /",
            "rm -fr /",
            "rm -rf /*",
            "rm -rf --no-preserve-root /",
            ":(){ :|:& };:",
            "mkfs.ext4 /dev/sda1",
            "format C:",
            "chmod 777 /",
            "chmod -R 777 /etc",
        ]

        for cmd in destructive_cmds:
            with self.subTest(command=cmd):
                # 1. Direct validation check
                with self.assertRaises(SecurityViolationError):
                    validate_command(cmd)

                # 2. Execution block check
                with self.assertRaises(SecurityViolationError):
                    run_background_job(cmd, log_file=str(self.test_log))

    def test_security_guardrail_allows_benign_commands(self):
        """Verify benign and safe administrative commands pass validation."""
        safe_cmds = [
            "echo Hello World",
            "python -m http.server 8080",
            "pytest tests/",
            "git status",
            "cat /var/log/syslog",
            "npm run build",
        ]

        for cmd in safe_cmds:
            with self.subTest(command=cmd):
                is_safe, _, _ = check_command_safety(cmd)
                self.assertTrue(is_safe, f"Safe command incorrectly flagged: {cmd}")

    def test_execute_tool_dispatcher(self):
        """Verify LLM dispatcher calls tools with dictionary parameters."""
        ret = execute_tool(
            "run_background_job",
            {"command": "echo Dispatcher OK", "log_file": str(self.test_log)},
        )
        self.assertIn("PID:", ret)

        status_out = execute_tool("list_background_jobs", {})
        self.assertIn("Dispatcher OK", status_out)

        with self.assertRaises(ValueError):
            execute_tool("unknown_tool", {})

    def test_mcp_server_registration(self):
        """Verify the MCP Server registers all 5 background agent tools."""
        registered_tool_names = [t.name for t in mcp_instance._tool_manager.list_tools()]
        expected_tools = [
            "run_background_job",
            "get_job_status",
            "stop_background_job",
            "read_job_logs",
            "list_background_jobs",
        ]
        for tool_name in expected_tools:
            self.assertIn(tool_name, registered_tool_names)

    def test_mcp_server_tool_call(self):
        """Verify calling background agent tools via the MCP Server async interface."""
        async def run_mcp_test():
            # 1. Run background job via MCP
            res = await mcp_instance.call_tool(
                "run_background_job",
                {"command": "echo MCP Execution Test", "log_file": str(self.test_log)},
            )
            # FastMCP returns tuple: (content_list, extra_dict)
            text_out = res[0][0].text
            self.assertIn("PID:", text_out)

            # 2. Check list_background_jobs via MCP
            list_res = await mcp_instance.call_tool("list_background_jobs", {})
            list_text = list_res[0][0].text
            self.assertIn("MCP Execution Test", list_text)

        asyncio.run(run_mcp_test())

    def test_mcp_server_security_guardrail(self):
        """Verify MCP Server intercepts destructive commands and raises ToolError wrapping SecurityViolationError."""
        from mcp.server.fastmcp.exceptions import ToolError

        async def run_security_test():
            with self.assertRaises(ToolError) as ctx:
                await mcp_instance.call_tool(
                    "run_background_job",
                    {"command": "rm -rf /", "log_file": str(self.test_log)},
                )
            self.assertIn("Security Guardrail", str(ctx.exception))
            self.assertIsInstance(ctx.exception.__cause__, SecurityViolationError)

        asyncio.run(run_security_test())


if __name__ == "__main__":
    unittest.main()

