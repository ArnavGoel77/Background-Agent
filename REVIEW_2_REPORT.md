# Operating Systems (BCSE303L) — Review 2 Project Report

**Project Title:** Natural Language to CLI (NL-to-CLI) AI Agentic Linux Shell  
**Subsystem:** Process & CPU Management Engine (Agent 5 — Background Job Manager)  
**Student Name:** Shobit Khanna  
**Registration Number:** 24BCT0187  
**Academic Year / Semester:** Fall Semester 2026–27  
**Faculty / Department:** Department of Computer Science & Engineering  

---

## Executive Summary

The **NL-to-CLI Agentic Linux Shell** bridges high-level human intent and low-level POSIX execution through specialized multi-agent collaboration. Within this architecture, **Agent 5 (Background Job Manager)** functions as the dedicated **Process & CPU Management Engine**. 

Following architectural alignment with faculty review guidelines, **the Background Agent contains no internal LLM**. Instead, the Parent Shell hosts the primary reasoning model and interactive user REPL, dispatching tasks to Agent 5 via the open **Model Context Protocol (MCP)**. Agent 5 serves as a strictly deterministic, low-overhead execution subsystem that enforces:
1. True POSIX process detachment (`fork()`, `setsid()`, and `nohup` semantics).
2. Asynchronous daemon monitoring and multi-channel system alerts with immediate output previews.
3. Robust runtime inspection and graceful/forced process lifecycle control.
4. Pre-execution security guardrails rejecting destructive shell commands.
5. Standardized MCP Server communication over `stdio` transport.

---

## 1. System Architecture & Role Separation

### 1.1 Hierarchical Agent Architecture
In multi-agent systems, assigning localized LLMs to low-level subsystems introduces prohibitive latency, API overhead, non-deterministic execution, and token exhaustion. Agent 5 solves this through a strict separation of concerns:

