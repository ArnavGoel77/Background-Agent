# Background Job Manager Agent (Agent 5)

Domain: **Process & CPU Management**  
Component of the next-generation **Linux Agentic Shell**.

---

## Architecture Overview

A modular execution and monitoring toolkit designed for the master LLM to dispatch long-running commands into the background, monitor their progress, inspect runtime output, and receive asynchronous completion notifications with an immediate output preview.

```
Background-Agent/
├── alerts.py                    # Multi-channel alerting (GUI, /dev/tty + \a, stderr) with log preview
├── job_status.py                # Process health checks, get_job_status, stop_background_job, read_job_logs
├── security.py                  # Security guardrail framework with regex-based destructive command blacklist
├── background_job_manager.py    # Process detachment (fork/setsid/nohup), daemon monitoring, dispatcher
├── mcp_server.py                # Model Context Protocol (FastMCP) server over stdio transport
├── schemas.py                   # LLM Function-Calling schemas (OpenAI/Gemini/Anthropic compatible)
├── test_background_job_manager.py # Comprehensive unit test suite (13/13 tests passing)
└── REVIEW_2_REPORT.md           # OS Lab Review 2 Comprehensive Technical Report
```

---

## Key Features

1. **Security Guardrails & Command Sanitization**:
   - Pre-execution validation using compiled regular expressions to reject destructive commands before child process creation.
   - Blocks recursive root wipes (`rm -rf /`), raw disk formats (`mkfs`, `format`), fork bombs (`:(){ :|:& };:`), and unauthorized permission modifications (`chmod 777 /`).
2. **True Detachment (`fork()`, `setsid()`, `nohup`)**:
   - Uses `start_new_session=True` (`os.setsid()` on POSIX) to establish a new process group and decouple from the controlling terminal session.
   - Ignores terminal disconnections (`SIGHUP`).
   - Binds `stdin` to `subprocess.DEVNULL` to prevent interactive hangs.
   - Redirects both standard output (`stdout`) and standard error (`stderr`) to a designated log file.
3. **Instant Non-Blocking Return**:
   - Immediately yields process metadata (`PID` and `log_file` path) back to the caller in milliseconds.
4. **Alerts with Output Preview**:
   - Background daemon thread automatically captures the trailing lines of the log upon process exit.
   - Dispatches a system alert containing the immediate result preview across:
     - **Linux Desktop**: `notify-send` with urgency levels.
     - **Linux Headless / SSH**: Direct write to `/dev/tty` with an audible ASCII bell (`\a`).
     - **Fallback**: Alert to `sys.stderr`.
5. **Dedicated LLM Inspection & Process Control Tools**:
   - `get_job_status`: Queries whether a PID is running, its start/completion times, and recent log output.
   - `stop_background_job`: Safely terminates or forcefully kills an active background job process.
   - `read_job_logs`: Reads intermediate or final logs by PID or direct log path.
   - `list_background_jobs`: Returns a table of all tracked background jobs.

---

## Tools Exposed to the Master LLM

### 1. `run_background_job(command, log_file=None)`
- **Parameters**: `command` (str, required), `log_file` (str, optional)
- Validates command safety against security blacklists, detaches the command, redirects stdout/stderr to disk, starts monitoring, and returns immediately with the PID and log path.

### 2. `get_job_status(pid, tail_lines=5)`
- **Parameters**: `pid` (int, required), `tail_lines` (int, optional, default: 5)
- Returns job status (`RUNNING`, `COMPLETED`, `FAILED`, `TERMINATED`), runtime, and the last few lines of output.

### 3. `stop_background_job(pid, force=False)`
- **Parameters**: `pid` (int, required), `force` (bool, optional, default: False)
- Gracefully terminates (`SIGTERM`) or forcefully kills (`SIGKILL` / `taskkill /F`) an active background process group.

### 4. `read_job_logs(pid=None, log_file=None, lines=20)`
- **Parameters**: `pid` (int, optional), `log_file` (str, optional), `lines` (int, optional, default: 20)
- Reads the requested number of log lines (or full log if `lines=0`) for a job.

### 5. `list_background_jobs()`
- **Parameters**: None
- Lists all jobs started and tracked during this session.

---

## LLM Function-Calling Usage

```python
from background_job_manager import execute_tool
from schemas import AGENT_TOOLS_SCHEMA

# 1. Master LLM dispatches run_background_job:
output = execute_tool("run_background_job", {
    "command": "mysqldump -u root production_db > dump.sql",
    "log_file": "/tmp/db_dump.log"
})

# 2. Master LLM checks status later:
status = execute_tool("get_job_status", {"pid": 12345, "tail_lines": 5})

# 3. Master LLM reads detailed logs:
logs = execute_tool("read_job_logs", {"pid": 12345, "lines": 50})
```

---

## Model Context Protocol (MCP) Server

Agent 5 is wrapped as an **MCP Server** via `mcp_server.py` using `FastMCP`. The Parent Shell connects to Agent 5 over standard I/O (`stdio` JSON-RPC transport).

### Running the MCP Server
```bash
python mcp_server.py
# or
python -m mcp_server
```

### Parent Shell MCP Client Configuration
Add Agent 5 to your Parent Shell's MCP client configuration file (e.g., `mcp_config.json`):
```json
{
  "mcpServers": {
    "background-job-manager": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "C:/Users/Shobit/Background-Agent"
    }
  }
}
```

---

## Documentation
- See **[REVIEW_2_REPORT.md](REVIEW_2_REPORT.md)** for the complete Operating Systems (BCSE303L) Review 2 report, system architecture diagrams, security policy specifications, and benchmarking data.

