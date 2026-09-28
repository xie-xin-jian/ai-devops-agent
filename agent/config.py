import os
import time
import random
import threading
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
DATA_DIR = Path(os.environ.get("DATA_DIR", str(WORKDIR))).expanduser()
if not DATA_DIR.is_absolute():
    DATA_DIR = (WORKDIR / DATA_DIR).resolve()

MODEL_ID = os.environ.get("MODEL_ID", "claude-3-5-sonnet-20240620")
PRIMARY_MODEL = MODEL_ID
FALLBACK_MODEL_ID = os.environ.get("FALLBACK_MODEL_ID", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")
API_KEY = (
    os.environ.get("ANTHROPIC_API_KEY")
    or os.environ.get("API_KEY")
    or os.environ.get("DEEPSEEK_API_KEY")
    or ""
)
API_AUTH_TOKEN = os.environ.get("API_AUTH_TOKEN", "").strip()
API_AUTH_USER = os.environ.get("API_AUTH_USER", "api-user").strip() or "api-user"
API_AUTH_ROLES = [
    role.strip()
    for role in os.environ.get(
        "API_AUTH_ROLES",
        "platform-admin",
    ).split(",")
    if role.strip()
]
ENABLE_UNSAFE_MCP_SHELL = os.environ.get(
    "ENABLE_UNSAFE_MCP_SHELL", ""
).strip().lower() in {"1", "true", "yes", "on"}

SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = DATA_DIR / ".transcripts"
TOOL_RESULTS_DIR = DATA_DIR / ".task_outputs" / "tool-results"
TASKS_DIR = DATA_DIR / ".tasks"
DURABLE_CRON_PATH = DATA_DIR / ".scheduled_tasks.json"
MEMORY_DIR = DATA_DIR / ".memory"
CRON_LOG_DIR = DATA_DIR / ".cron_logs"
AUDIT_DIR = DATA_DIR / ".audit"
SANDBOX_DIR = DATA_DIR / ".sandboxes"
RUNS_DIR = DATA_DIR / ".runs"
BACKGROUND_DIR = DATA_DIR / ".background"
LOG_DIR = DATA_DIR / "logs"

SANDBOX_ENABLED = os.environ.get(
    "SANDBOX_ENABLED", "1"
).strip().lower() in {"1", "true", "yes", "on"}
SANDBOX_IMAGE = os.environ.get(
    "SANDBOX_IMAGE", "python:3.11-slim"
).strip() or "python:3.11-slim"
SANDBOX_TIMEOUT_SECONDS = _env_int(
    "SANDBOX_TIMEOUT_SECONDS",
    120,
    minimum=1,
)
SANDBOX_MEMORY_LIMIT = os.environ.get(
    "SANDBOX_MEMORY_LIMIT", "512m"
).strip() or "512m"
SANDBOX_CPUS = _env_float("SANDBOX_CPUS", 1.0, minimum=0.1)
SANDBOX_PIDS_LIMIT = _env_int(
    "SANDBOX_PIDS_LIMIT",
    128,
    minimum=16,
)
SANDBOX_NETWORK_DISABLED = os.environ.get(
    "SANDBOX_NETWORK_DISABLED", "1"
).strip().lower() in {"1", "true", "yes", "on"}
SANDBOX_USER = os.environ.get(
    "SANDBOX_USER", "65534:65534"
).strip() or "65534:65534"
SANDBOX_ALLOW_LOCAL_DOCKER = os.environ.get(
    "SANDBOX_ALLOW_LOCAL_DOCKER", "0"
).strip().lower() in {"1", "true", "yes", "on"}

try:
    MEMORY_MIN_SCORE = float(os.environ.get("MEMORY_MIN_SCORE", "0.25"))
except ValueError:
    MEMORY_MIN_SCORE = 0.25
try:
    MEMORY_TOP_K = max(1, int(os.environ.get("MEMORY_TOP_K", "5")))
except ValueError:
    MEMORY_TOP_K = 5
MEMORY_SCOPE = os.environ.get("MEMORY_SCOPE", "global").strip() or "global"
try:
    MEMORY_NEAR_DUP_THRESHOLD = float(
        os.environ.get("MEMORY_NEAR_DUP_THRESHOLD", "0.85")
    )
except ValueError:
    MEMORY_NEAR_DUP_THRESHOLD = 0.85
try:
    MEMORY_AUTO_MERGE_THRESHOLD = float(
        os.environ.get("MEMORY_AUTO_MERGE_THRESHOLD", "0.95")
    )
except ValueError:
    MEMORY_AUTO_MERGE_THRESHOLD = 0.95
try:
    MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS = max(
        1,
        int(os.environ.get("MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS", "300")),
    )
except ValueError:
    MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS = 300
try:
    MEMORY_ACCESS_FLUSH_BATCH = max(
        1,
        int(os.environ.get("MEMORY_ACCESS_FLUSH_BATCH", "20")),
    )
except ValueError:
    MEMORY_ACCESS_FLUSH_BATCH = 20

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
MAX_RECOVERY_RETRIES = 2
BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30000
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."

DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]

CLI_ACTIVE = False

# CORS 允许的来源（逗号分隔），生产环境务必配置具体域名
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:8000,"
        "http://127.0.0.1:5173,http://127.0.0.1:8000"
    ).split(",")
    if o.strip()
]
