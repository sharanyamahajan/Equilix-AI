# main.py
import os
import hashlib
import json
import sqlite3
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from compliance import ComplianceEngine, generate_tests_via_llm
from ledger import Ledger
from models import ProjectCreate, IngestResponse, TestCaseOut

# CONFIG
DB_PATH = os.environ.get("EQUILIX_DB", "equilix.db")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # optional; used by LLM call if present

# Initialize app, DB, services
app = FastAPI(title="Equilix PoC API")
ledger = Ledger(DB_PATH)
engine = ComplianceEngine()

# --- DB helper (very small) ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        region TEXT,
        regulations TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        text TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS test_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        requirement_id INTEGER,
        title TEXT,
        steps TEXT,
        compliance_justification TEXT,
        risk_score REAL
    )""")
    conn.commit()
    conn.close()

init_db()

# --- Endpoints ---

@app.post("/api/v1/projects", response_model=dict)
def create_project(p: ProjectCreate):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    regs_json = json.dumps(p.regulations)
    cur.execute("INSERT INTO projects (name, region, regulations) VALUES (?, ?, ?)",
                (p.name, p.region, regs_json))
    project_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"project_id": project_id, "name": p.name, "region": p.region, "regulations": p.regulations}

@app.post("/api/v1/projects/{project_id}/ingest", response_model=IngestResponse)
async def ingest_requirements(project_id: int, file: Optional[UploadFile] = File(None), text: Optional[str] = None):
    if not (file or text):
        raise HTTPException(status_code=400, detail="Provide either a file or raw text in 'text' param.")
    content = ""
    if file:
        b = await file.read()
        try:
            content = b.decode("utf-8")
        except:
            content = str(b)
    else:
        content = text

    # Naive split by newline paragraphs as demo "requirements"
    reqs = [r.strip() for r in content.split("\n\n") if r.strip()]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    inserted = []
    for r in reqs:
        cur.execute("INSERT INTO requirements (project_id, text) VALUES (?, ?)", (project_id, r))
        rid = cur.lastrowid
        inserted.append({"requirement_id": rid, "text": r})
    conn.commit()
    conn.close()
    # Write to immutable ledger (demo)
    ledger_entry = {"action": "ingest", "project_id": project_id, "count": len(inserted)}
    ledger.append(json.dumps(ledger_entry))
    return {"project_id": project_id, "ingested": len(inserted), "requirements": inserted}

@app.post("/api/v1/projects/{project_id}/generate", response_model=dict)
def generate_tests(project_id: int, prioritize_top:int = 10):
    """
    Generate tests for all requirements in a project.
    This function:
      - loads requirements
      - calls a mock LLM generator (or real LLM if OPENAI_API_KEY is set)
      - runs compliance engine to attach justifications and risk score
      - stores results and writes ledger entry
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, text FROM requirements WHERE project_id = ?", (project_id,))
    rows = cur.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No requirements found for project")
    generated = []
    for (rid, rtext) in rows:
        tests = generate_tests_via_llm(rtext, OPENAI_API_KEY)  # list of dicts: title, steps
        # run compliance engine to annotate
        annotated = []
        for t in tests:
            justification, risk = engine.assess_test_and_justify(rtext, t)
            # persist
            cur.execute("""INSERT INTO test_cases 
                        (project_id, requirement_id, title, steps, compliance_justification, risk_score)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (project_id, rid, t["title"], json.dumps(t["steps"]), json.dumps(justification), risk))
            tid = cur.lastrowid
            annotated.append({
                "test_id": tid,
                "title": t["title"],
                "steps": t["steps"],
                "justification": justification,
                "risk_score": risk
            })
        generated.append({"requirement_id": rid, "tests": annotated})
    conn.commit()
    conn.close()
    ledger.append(json.dumps({"action":"generate", "project_id": project_id, "generated_count": len(generated)}))
    return {"project_id": project_id, "generated": generated}

@app.get("/api/v1/projects/{project_id}/tests", response_model=List[TestCaseOut])
def get_tests(project_id: int, regulation: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""SELECT id, requirement_id, title, steps, compliance_justification, risk_score 
                   FROM test_cases WHERE project_id = ?""", (project_id,))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "test_id": r[0],
            "requirement_id": r[1],
            "title": r[2],
            "steps": json.loads(r[3]),
            "compliance_justification": json.loads(r[4]),
            "risk_score": r[5]
        })
    return out

@app.post("/api/v1/tests/{test_id}/approve", response_model=dict)
def approve_test(test_id: int, approver: str = "qa"):
    # Very small demonstration: write approval to ledger and return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, project_id FROM test_cases WHERE id = ?", (test_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Test not found")
    project_id = row[1]
    ledger.append(json.dumps({"action":"approve_test", "project_id": project_id, "test_id": test_id, "approver": approver}))
    return {"test_id": test_id, "status": "approved", "approver": approver}

@app.get("/api/v1/audit/{project_id}/ledger", response_model=dict)
def get_ledger(project_id: int, limit: int = 50):
    entries = ledger.read_latest(limit=limit)
    # filter by project_id if present in entry json
    filtered = []
    for e in entries:
        try:
            payload = json.loads(e["payload"])
            if payload.get("project_id") == project_id:
                filtered.append(e)
        except:
            continue
    return {"project_id": project_id, "ledger": filtered}
