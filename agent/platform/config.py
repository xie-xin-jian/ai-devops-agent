import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)


def _env_path_list(name: str) -> tuple[Path, ...]:
    raw = os.environ.get(name, "")
    paths = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        paths.append(Path(value).expanduser().resolve())
    return tuple(paths)


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
ENABLE_MOCK_MCP = os.environ.get(
    "ENABLE_MOCK_MCP", "0"
).strip().lower() in {"1", "true", "yes", "on"}
TARGET_BROWSE_ROOTS = _env_path_list("TARGET_BROWSE_ROOTS")
PERSISTENCE_BACKEND = (
    os.environ.get("PERSISTENCE_BACKEND", "json").strip().lower() or "json"
)
# Read path: "json" (default) keeps every read on the local store. "postgres"
# switches the domains listed in PERSISTENCE_READ_DOMAINS to PostgreSQL.
PERSISTENCE_READ = (
    os.environ.get("PERSISTENCE_READ", "json").strip().lower() or "json"
)
PERSISTENCE_READ_DOMAINS = tuple(
    item.strip().lower()
    for item in os.environ.get("PERSISTENCE_READ_DOMAINS", "").split(",")
    if item.strip()
)
# Shadow reads: after serving a single-record read from PostgreSQL, also read
# the local store and compare. Catches query-level differences (filters,
# ownership, "one side says missing") that a whole-domain check cannot see.
PERSISTENCE_SHADOW = os.environ.get(
    "PERSISTENCE_SHADOW", "0"
).strip().lower() in {"1", "true", "yes", "on"}
# Minimum seconds between drift events for the same domain, so a broken
# domain cannot flood the audit log.
PERSISTENCE_SHADOW_COOLDOWN_SECONDS = max(
    0,
    int(os.environ.get("PERSISTENCE_SHADOW_COOLDOWN_SECONDS", "60")),
)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# Background JSON-vs-PostgreSQL drift check interval. 0 disables the watcher.
PERSISTENCE_CONSISTENCY_INTERVAL_SECONDS = max(
    0,
    int(os.environ.get("PERSISTENCE_CONSISTENCY_INTERVAL_SECONDS", "900")),
)
DB_AUTO_MIGRATE = os.environ.get(
    "DB_AUTO_MIGRATE", "0"
).strip().lower() in {"1", "true", "yes", "on"}
DB_POOL_SIZE = max(1, int(os.environ.get("DB_POOL_SIZE", "5")))
DB_MAX_OVERFLOW = max(0, int(os.environ.get("DB_MAX_OVERFLOW", "10")))
# Without a connect timeout a dead database makes every mirror write wait for
# the OS TCP timeout (measured: 130s on Windows). A few seconds is long enough
# for a healthy server and short enough not to stall the caller.
DB_CONNECT_TIMEOUT = max(1, int(os.environ.get("DB_CONNECT_TIMEOUT", "5")))
# After one failure, stop hammering the database for this many seconds: every
# mirror write during an outage would otherwise pay the timeout again.
DB_FAILURE_COOLDOWN_SECONDS = max(
    0,
    int(os.environ.get("DB_FAILURE_COOLDOWN_SECONDS", "30")),
)

SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = DATA_DIR / ".transcripts"
TOOL_RESULTS_DIR = DATA_DIR / ".task_outputs" / "tool-results"
TASKS_DIR = DATA_DIR / ".tasks"
DURABLE_CRON_PATH = DATA_DIR / ".scheduled_tasks.json"
MEMORY_DIR = DATA_DIR / ".memory"
CRON_LOG_DIR = DATA_DIR / ".cron_logs"
AUDIT_DIR = DATA_DIR / ".audit"
SANDBOX_DIR = DATA_DIR / ".sandboxes"
SESSIONS_DIR = DATA_DIR / ".sessions"
RUNS_DIR = DATA_DIR / ".runs"
BACKGROUND_DIR = DATA_DIR / ".background"
TARGETS_DIR = DATA_DIR / ".targets"
LOG_DIR = DATA_DIR / "logs"

SANDBOX_ENABLED = os.environ.get(
    "SANDBOX_ENABLED", "1"
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
BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50000
CONTEXT_BYTES_BUDGET = 120000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 8000
HISTORY_TOOL_LIMIT = 6000

# 每百万 token 单价（人民币），用于估算每轮/每 run 的调用成本。
# 按 deepseek-chat 公开价格设置；换模型时同步调整。
PRICE_INPUT_PER_M = 2.0
PRICE_OUTPUT_PER_M = 8.0
PRICE_CACHE_HIT_PER_M = 0.5

# CORS 允许的来源（逗号分隔），生产环境务必配置具体域名
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:8000,"
        "http://127.0.0.1:5173,http://127.0.0.1:8000"
    ).split(",")
    if o.strip()
]
