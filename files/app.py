"""Case Management Simulator - Flask + SQLite backend.

Serves the front end (index.html) and a REST API.
Run:  pip install -r requirements.txt  &&  python app.py
Open: http://127.0.0.1:5000
"""
import os
import sqlite3
import time

from flask import Flask, g, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cases.db")
SLA_HOURS = {"Critical": 4, "High": 8, "Medium": 24, "Low": 72}
STATUSES = ["New", "Categorized", "Assigned", "In Progress", "Escalated", "Resolved", "Closed"]

app = Flask(__name__, static_folder=None)

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, name TEXT, type TEXT, owner TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS software(id TEXT PRIMARY KEY, name TEXT, version TEXT, seats TEXT, renewal TEXT);
CREATE TABLE IF NOT EXISTS cases(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, customer TEXT, type TEXT, category TEXT,
  priority TEXT DEFAULT 'Medium', asset_id TEXT REFERENCES assets(id), software_id TEXT REFERENCES software(id),
  status TEXT DEFAULT 'New', owner TEXT, created INTEGER, resolution TEXT, kb_saved INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT REFERENCES cases(id), text TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS kb(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, category TEXT, fix TEXT, source_case TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.executescript(SCHEMA)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def case_json(row, notes):
    return {
        "id": row["id"], "title": row["title"], "customer": row["customer"], "type": row["type"],
        "cat": row["category"] or "", "pri": row["priority"], "asset": row["asset_id"] or "",
        "sw": row["software_id"] or "", "status": row["status"], "owner": row["owner"] or "",
        "created": row["created"], "res": row["resolution"] or "", "kb": bool(row["kb_saved"]),
        "notes": [{"t": n["text"], "ts": n["ts"]} for n in notes],
    }


def all_cases(where="", args=()):
    conn = db()
    out = []
    for r in conn.execute("SELECT * FROM cases " + where + " ORDER BY created DESC", args):
        notes = conn.execute("SELECT * FROM notes WHERE case_id=? ORDER BY ts", (r["id"],)).fetchall()
        out.append(case_json(r, notes))
    return out


def next_id():
    conn = db()
    row = conn.execute("SELECT value FROM meta WHERE key='nid'").fetchone()
    n = int(row["value"]) if row else 1001
    conn.execute("INSERT OR REPLACE INTO meta VALUES('nid', ?)", (str(n + 1),))
    return "CS-%d" % n


# ---------- front end ----------
@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


# ---------- whole-state sync used by the UI ----------
@app.get("/api/state")
def get_state():
    conn = db()
    nid = conn.execute("SELECT value FROM meta WHERE key='nid'").fetchone()
    return jsonify({
        "cases": all_cases(),
        "assets": [dict(r) for r in conn.execute("SELECT * FROM assets")],
        "sw": [dict(r) for r in conn.execute("SELECT * FROM software")],
        "kb": [{"title": r["title"], "cat": r["category"], "fix": r["fix"], "from": r["source_case"]}
               for r in conn.execute("SELECT * FROM kb ORDER BY id DESC")],
        "nid": int(nid["value"]) if nid else 1001,
    })


@app.put("/api/state")
def put_state():
    s = request.get_json(force=True)
    conn = db()
    with conn:
        for t in ("notes", "cases", "assets", "software", "kb"):
            conn.execute("DELETE FROM " + t)
        for a in s.get("assets", []):
            conn.execute("INSERT INTO assets VALUES(?,?,?,?,?)", (a["id"], a["name"], a["type"], a["owner"], a["status"]))
        for w in s.get("sw", []):
            conn.execute("INSERT INTO software VALUES(?,?,?,?,?)", (w["id"], w["name"], w["version"], w["seats"], w["renewal"]))
        for c in s.get("cases", []):
            conn.execute("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                c["id"], c["title"], c["customer"], c["type"], c["cat"], c["pri"], c["asset"] or None,
                c["sw"] or None, c["status"], c["owner"], int(c["created"]), c["res"], int(bool(c.get("kb")))))
            for n in c.get("notes", []):
                conn.execute("INSERT INTO notes(case_id,text,ts) VALUES(?,?,?)", (c["id"], n["t"], int(n["ts"])))
        for k in reversed(s.get("kb", [])):
            conn.execute("INSERT INTO kb(title,category,fix,source_case) VALUES(?,?,?,?)", (k["title"], k["cat"], k["fix"], k["from"]))
        conn.execute("INSERT OR REPLACE INTO meta VALUES('nid', ?)", (str(s.get("nid", 1001)),))
    return jsonify(ok=True)


# ---------- REST API ----------
@app.get("/api/cases")
def list_cases():
    clauses, args = [], []
    for param, col in (("status", "status"), ("priority", "priority"), ("owner", "owner")):
        if request.args.get(param):
            clauses.append(col + "=?")
            args.append(request.args[param])
    return jsonify(all_cases("WHERE " + " AND ".join(clauses) if clauses else "", args))


@app.get("/api/cases/<cid>")
def get_case(cid):
    found = all_cases("WHERE id=?", (cid,))
    return (jsonify(found[0]), 200) if found else (jsonify(error="Case not found"), 404)


@app.post("/api/cases")
def create_case():
    d = request.get_json(force=True)
    if not d.get("title"):
        return jsonify(error="title is required"), 400
    conn = db()
    with conn:
        cid = next_id()
        conn.execute(
            "INSERT INTO cases(id,title,customer,type,priority,asset_id,software_id,status,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (cid, d["title"], d.get("customer", "Unknown"), d.get("type", "Incident"), d.get("priority", "Medium"),
             d.get("asset") or None, d.get("sw") or None, "New", int(time.time() * 1000)))
    return jsonify(all_cases("WHERE id=?", (cid,))[0]), 201


@app.patch("/api/cases/<cid>")
def update_case(cid):
    d = request.get_json(force=True)
    fields = {"status": "status", "owner": "owner", "cat": "category", "pri": "priority", "res": "resolution"}
    if d.get("status") and d["status"] not in STATUSES:
        return jsonify(error="invalid status"), 400
    conn = db()
    with conn:
        for key, col in fields.items():
            if key in d:
                conn.execute("UPDATE cases SET %s=? WHERE id=?" % col, (d[key], cid))
    found = all_cases("WHERE id=?", (cid,))
    return (jsonify(found[0]), 200) if found else (jsonify(error="Case not found"), 404)


@app.post("/api/cases/<cid>/notes")
def add_note(cid):
    text = (request.get_json(force=True).get("text") or "").strip()
    if not text:
        return jsonify(error="text is required"), 400
    conn = db()
    with conn:
        conn.execute("INSERT INTO notes(case_id,text,ts) VALUES(?,?,?)", (cid, text, int(time.time() * 1000)))
    return jsonify(ok=True), 201


@app.get("/api/stats")
def stats():
    cases = all_cases()
    now = time.time() * 1000
    open_cases = [c for c in cases if c["status"] not in ("Resolved", "Closed")]
    return jsonify({
        "total": len(cases),
        "open": len(open_cases),
        "escalated": sum(c["status"] == "Escalated" for c in cases),
        "unassigned": sum(not c["owner"] for c in open_cases),
        "sla_breached": sum(now > c["created"] + SLA_HOURS[c["pri"]] * 3600000 for c in open_cases),
        "by_status": {s: sum(c["status"] == s for c in cases) for s in STATUSES},
    })


if __name__ == "__main__":
    app.run(debug=True)
