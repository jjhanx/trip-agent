"""
계획(Plans) API - 사용자별 서버 저장.

- 나중에 가입/로그인을 붙일 수 있도록 user_id 기반 구조
- 현재는 X-User-Id 헤더로 익명 사용자 식별 (연결 코드 활용)
"""

import json
import random
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _get_db_path() -> Path:
    """SQLite DB 경로 (데이터 디렉터리)."""
    base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "plans.db"


def _init_db(db_path: Path) -> None:
    """테이블 초기화."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_plans_user_id ON plans(user_id);
        """)
        conn.commit()
    finally:
        conn.close()


def _get_user_id(request: Request) -> str | None:
    """X-User-Id 헤더 또는 쿼리 파라미터에서 사용자 ID 반환."""
    uid = request.headers.get("X-User-Id")
    if uid:
        return uid.strip()
    return request.query_params.get("user_id", "").strip() or None


def _require_user_id(request: Request) -> tuple[str | None, Response | None]:
    """
    user_id가 있으면 (user_id, None) 반환,
    없으면 (None, 400 Response) 반환.
    """
    uid = _get_user_id(request)
    if not uid or len(uid) < 4:
        return None, JSONResponse(
            {"error": "X-User-Id header or user_id query param required"},
            status_code=400,
        )
    return uid, None


def generate_user_code(length: int = 8) -> str:
    """읽기 쉬운 연결 코드 생성 (혼동 문자 제외)."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(chars) for _ in range(length))


# --- Routes ---


async def register_user(_request: Request) -> Response:
    """
    익명 사용자 등록. 연결 코드 반환.
    나중에 로그인 연동 시 이 코드를 실제 user_id에 매핑.
    """
    code = generate_user_code()
    return JSONResponse({"user_id": code})


async def list_plans(request: Request) -> Response:
    """사용자별 계획 목록 조회."""
    uid, err = _require_user_id(request)
    if err:
        return err
    db_path = _get_db_path()
    _init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT id, name, created_at, updated_at FROM plans WHERE user_id = ? ORDER BY updated_at DESC",
            (uid,),
        ).fetchall()
        plans = [
            {
                "id": r[0],
                "name": r[1],
                "createdAt": r[2],
                "updatedAt": r[3],
            }
            for r in rows
        ]
        return JSONResponse({"plans": plans})
    finally:
        conn.close()


async def get_plan(request: Request) -> Response:
    """단일 계획 조회."""
    uid, err = _require_user_id(request)
    if err:
        return err
    plan_id = request.path_params.get("id")
    if not plan_id:
        return JSONResponse({"error": "Plan id required"}, status_code=400)
    db_path = _get_db_path()
    _init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT id, name, data, created_at, updated_at FROM plans WHERE id = ? AND user_id = ?",
            (plan_id, uid),
        ).fetchone()
        if not row:
            return JSONResponse({"error": "Plan not found"}, status_code=404)
        data = json.loads(row[2])
        return JSONResponse(
            {
                "id": row[0],
                "name": row[1],
                "data": data,
                "createdAt": row[3],
                "updatedAt": row[4],
            }
        )
    finally:
        conn.close()


async def save_plan(request: Request) -> Response:
    """
    계획 저장. POST body: { id?, name, data }.
    id 없으면 새로 생성, 있으면 업데이트.
    """
    uid, err = _require_user_id(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    name = body.get("name")
    data = body.get("data")
    plan_id = body.get("id")
    if not name or data is None:
        return JSONResponse(
            {"error": "name and data required"},
            status_code=400,
        )
    now = datetime.utcnow().isoformat() + "Z"
    db_path = _get_db_path()
    _init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        data_str = json.dumps(data, ensure_ascii=False)
        if plan_id:
            cursor = conn.execute(
                "UPDATE plans SET name=?, data=?, updated_at=? WHERE id=? AND user_id=?",
                (name, data_str, now, plan_id, uid),
            )
            if cursor.rowcount == 0:
                conn.execute(
                    "INSERT INTO plans (id, user_id, name, data, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (plan_id, uid, name, data_str, now, now),
                )
        else:
            plan_id = body.get("id") or str(uuid.uuid4())
            conn.execute(
                "INSERT INTO plans (id, user_id, name, data, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (plan_id, uid, name, data_str, now, now),
            )
        conn.commit()
        return JSONResponse(
            {
                "id": plan_id,
                "name": name,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    finally:
        conn.close()


async def upsert_plan(request: Request) -> Response:
    """
    계획 생성/수정. PUT /api/plans/{id}
    body: { name, data }
    """
    uid, err = _require_user_id(request)
    if err:
        return err
    plan_id = request.path_params.get("id")
    if not plan_id:
        return JSONResponse({"error": "Plan id required"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    name = body.get("name")
    data = body.get("data")
    if not name or data is None:
        return JSONResponse(
            {"error": "name and data required"},
            status_code=400,
        )
    now = datetime.utcnow().isoformat() + "Z"
    db_path = _get_db_path()
    _init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        data_str = json.dumps(data, ensure_ascii=False)
        cursor = conn.execute(
            "UPDATE plans SET name=?, data=?, updated_at=? WHERE id=? AND user_id=?",
            (name, data_str, now, plan_id, uid),
        )
        if cursor.rowcount == 0:
            conn.execute(
                "INSERT INTO plans (id, user_id, name, data, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (plan_id, uid, name, data_str, now, now),
            )
        conn.commit()
        return JSONResponse(
            {
                "id": plan_id,
                "name": name,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    finally:
        conn.close()


async def delete_plan(request: Request) -> Response:
    """계획 삭제."""
    uid, err = _require_user_id(request)
    if err:
        return err
    plan_id = request.path_params.get("id")
    if not plan_id:
        return JSONResponse({"error": "Plan id required"}, status_code=400)
    db_path = _get_db_path()
    _init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM plans WHERE id = ? AND user_id = ?", (plan_id, uid))
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()
