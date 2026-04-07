from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

# Ensure data folders exist
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "runs.db"
JSON_OUT_DIR = DATA_DIR / "runs"
JSON_OUT_DIR.mkdir(parents=True, exist_ok=True)


def save_run(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# --- persistence helpers used by the simulation APIs ---

def init_db() -> None:
    """Create SQLite DB and runs table if missing."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            post_id TEXT,
            created_at TEXT,
            config_json TEXT,
            result_json TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_run_db(run_id: str, post_id: str, config: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Insert or replace a run record."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO runs (run_id, post_id, created_at, config_json, result_json) VALUES (?, ?, ?, ?, ?)",
        (run_id, post_id, datetime.utcnow().isoformat(), json.dumps(config), json.dumps(result)),
    )
    conn.commit()
    conn.close()


def load_run_db(run_id: str) -> Optional[Dict[str, Any]]:
    """Load a run's result_json from the DB and return it as a dict (or None)."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT result_json FROM runs WHERE run_id = ?", (run_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row[0])


def save_run_json(run_id: str, payload: Dict[str, Any]) -> None:
    """Persist run payload to a JSON file under data/runs/"""
    out = JSON_OUT_DIR / f"{run_id}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)