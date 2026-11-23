import threading

# Guest chats live only in memory. The limits below keep a public site from
# growing without bound and keep each Gemini request small.
guest_sessions: dict[str, list[dict]] = {}

MAX_GUEST_SESSIONS = 500
MAX_GUEST_MESSAGES = 20

_lock = threading.Lock()


def save_guest_history(session_id: str, history: list[dict]) -> None:
    """Store a guest conversation, keeping only the newest sessions and messages."""
    recent = history[-MAX_GUEST_MESSAGES:]
    if recent and recent[0]["role"] != "user":
        recent = recent[1:]  # a conversation sent to the AI must start with the user

    with _lock:
        guest_sessions.pop(session_id, None)  # re-insert so this one counts as newest
        guest_sessions[session_id] = recent
        while len(guest_sessions) > MAX_GUEST_SESSIONS:
            guest_sessions.pop(next(iter(guest_sessions)))
