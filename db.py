"""
db.py  – ultra‑light persistence for the WA ↔ Zulip bridge.
Stores the live mapping so redeploys or dyno restarts don’t lose state.

Mount a Render Disk at /data (1 GiB is fine). The JSON file lives there.
"""

import json, os, threading

DATA_FILE = os.getenv("BRIDGE_DB_FILE", "/data/bridge_state.json")
_lock     = threading.Lock()

def _default():
    return {"phone_to_chat": {}, "engineer_to_set": {}}

def _load():
    if not os.path.exists(DATA_FILE):
        return _default()
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return _default()

state = _load()

def save():
    """Write the in‑memory `state` back to disk (atomic enough for one‑dyno MVP)."""
    with _lock, open(DATA_FILE, "w") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
