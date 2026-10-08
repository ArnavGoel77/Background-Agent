"""
Unit tests for the Background Job Manager Tool.
"""

import os
import pathlib
import time
import unittest

from background_job_manager import (
    BACKGROUND_JOB_TOOL_SCHEMA,
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
        """Verify the JSON tool schema adheres to OpenAI/LLM function calling spec."""
        self.assertEqual(BACKGROUND_JOB_TOOL_SCHEMA["type"], "function")
        func = BACKGROUND_JOB_TOOL_SCHEMA["function"]
        self.assertEqual(func["name"], "run_background_job")
        self.assertIn("command", func["parameters"]["properties"])
        self.assertIn("log_file", func["parameters"]["properties"])
        self.assertEqual(func["parameters"]["required"], ["command"])

    def test_empty_command_raises(self):
        """Verify empty command string raises ValueError."""
        with self.assertRaises(ValueError):
            run_background_job("")
        with self.assertRaises(ValueError):
            run_background_job("   ")

    def test_successful_execution(self):
        """Verify background execution, log writing, and immediate return."""
        start_time = time.time()
        ret = run_background_job("echo Test Job Started", log_file=str(self.test_log))
        duration = time.time() - start_time

        # Ensure call returned almost instantaneously (< 0.2s)
        self.assertLess(duration, 0.2)
        self.assertIn("PID:", ret)
        self.assertIn(self.test_log.name, ret)

        # Allow background process and thread to finish
        time.sleep(1.0)
        self.assertTrue(self.test_log.exists())
        content = self.test_log.read_text(encoding="utf-8")
        self.assertIn("Test Job Started", content)
        self.assertIn("completed: SUCCESS", content)

    def test_error_exit_code_logging(self):
        """Verify that non-zero exit codes are logged and reported."""
        run_background_job("exit 1", log_file=str(self.test_log))
        time.sleep(1.0)

        self.assertTrue(self.test_log.exists())
        content = self.test_log.read_text(encoding="utf-8")
        self.assertIn("completed: ERROR", content)


if __name__ == "__main__":
    unittest.main()
