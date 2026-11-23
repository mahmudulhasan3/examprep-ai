import hashlib
import logging
import math
import threading
import time
from collections import deque

from fastapi import HTTPException

from app.core.env_utils import env_flag

logger = logging.getLogger(__name__)

# Counts live in this process only. That is fine while the API runs as one worker;
# with several workers each one would count on its own.
_hits: dict[tuple[str, str], deque[float]] = {}
_lock = threading.Lock()

MAX_TRACKED_KEYS = 50_000
LONGEST_WINDOW_SECONDS = 3600


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def _purge(now: float) -> None:
    """Forget keys that have been quiet for longer than any window we use."""
    stale = [
        key
        for key, hits in _hits.items()
        if not hits or now - hits[-1] > LONGEST_WINDOW_SECONDS
    ]
    for key in stale:
        del _hits[key]


def check_rate_limit(
    bucket: str, key: str, max_requests: int, window_seconds: int
) -> None:
    """Allow at most max_requests per window for this (bucket, key), else HTTP 429.

    The key says who is counted: an email address, a user id, or a fixed word such as
    "all" to count everybody together.
    """
    if not env_flag("RATE_LIMIT_ENABLED", True):
        return

    now = time.monotonic()
    with _lock:
        if len(_hits) > MAX_TRACKED_KEYS:
            _purge(now)
        hits = _hits.setdefault((bucket, key), deque())
        while hits and now - hits[0] >= window_seconds:
            hits.popleft()
        if len(hits) >= max_requests:
            wait = max(1, math.ceil(window_seconds - (now - hits[0])))
        else:
            hits.append(now)
            wait = 0

    if wait:
        # log a short fingerprint instead of the key, which may be an email address
        fingerprint = hashlib.sha256(key.encode()).hexdigest()[:8]
        logger.warning("Rate limit hit: bucket=%s key=%s", bucket, fingerprint)
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Please try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )
