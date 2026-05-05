import json
from datetime import datetime
from pathlib import Path

# Paths to local JSON "databases"
BASE_DIR = Path(__file__).resolve().parent
FRIDGE_PATH = BASE_DIR / "fridge.json"
RECIPES_PATH = BASE_DIR / "recipes.json"
HISTORY_PATH = BASE_DIR / "history.json"

def load_json(path: Path) -> list:
    """Load a JSON array from file, returning empty list on error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_json(path: Path, data: list) -> None:
    """Atomically-ish write a JSON array to file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_history(action: str, items: list) -> None:
    """Append entries to history.json with timestamp."""
    history = load_json(HISTORY_PATH)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for item in items:
        history.append({
            "aksi": action,
            "nama": item["nama"],
            "qty": item["qty"],
            "satuan": item["satuan"],
            "waktu": now,
        })
    save_json(HISTORY_PATH, history)
