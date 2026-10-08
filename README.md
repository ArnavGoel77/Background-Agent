# Background Job Manager Tool

A standalone execution tool designed for a master LLM in an Agentic Shell environment to dispatch long-running commands into the background without blocking the agent's reasoning loop.

---

## Features

- **True Detachment (`fork()`, `setsid()`, `nohup`)**:
  - Sets `start_new_session=True` (`os.setsid()` on POSIX) to establish a new process group and decouple the child from the controlling terminal session.
  - Ignores terminal disconnections (`SIGHUP`).
- **No Stdin Blocking**:
  - Binds `stdin` to `subprocess.DEVNULL` to prevent interactive hangs.
- **Log Stream Redirection**:
  - Redirects both standard output (`stdout`) and standard error (`stderr`) to a designated or auto-generated log file.
- **Instant Non-Blocking Return**:
  - Immediately yields process metadata (`PID` and `log_file` path) back to the caller.
- **Non-Blocking Background Monitoring Thread**:
  - A lightweight daemon thread waits on the child process exit code.
  - Automatically appends execution telemetry to the log file.
  - Emits system-level asynchronous alerts:
    - **Linux Desktop**: `notify-send` notification.
    - **Linux Headless**: Direct terminal write to `/dev/tty` with an ASCII bell (`\a`).
    - **Fallback**: Alert to `sys.stderr`.

---

## Tool Files

- [`background_job_manager.py`](file:///c:/Background-Agent/background_job_manager.py): Main implementation and JSON tool schema definition.
- [`test_background_job_manager.py`](file:///c:/Background-Agent/test_background_job_manager.py): Unit test suite.
