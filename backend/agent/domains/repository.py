"""PostgreSQL persistence for independent interest/expertise selections."""
from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from psycopg.types.json import Jsonb
from db.database import connect
from .catalog import BY_ID, CATALOG_VERSION

def _now(): return datetime.now(timezone.utc)

def _avatar(db, user_id: str) -> str:
    now = _now()
    db.execute("INSERT INTO users(id,created_at,updated_at) VALUES (%s,%s,%s) ON CONFLICT(id) DO UPDATE SET updated_at=EXCLUDED.updated_at", (user_id,now,now))
    row = db.execute("SELECT id FROM avatars WHERE user_id=%s AND deleted_at IS NULL ORDER BY created_at,id LIMIT 1", (user_id,)).fetchone()
    if row: return row["id"]
    aid = "avatar_" + uuid4().hex
    db.execute("INSERT INTO avatars(id,user_id,status,created_at,updated_at) VALUES (%s,%s,'draft',%s,%s)", (aid,user_id,now,now))
    return aid

def get_selections(user_id: str) -> dict:
    with connect() as db:
        row = db.execute("SELECT id FROM avatars WHERE user_id=%s AND deleted_at IS NULL ORDER BY created_at,id LIMIT 1", (user_id,)).fetchone()
        if not row: return {"catalog_version": CATALOG_VERSION, "revision": 0, "interests": [], "expertise": []}
        rows = db.execute("SELECT domain_id,selection_type,interest_level,proficiency,notes,revision,created_at,updated_at FROM avatar_domain_selections WHERE avatar_id=%s AND deleted_at IS NULL ORDER BY domain_id,selection_type", (row["id"],)).fetchall()
    result={"catalog_version": CATALOG_VERSION,"revision": max((r["revision"] for r in rows), default=0),"interests":[],"expertise":[]}
    for r in rows:
        item={"domain_id":r["domain_id"],"interest_level":r["interest_level"],"proficiency":r["proficiency"],"notes":r["notes"],"created_at":r["created_at"].isoformat(),"updated_at":r["updated_at"].isoformat()}
        result["interests" if r["selection_type"]=="interest" else "expertise"].append(item)
    return result

def replace_selections(user_id: str, payload: dict) -> dict:
    revision=int(payload.get("expected_revision",0)); entries=[]; seen=set()
    for key in ("interests","expertise"):
        kind = "interest" if key == "interests" else "expertise"
        for item in payload.get(key,[]):
            did=item.get("domain_id")
            if did not in BY_ID or BY_ID[did].level == "root": raise ValueError(f"invalid selectable domain: {did}")
            if (kind, did) in seen: raise ValueError(f"duplicate selection: {did}")
            seen.add((kind, did))
            level=item.get("interest_level",1)
            if not isinstance(level,int) or not 0 <= level <= 3: raise ValueError("interest_level must be 0..3")
            proficiency=item.get("proficiency") if kind=="expertise" else None
            if proficiency not in (None,"novice","familiar","working","advanced","unknown"): raise ValueError("invalid proficiency")
            entries.append((kind,did,level,proficiency,item.get("notes")))
    with connect() as db:
        aid=_avatar(db,user_id)
        current=db.execute("SELECT COALESCE(MAX(revision),0) AS revision FROM avatar_domain_selections WHERE avatar_id=%s AND deleted_at IS NULL",(aid,)).fetchone()["revision"]
        if current != revision: raise RuntimeError("selection revision conflict")
        next_rev=current+1
        db.execute("UPDATE avatar_domain_selections SET deleted_at=%s WHERE avatar_id=%s AND deleted_at IS NULL",(_now(),aid))
        for kind,did,level,prof,notes in entries:
            db.execute("INSERT INTO avatar_domain_selections(id,avatar_id,domain_id,selection_type,interest_level,proficiency,notes,revision,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", ("sel_"+uuid4().hex,aid,did,kind,level,prof,notes,next_rev,_now(),_now()))
    return get_selections(user_id)