```
┌──────────────────────────────────────────────────────────────────┐
│                   PARENT SHELL (Interactive REPL)                │
│            - Hosts Central LLM (OpenAI / Anthropic / Gemini)     │
│            - Translates Natural Language Intent to CLI Ops       │
└─────────────────────────────────┬────────────────────────────────┘
                                  │
                       JSON-RPC over stdio (MCP)
                                  │
┌─────────────────────────────────▼────────────────────────────────┐
│          AGENT 5: BACKGROUND JOB MANAGER (MCP SERVER)            │
│                 (No Internal LLM — Pure OS Engine)               │
│                                                                  │
│  ┌───────────────────────┐             ┌──────────────────────┐  │
│  │ Security Guardrails   │             │ Process Detachment   │  │
│  │ (Regex Sanitization)  │             │ (fork/setsid/nohup)  │  │
│  └───────────┬───────────┘             └──────────┬───────────┘  │
│              │                                    │              │
│  ┌───────────▼───────────┐             ┌──────────▼───────────┐  │
│  │ Inspection & Tracking │             │ Multi-Tier Alerting  │  │
│  │ (get_job_status/stop) │             │ (notify-send/tty/\a) │  │
│  └───────────────────────┘             └──────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

- **Parent Shell**: Responsible for conversation history, contextual intent resolution, and high-level strategy.
- **Agent 5 (Execution Engine)**: Operates as an MCP tool provider, exposing deterministic operating system APIs for background job creation, output redirection, process tree management, and completion alerting.

---

## 2. Core Operating System Principles & Implementation

### 2.1 Process Detachment & Session Isolation
When an operator launches a long-running process (e.g., database compilation, large network downloads, model training), standard shell invocation attaches the child process to the active terminal session. Closing the terminal or dropping SSH connectivity sends a hangup signal (`SIGHUP`) to the process group leader, killing the child.

Agent 5 replicates classic UNIX daemonization:
1. **New Session Group (`setsid`)**:
   - On POSIX platforms, `start_new_session=True` calls `os.setsid()` prior to executing the binary in child context.
   - The child becomes the session leader of a newly created process group, fully detached from the controlling terminal.
2. **Terminal Disconnection & SIGHUP Immunity**:
   - By breaking association with the terminal device (`/dev/tty`), disconnection of the parent shell never triggers `SIGHUP` in the detached child.
3. **Standard Stream Redirection**:
   - `stdin` is bound to `subprocess.DEVNULL` to prevent blocking on user input.
   - `stdout` and `stderr` are combined and streamed into an unbuffered log file on persistent storage (`/tmp` or `.logs/`).
4. **Parent File Descriptor Hygeine**:
   - Parent file descriptors are closed immediately after child fork (`close_fds=True`), ensuring no leaked descriptors or file locks across processes.

### 2.2 Instant Non-Blocking Return Latency
Unlike synchronous subshells that block execution until completion, Agent 5 spawns the process, registers its PID in memory, and returns execution control back to the caller in **under 0.25 seconds** (benchmarked at ~0.08s).

### 2.3 Asynchronous Monitoring & Alert Cascade
To alert operators upon process exit without blocking the agent, Agent 5 spawns an internal daemon thread (`JobMonitor-<PID>`):
1. **Thread Wait**: The daemon thread blocks on `proc.wait()` in kernel space.
2. **Output Preview Extraction**: The last 5 lines of the generated log (capped at 400 characters) are extracted before writing completion headers.
3. **Multi-Tier Alert Cascade**:
   - **Tier 1 (Desktop GUI)**: Dispatches `notify-send` with urgency levels (`normal` for code 0, `critical` for non-zero exit).
   - **Tier 2 (Headless / SSH)**: Direct write to `/dev/tty` with an audible ASCII bell (`\a`) to alert system administrators over remote SSH sessions.
   - **Tier 3 (Fallback)**: Direct emission to `sys.stderr` when interactive ttys are detached.

---

## 3. Security Guardrails & Command Sanitization (Chapter 3.3)

Agent 5 implements pre-execution command sanitization in [security.py](file:///c:/Users/Shobit/Background-Agent/security.py) using compiled regular expressions to reject destructive commands before process creation:

| Vulnerability Type | Blacklist Pattern / Command | Guardrail Behavior |
| :--- | :--- | :--- |
| **Root Filesystem Deletion** | `rm -rf /`, `rm -rf /*`, `rm -rf ~` | Intercepted; raises `SecurityViolationError` |
| **Bypass Flag Protection** | `--no-preserve-root` | Blocked regardless of parameter ordering |
| **Denial-of-Service Fork Bomb** | `:(){ :|:& };:` | Blocked before bash subshell evaluation |
| **Raw Disk Formatting** | `mkfs /dev/sda1`, `fdisk /dev/sdb` | Blocked to protect physical/virtual block storage |
| **Block Device Overwrite** | `dd if=/dev/zero of=/dev/...` | Blocked to prevent partition table corruption |
| **Windows Root Wipes** | `format C:`, `rd /s /q C:\` | Cross-platform protection for Windows hosts |
| **Critical Permission Escalation** | `chmod 777 /`, `chmod -R 777 /etc` | Blocked to preserve privilege boundaries |
| **System Auth Tampering** | `> /etc/shadow`, `>> /etc/passwd` | Blocked to prevent authentication file truncation |

---

## 4. Model Context Protocol (MCP) Server Architecture

Agent 5 is wrapped as an official **MCP Server** via [mcp_server.py](file:///c:/Users/Shobit/Background-Agent/mcp_server.py) using the Python `FastMCP` framework.

### 4.1 Exposed MCP Tools

1. **`run_background_job(command: str, log_file: Optional[str] = None) -> str`**:
   - Detaches command execution, binds I/O to log file, spawns background monitor, returns PID instantly.
2. **`get_job_status(pid: int, tail_lines: int = 5) -> str`**:
   - Inspects PID health, runtime duration, execution state (`RUNNING`, `COMPLETED`, `FAILED`, `STOPPED`), and provides a tail preview of logs.
3. **`stop_background_job(pid: int, force: bool = False) -> str`**:
   - Graceful termination via `SIGTERM` / `taskkill /T`, or forceful process group elimination via `SIGKILL` / `taskkill /F /T`.
4. **`read_job_logs(pid: Optional[int] = None, log_file: Optional[str] = None, lines: int = 20) -> str`**:
   - Reads designated log segment by PID or path without loading massive multi-gigabyte logs into memory.
5. **`list_background_jobs() -> str`**:
   - Returns a structured table of all session jobs, their current state, and start times.

### 4.2 Parent Shell Integration (`stdio` Transport)
The Parent Shell configures Agent 5 in its MCP client configuration:
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

## 5. Verification & Test Suite Results

The comprehensive test suite in [test_background_job_manager.py](file:///c:/Users/Shobit/Background-Agent/test_background_job_manager.py) validates the entire subsystem across 13 test categories:

```
----------------------------------------------------------------------
Ran 13 tests in 4.321s

OK
```

### Verified Test Categories:
1. `test_schema_validity`: Validates adherence to LLM function calling and JSON schema specifications.
2. `test_empty_command_raises`: Guards against empty or whitespace-only inputs.
3. `test_successful_execution_and_output_preview`: Confirms non-blocking detachment (<0.25s), log streaming, and output preview extraction.
4. `test_get_job_status_tool`: Validates runtime duration and status reporting.
5. `test_read_job_logs_tool`: Confirms dual lookup by PID and direct filesystem path.
6. `test_list_background_jobs_tool`: Validates ASCII job table formatting.
7. `test_stop_background_job_tool`: Verifies process group termination.
8. `test_security_guardrail_blocks_destructive_commands`: Validates that destructive patterns trigger `SecurityViolationError`.
9. `test_security_guardrail_allows_benign_commands`: Ensures zero false positives on safe administrative commands.
10. `test_execute_tool_dispatcher`: Validates standard LLM dictionary dispatching.
11. `test_mcp_server_registration`: Verifies all 5 tools are exposed via MCP.
12. `test_mcp_server_tool_call`: Validates end-to-end async tool invocation through MCP protocol.
13. `test_mcp_server_security_guardrail`: Validates that MCP tool errors wrap security violations properly.

---

## 6. Conclusion & Roadmap for Review 3

Agent 5 successfully satisfies all requirements for **Review 2**:
- Complete process detachment and resource hygiene without memory leaks or zombie processes.
- True multi-channel alerting with output previews.
- Full security guardrails against destructive shell instructions.
- Clean Model Context Protocol (MCP) server implementation ready for Parent Shell integration.

**Next Steps for Review 3:**
1. IPC Integration: Connect the live Parent Shell REPL to Agent 5 over stdio MCP.
2. Resource Limits (`cgroups` / `setrlimit`): Enforce memory and CPU quota constraints on spawned background jobs.
3. Multi-Session Persistence: SQLite backing store for job logs across shell restarts.
