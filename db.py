import json, os, threading

DATA_FILE = os.getenv("BRIDGE_DB_FILE", "./bridge_state.json")
_lock     = threading.Lock()

def _default():
    return {
        "phone_to_chat": {},
        "engineer_to_set": {},
        "transcripts": {}    
        }

# load state from disk
def _load():
    if not os.path.exists(DATA_FILE):
        return _default()
    try:
        with open(DATA_FILE) as f:
            raw = json.load(f)
            raw["engineer_to_set"] = {
                k: set(v) for k, v in raw.get("engineer_to_set", {}).items()
            }
            raw["transcripts"] = raw.get("transcripts", {})  
            return raw
    except Exception:
        return _default()

state = _load()

# Save state to disk
def save():
    """
    Atomically write `state` to disk, converting sets → lists.
    Works with or without a /data disk mount.
    """
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)

    serialisable = {
        "phone_to_chat": state["phone_to_chat"],      
        "engineer_to_set": {k: list(v)                        
                            for k, v in state["engineer_to_set"].items()},
        "transcripts":     state["transcripts"]
    }

    with _lock, open(DATA_FILE, "w") as f:
        json.dump(serialisable, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

