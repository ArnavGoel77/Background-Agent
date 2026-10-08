"""
Unit tests for the Background Job Manager Agent (Agent 5).

Verifies:
  - Process detachment and non-blocking return.
  - Multi-tier alert generation with immediate output preview.
  - get_job_status and read_job_logs inspection tools.
  - list_background_jobs and execute_tool LLM dispatcher.
"""

import os
import pathlib
import time
import unittest

from alerts import extract_log_preview
from background_job_manager import (
    AGENT_TOOLS_SCHEMA,
    BACKGROUND_JOB_TOOL_SCHEMA,
    execute_tool,
    get_job_status,
    list_background_jobs,
    read_job_logs,
    run_background_job,
)


class TestBackgroundJobManager(unittest.TestCase):
    def setUp(self):
        self.test_log = pathlib.Path("test_run.log")
        if self.test_log.exists():
            self.test_log.unlink()

    def tearDown(self):
        if self.test_log.exists():
            try:
                self.test_log.unlink()
            except OSError:
                pass

    def test_schema_validity(self):
        """Verify the JSON tool schemas adhere to LLM function calling spec."""
        self.assertEqual(len(AGENT_TOOLS_SCHEMA), 4)
        tool_names = [t["function"]["name"] for t in AGENT_TOOLS_SCHEMA]
        expected_names = [
            "run_background_job",
            "get_job_status",
            "read_job_logs",
            "list_background_jobs",
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
        logs_by_path = read_job_logs(log_file=str(self.test_log), lines=2)
        self.assertIn("Log Entry Beta", logs_by_path)

    def test_list_background_jobs_tool(self):
        """Verify list_background_jobs returns tracked job table."""
        run_background_job("echo ListableJob", log_file=str(self.test_log))
        listing = list_background_jobs()
        self.assertIn("PID", listing)
        self.assertIn("STATUS", listing)
        self.assertIn("ListableJob", listing)

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


if __name__ == "__main__":
    unittest.main()
