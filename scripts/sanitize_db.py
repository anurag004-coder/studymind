"""Sanitizes corrupted legacy questions in SQLite database."""

import sqlite3
from pathlib import Path

db_path = Path("studymind.db")
if db_path.exists():
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT id, stem, options_json, type FROM questions WHERE status = 'active'")
    rows = cur.fetchall()
    retired_count = 0
    for qid, stem, opts_json, q_type in rows:
        stem_str = (stem or "").strip()
        should_retire = False
        if len(stem_str) < 25 or stem_str.endswith((":", ",")):
            should_retire = True
        elif "regarding include" in stem_str or "\n\n" in stem_str or "Threats," in stem_str or "Secure." in stem_str:
            should_retire = True
        elif q_type == "mcq" and opts_json:
            import json
            try:
                opts = json.loads(opts_json)
                if not isinstance(opts, list) or len(opts) != 4 or any(len(str(o).strip()) < 5 for o in opts):
                    should_retire = True
            except Exception:
                should_retire = True

        if should_retire:
            cur.execute("UPDATE questions SET status = 'retired' WHERE id = ?", (qid,))
            retired_count += 1

    con.commit()
    cur.execute("SELECT count(*) FROM questions WHERE status = 'active'")
    active_left = cur.fetchone()[0]
    con.close()
    print(f"Retired {retired_count} corrupted legacy questions. Remaining active: {active_left}")
else:
    print("Database not found.")
