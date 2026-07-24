import os
import time
import random
import threading
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()

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

SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
TASKS_DIR = WORKDIR / ".tasks"
DURABLE_CRON_PATH = WORKDIR / ".scheduled_tasks.json"

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
