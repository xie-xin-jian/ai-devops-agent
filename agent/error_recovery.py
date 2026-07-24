import time, random
from agent.config import (
    MAX_RETRIES, MAX_CONSECUTIVE_529, BASE_DELAY_MS,
    PRIMARY_MODEL, FALLBACK_MODEL_ID, DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS
)

class RecoveryState:
    def __init__(self):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        self.current_model = PRIMARY_MODEL
        self.current_max_tokens = DEFAULT_MAX_TOKENS

def retry_delay(attempt: int) -> float:
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    return base + random.uniform(0, base * 0.25)

def with_retry(fn, state: RecoveryState):
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            name = type(e).__name__.lower()
            msg = str(e).lower()
            if "ratelimit" in name or "429" in msg:
                if attempt < MAX_RETRIES - 1:
                    delay = retry_delay(attempt)
                    time.sleep(delay)
                    continue
            if "overloaded" in name or "529" in msg or "overloaded" in msg:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529 and FALLBACK_MODEL_ID:
                    state.current_model = FALLBACK_MODEL_ID
                    state.consecutive_529 = 0
                if attempt < MAX_RETRIES - 1:
                    delay = retry_delay(attempt)
                    time.sleep(delay)
                    continue
            raise
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")

def is_prompt_too_long_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (("prompt" in msg and "long" in msg)
            or "context_length_exceeded" in msg
            or "max_context_window" in msg)

def escalate_tokens(state: RecoveryState) -> bool:
    if state.current_max_tokens < ESCALATED_MAX_TOKENS:
        state.current_max_tokens = ESCALATED_MAX_TOKENS
        state.has_escalated = True
        return True
    return False
