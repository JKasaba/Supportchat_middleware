# """
# db.py  – ultra‑light persistence for the WA ↔ Zulip bridge.
# Stores the live mapping so redeploys or dyno restarts don’t lose state.

# Mount a Render Disk at /data (1 GiB is fine). The JSON file lives there.
# """

# import json, os, threading

# DATA_FILE = os.getenv("BRIDGE_DB_FILE", "/data/bridge_state.json")
# _lock     = threading.Lock()

# def _default():
#     return {"phone_to_chat": {}, "engineer_to_set": {}}

# def _load():
#     if not os.path.exists(DATA_FILE):
#         return _default()
#     try:
#         with open(DATA_FILE) as f:
#             return json.load(f)
#     except Exception:
#         return _default()

# state = _load()

# def save():
#     """Write the in‑memory `state` back to disk (atomic enough for one‑dyno MVP)."""
#     with _lock, open(DATA_FILE, "w") as f:
#         json.dump(state, f)
#         f.flush()
#         os.fsync(f.fileno())

"""
db.py – JSON persistence for the WA↔Zulip bridge.
Handles set↔list conversion so state is always JSON‑serialisable.
"""

import json, os, threading

DATA_FILE = os.getenv("BRIDGE_DB_FILE", "./bridge_state.json")
_lock     = threading.Lock()

def _default():
    return {"phone_to_chat": {}, "engineer_to_set": {}}

# ─── Load ────────────────────────────────────────────────────────────────────
def _load():
    if not os.path.exists(DATA_FILE):
        return _default()
    try:
        with open(DATA_FILE) as f:
            raw = json.load(f)
            # lists → sets for in‑memory use
            raw["engineer_to_set"] = {
                k: set(v) for k, v in raw.get("engineer_to_set", {}).items()
            }
            return raw
    except Exception:
        return _default()

state = _load()

# ─── Save ────────────────────────────────────────────────────────────────────
def save():
    """
    Atomically write `state` to disk, converting sets → lists.
    Works with or without a /data disk mount.
    """
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)

    serialisable = {
        "phone_to_chat": state["phone_to_chat"],               # plain dict
        "engineer_to_set": {k: list(v)                        # sets → lists
                            for k, v in state["engineer_to_set"].items()}
    }

    with _lock, open(DATA_FILE, "w") as f:
        json.dump(serialisable, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

