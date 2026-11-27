"""Small SQLite repository with organization-scoped queries and atomic event sequencing."""
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import Request


def _database_path() -> str:
    return os.getenv("AATM_DATABASE_PATH", "aatm.sqlite3")


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or _database_path()
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self):
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY, org TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(id), org TEXT NOT NULL, config TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(id), org TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS events(run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL, org TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(run_id, sequence));
            CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), org TEXT NOT NULL, tool_name TEXT NOT NULL DEFAULT '', arguments TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending');
            ''')

    def create_agent(self, org: str, config: dict[str, Any]):
        agent_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO agents(id,org,name) VALUES(?,?,?)", (agent_id, org, config["name"]))
            return self.create_version(agent_id, org, config, db=db)

    def create_version(self, agent_id: str, org: str, config: dict[str, Any], db=None):
        own = db is None
        db = db or self._connect()
        try:
            version_id = str(uuid.uuid4())
            db.execute("INSERT INTO versions(id,agent_id,org,config) VALUES(?,?,?,?)", (version_id, agent_id, org, json.dumps(config)))
            db.commit() if own else None
            return {"id": agent_id, "version_id": version_id, **config}
        finally:
            if own:
                db.close()

    def list_agents(self, org: str):
        with self._connect() as db:
            rows = db.execute("SELECT a.id,a.name,a.created_at,v.id AS version_id FROM agents a LEFT JOIN versions v ON v.agent_id=a.id AND v.org=a.org WHERE a.org=? AND v.rowid=(SELECT vv.rowid FROM versions vv WHERE vv.agent_id=a.id ORDER BY vv.created_at DESC,vv.rowid DESC LIMIT 1) ORDER BY a.created_at", (org,)).fetchall()
            return [dict(row) for row in rows]

    def agent_exists(self, agent_id: str, org: str):
        with self._connect() as db:
            return db.execute("SELECT 1 FROM agents WHERE id=? AND org=?", (agent_id, org)).fetchone() is not None

    def list_versions(self, agent_id: str, org: str):
        with self._connect() as db:
            rows = db.execute("SELECT id,config,created_at FROM versions WHERE agent_id=? AND org=? ORDER BY created_at,rowid", (agent_id, org)).fetchall()
            return [{"id": r["id"], **json.loads(r["config"]), "created_at": r["created_at"]} for r in rows]

    def create_run(self, org: str, agent_id: str):
        run_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO runs(id,agent_id,org) VALUES(?,?,?)", (run_id, agent_id, org))
        return {"id": run_id, "agent_id": agent_id, "status": "running"}

    def run_exists(self, run_id: str, org: str):
        with self._connect() as db:
            return db.execute("SELECT 1 FROM runs WHERE id=? AND org=?", (run_id, org)).fetchone() is not None

    def append_event(self, run_id: str, org: str, kind: str, data: dict[str, Any]):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
            event_id = str(uuid.uuid4())
            db.execute("INSERT INTO events(run_id,sequence,org,kind,data) VALUES(?,?,?,?,?)", (run_id, seq, org, kind, json.dumps(data)))
            db.commit()
        return {"id": event_id, "run_id": run_id, "sequence": seq, "type": kind, "data": data}

    def events_after(self, run_id: str, after: int):
        with self._connect() as db:
            rows = db.execute("SELECT sequence,kind,data,created_at FROM events WHERE run_id=? AND sequence>? ORDER BY sequence", (run_id, after)).fetchall()
            return [{"sequence": r["sequence"], "type": r["kind"], "data": json.loads(r["data"]), "created_at": r["created_at"]} for r in rows]

    def last_sequence(self, run_id: str):
        with self._connect() as db:
            return db.execute("SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?", (run_id,)).fetchone()[0]

    def add_approval(self, run_id: str, org: str, tool_name: str, arguments: dict[str, Any]):
        approval_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO approvals(id,run_id,org,tool_name,arguments) VALUES(?,?,?,?,?)", (approval_id, run_id, org, tool_name, json.dumps(arguments)))
        self.append_event(run_id, org, "tool_approval_requested", {"approval_id": approval_id, "tool_name": tool_name, "arguments": arguments})
        return {"id": approval_id, "tool_name": tool_name, "status": "pending"}

    def resolve_approval(self, run_id: str, approval_id: str, org: str):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute("UPDATE approvals SET status='approved' WHERE id=? AND run_id=? AND org=? AND status='pending'", (approval_id, run_id, org))
            row = db.execute("SELECT id,status FROM approvals WHERE id=? AND run_id=? AND org=?", (approval_id, run_id, org)).fetchone()
            db.commit()
            if cur.rowcount:
                self.append_event(run_id, org, "tool_approval", {"approval_id": approval_id, "status": "approved"})
            return dict(row) if row else None


_store: Store | None = None


def get_store(request: Request) -> Store:
    return request.app.state.store
