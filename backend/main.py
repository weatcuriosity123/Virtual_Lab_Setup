import asyncio
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import docker
import classrooms
from docker.errors import DockerException, NotFound
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="Linux Lab API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    root_path="/api",
)

CLASS_ACCESS_CODE = os.getenv("CLASS_ACCESS_CODE", "")
ALLOW_LEGACY_CLASS_CODE = os.getenv("ALLOW_LEGACY_CLASS_CODE", "true").lower() == "true"
PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL", "https://vm.curiosity4u.in"
).rstrip("/")
SESSION_MINUTES = int(os.getenv("SESSION_MINUTES", "60"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "4"))
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "linux-lab-net")
STUDENT_IMAGE = os.getenv("STUDENT_IMAGE", "linux-lab:1.0")
SESSION_DB = os.getenv("SESSION_DB", "/data/sessions.db")
CONFIG_DIR = Path(os.getenv(
    "SESSION_CONFIG_DIR", "/etc/nginx/sessions"
))
PROXY_CONTAINER = os.getenv("PROXY_CONTAINER", "linux-lab-proxy")

docker_client = docker.from_env()
creation_lock = asyncio.Lock()


class CreateSession(BaseModel):
    access_code: str = Field(min_length=1, max_length=200)
    request_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


def connect_db():
    conn = sqlite3.connect(SESSION_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    Path(SESSION_DB).parent.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    with closing(connect_db()) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                container_name TEXT NOT NULL,
                password TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """)
        columns = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
        if "request_id" not in columns:
            db.execute("ALTER TABLE sessions ADD COLUMN request_id TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS session_request_id ON sessions(request_id)")
        for name, kind in {
            "college_id": "TEXT", "classroom_id": "TEXT", "template_id": "TEXT",
            "session_minutes": "INTEGER", "college_name": "TEXT",
            "classroom_name": "TEXT", "template_name": "TEXT",
        }.items():
            if name not in columns:
                db.execute(f"ALTER TABLE sessions ADD COLUMN {name} {kind}")
        db.commit()
        classrooms.init_catalog(db)


def admission_context(code):
    with closing(connect_db()) as db:
        context = classrooms.resolve_classroom(db, code)
    if context:
        context["classroom_id"] = context["id"]
        context["classroom_name"] = context["name"]
        return context
    if (ALLOW_LEGACY_CLASS_CODE and CLASS_ACCESS_CODE and
            hmac.compare_digest(code.encode(), CLASS_ACCESS_CODE.encode())):
        # A configured classroom may not be bypassed by reusing its code as legacy.
        with closing(connect_db()) as db:
            if any(classrooms.matches(code, row) for row in db.execute("SELECT * FROM classrooms")):
                raise HTTPException(401, "Invalid or unavailable classroom code")
        return dict(classroom_id=None, college_id=None, template_id=None,
                    college_name=None, classroom_name="Linux Practice Lab", template_name="Linux desktop",
                    image=STUDENT_IMAGE, memory_mb=768, cpu_millis=750, shm_mb=256,
                    home_mb=300, pids=256, session_minutes=SESSION_MINUTES, max_sessions=MAX_SESSIONS)
    raise HTTPException(401, "Invalid or unavailable classroom code")


def reload_proxy():
    proxy = docker_client.containers.get(PROXY_CONTAINER)
    result = proxy.exec_run(["nginx", "-s", "reload"])
    if result.exit_code != 0:
        raise RuntimeError(
            f"Nginx reload failed: {result.output!r}"
        )




def write_route(token: str, container_name: str):
    config = f"""
location ^~ /s/{token}/ {{
    resolver 127.0.0.11 valid=10s ipv6=off;
    set $student_upstream http://{container_name}:3000;

    rewrite ^/s/{token}/(.*)$ /$1 break;
    proxy_pass $student_upstream;

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
}}
"""
    (CONFIG_DIR / f"{token}.conf").write_text(config)



def delete_container(container_name: str):
    try:
        container = docker_client.containers.get(container_name)
        container.stop(timeout=5)
        container.remove(force=True, v=True)
    except NotFound:
        pass


def delete_session(token: str):
    with closing(connect_db()) as db:
        row = db.execute(
            "SELECT container_name FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()

        if row is None:
            return

        delete_container(row["container_name"])
        (CONFIG_DIR / f"{token}.conf").unlink(missing_ok=True)

        db.execute(
            "UPDATE sessions SET status = 'expired' WHERE token = ?",
            (token,),
        )
        db.commit()

    reload_proxy()


def cleanup_expired():
    now = datetime.now(timezone.utc).isoformat()

    with closing(connect_db()) as db:
        rows = db.execute("""
            SELECT token FROM sessions
            WHERE status IN ('active', 'starting') AND expires_at <= ?
        """, (now,)).fetchall()

    for row in rows:
        try:
            delete_session(row["token"])
        except Exception as exc:
            print(f"Cleanup failed for session: {exc}", flush=True)


async def expiry_worker():
    while True:
        await asyncio.sleep(15)
        try:
            cleanup_expired()
        except Exception as exc:
            print(f"Expiry worker error: {exc}", flush=True)


@app.on_event("startup")
async def startup():
    init_db()
    cleanup_expired()
    app.state.expiry_task = asyncio.create_task(expiry_worker())


@app.on_event("shutdown")
async def shutdown():
    task = getattr(app.state, "expiry_task", None)
    if task:
        task.cancel()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sessions")
def session_capacity():
    now = datetime.now(timezone.utc).isoformat()

    with closing(connect_db()) as db:
        count = db.execute("""
            SELECT COUNT(*) FROM sessions
            WHERE status IN ('active', 'starting') AND expires_at > ?
        """, (now,)).fetchone()[0]

    return {
        "active_sessions": count,
        "capacity": MAX_SESSIONS,
        "available_slots": max(0, MAX_SESSIONS - count),
        "session_minutes": SESSION_MINUTES,
    }


@app.post("/sessions")
async def create_session(request: CreateSession):
    async with creation_lock:
        context = await asyncio.to_thread(admission_context, request.access_code)
        cleanup_expired()
        now = datetime.now(timezone.utc)
        if request.request_id:
            with closing(connect_db()) as db:
                existing = db.execute("SELECT * FROM sessions WHERE request_id = ?", (request.request_id,)).fetchone()
            if existing:
                if existing["classroom_id"] != context["classroom_id"]:
                    raise HTTPException(409, "Start request belongs to another classroom. Retry with a new request.")
                if existing["status"] not in ("starting", "active"):
                    raise HTTPException(409, "This start attempt has ended. Start a new lab.")
                return session_payload(existing)
        token = secrets.token_hex(16)
        container_name = f"linux-lab-session-{token}"
        password = secrets.token_urlsafe(18)
        expires = now + timedelta(minutes=5)

        with closing(connect_db()) as db:
            count = db.execute("""
                SELECT COUNT(*) FROM sessions
                WHERE status IN ('active', 'starting') AND expires_at > ?
            """, (now.isoformat(),)).fetchone()[0]

        if count >= MAX_SESSIONS:
            raise HTTPException(
                status_code=429,
                detail="All student desktops are in use. Try again later.",
            )

        with closing(connect_db()) as db:
            occupied = db.execute("""SELECT COUNT(*) FROM sessions
                WHERE classroom_id IS ? AND status IN ('starting','active') AND expires_at > ?""",
                (context["classroom_id"], now.isoformat())).fetchone()[0]
        if occupied >= context["max_sessions"]:
            raise HTTPException(429, "All desktops for this classroom are in use. Try again later.")

        try:
            docker_client.images.get(context["image"])

            docker_client.containers.run(
                image=context["image"],
                name=container_name,
                detach=True,
                network=DOCKER_NETWORK,
                shm_size=f"{context['shm_mb']}m",
                tmpfs={
                    "/config": f"rw,size={context['home_mb']}m,mode=1777",
                },
                mem_limit=f"{context['memory_mb']}m",
                nano_cpus=context["cpu_millis"] * 1_000_000,
                pids_limit=context["pids"],
                security_opt=["no-new-privileges:true"],
                environment={
                    "TZ": "Asia/Kolkata",
                    "PUID": "1000",
                    "PGID": "1000",
                    "CUSTOM_USER": "student",
                    "PASSWORD": password,
                    "START_DOCKER": "false",
                },
                labels={
                    "linux-lab.managed": "true",
                    "linux-lab.session": token,
                    "linux-lab.college": context["college_id"] or "legacy",
                    "linux-lab.classroom": context["classroom_id"] or "legacy",
                    "linux-lab.template": context["template_id"] or "legacy",
                },
            )

            write_route(token, container_name)
            reload_proxy()

            with closing(connect_db()) as db:
                db.execute("""
                    INSERT INTO sessions
                    (token, container_name, password,
                     created_at, expires_at, status, request_id, college_id, classroom_id,
                     template_id, session_minutes, college_name, classroom_name, template_name)
                    VALUES (?, ?, ?, ?, ?, 'starting', ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    token,
                    container_name,
                    password,
                    now.isoformat(),
                    expires.isoformat(),
                    request.request_id, context["college_id"], context["classroom_id"],
                    context["template_id"], context["session_minutes"], context["college_name"],
                    context["classroom_name"], context["template_name"],
                ))
                db.commit()

        except Exception as exc:
            (CONFIG_DIR / f"{token}.conf").unlink(missing_ok=True)
            try:
                reload_proxy()
            except Exception:
                pass
            try:
                delete_container(container_name)
            except Exception:
                pass

            print(f"Session creation failed: {exc}", flush=True)
            raise HTTPException(
                status_code=500,
                detail="Could not create a desktop. Check server logs.",
            )

        with closing(connect_db()) as db:
            return session_payload(db.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone())


@app.delete("/sessions/{token}")
async def end_session(token: str, access_code: str):
    context = await asyncio.to_thread(admission_context, access_code)

    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(status_code=404, detail="Session not found")

    with closing(connect_db()) as db:
        row = db.execute(
            "SELECT status, classroom_id FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()

    if row is None or row["classroom_id"] != context["classroom_id"] or row["status"] not in ("active", "starting"):
        raise HTTPException(status_code=404, detail="Active session not found")

    async with creation_lock:
        delete_session(token)

    return {"status": "deleted", "session_id": token}


# Student lab controls
from fastapi import Header


def authorize_lab_session(token: str, password: str):
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(status_code=404, detail="Session not found")

    with closing(connect_db()) as db:
        row = db.execute(
            "SELECT * FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()

    if row is None or not hmac.compare_digest(
        password.encode("utf-8"),
        row["password"].encode("utf-8"),
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid session credentials",
        )

    return row


@app.get("/lab/{token}")
async def lab_status(
    token: str,
    x_session_password: str = Header(...),
):
    async with creation_lock:
        row = authorize_lab_session(token, x_session_password)
        now = datetime.now(timezone.utc)
        expires = datetime.fromisoformat(row["expires_at"])

        if row["status"] in ("active", "starting") and now >= expires:
            try:
                delete_session(token)
            except Exception:
                raise HTTPException(
                    status_code=503,
                    detail="Session cleanup pending. Retry shortly.",
                )
            row = authorize_lab_session(token, x_session_password)

        remaining = max(0, int((expires - now).total_seconds()))

        return {
            "session_id": token,
            "status": row["status"],
            "expires_at": row["expires_at"],
            "server_time": now.isoformat(),
            "college_name": row["college_name"], "classroom_name": row["classroom_name"],
            "template_name": row["template_name"],
            "remaining_seconds": (
                remaining if row["status"] == "active" else 0
            ),
        }


@app.post("/lab/{token}/terminate")
async def terminate_lab(
    token: str,
    x_session_password: str = Header(...),
):
    async with creation_lock:
        row = authorize_lab_session(token, x_session_password)

        if row["status"] not in ("active", "starting"):
            return {"status": row["status"], "session_id": token}

        expired = (
            datetime.now(timezone.utc)
            >= datetime.fromisoformat(row["expires_at"])
        )

        try:
            delete_session(token)
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="Could not finish cleanup. Retry shortly.",
            )

        status = "expired" if expired else "terminated"

        with closing(connect_db()) as db:
            db.execute(
                "UPDATE sessions SET status = ? WHERE token = ?",
                (status, token),
            )
            db.commit()

        return {"status": status, "session_id": token}


from typing import Literal


class LabFeedback(BaseModel):
    rating: int = Field(ge=1, le=5)
    worked: Literal["yes", "partially", "no"]
    comments: str = Field(default="", max_length=2000)


@app.post("/lab/{token}/feedback")
async def submit_lab_feedback(
    token: str,
    feedback: LabFeedback,
    x_session_password: str = Header(...),
):
    row = authorize_lab_session(token, x_session_password)

    if row["status"] in ("active", "starting"):
        raise HTTPException(
            status_code=409,
            detail="End your session before submitting feedback.",
        )

    with closing(connect_db()) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                session_token TEXT PRIMARY KEY,
                rating INTEGER NOT NULL,
                worked TEXT NOT NULL,
                comments TEXT NOT NULL,
                submitted_at TEXT NOT NULL
            )
        """)

        db.execute("""
            INSERT INTO feedback
                (session_token, rating, worked, comments, submitted_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_token) DO UPDATE SET
                rating = excluded.rating,
                worked = excluded.worked,
                comments = excluded.comments,
                submitted_at = excluded.submitted_at
        """, (
            token,
            feedback.rating,
            feedback.worked,
            feedback.comments.strip(),
            datetime.now(timezone.utc).isoformat(),
        ))
        db.commit()

    return {"status": "saved"}


# LAB_IDLE_V1
import time

IDLE_WARNING_SECONDS = 180
IDLE_END_SECONDS = 240

INSTALLER_PROCESSES = {
    "apk", "apt", "apt-get", "dpkg",
    "pip", "pip3", "pip3.12", "pip3.13",
    "npm", "yarn", "pnpm",
}


def init_idle_db():
    with closing(connect_db()) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS lab_activity (
                token TEXT PRIMARY KEY,
                last_activity REAL NOT NULL,
                end_reason TEXT,
                monitor_note TEXT NOT NULL DEFAULT ''
            )
        """)
        db.commit()


def get_idle_record(token):
    with closing(connect_db()) as db:
        return db.execute(
            "SELECT * FROM lab_activity WHERE token = ?",
            (token,),
        ).fetchone()


def touch_idle(token):
    with closing(connect_db()) as db:
        db.execute("""
            INSERT INTO lab_activity(token, last_activity)
            VALUES (?, ?)
            ON CONFLICT(token) DO UPDATE SET
                last_activity = excluded.last_activity,
                monitor_note = ''
        """, (token, time.time()))
        db.commit()


def installer_running(container_name):
    try:
        container = docker_client.containers.get(container_name)
        result = container.exec_run(["ps", "-eo", "comm"])

        if result.exit_code != 0:
            raise RuntimeError(
                f"Process check exited with code {result.exit_code}"
            )

        output = result.output.decode("utf-8", errors="replace")
        names = {
            Path(line.strip()).name
            for line in output.splitlines()
            if line.strip() and line.strip() != "COMMAND"
        }

        if not names:
            raise RuntimeError("Process check returned no process names")

        return bool(names & INSTALLER_PROCESSES)
    except Exception as exc:
        print(
            f"Installer check failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
        raise


def set_idle_note(token, note):
    with closing(connect_db()) as db:
        db.execute(
            "UPDATE lab_activity SET monitor_note = ? WHERE token = ?",
            (note, token),
        )
        db.commit()


def enforce_idle(row):
    token = row["token"]
    record = get_idle_record(token)

    if row["status"] != "active" or record is None:
        return

    now = datetime.now(timezone.utc)
    if now >= datetime.fromisoformat(row["expires_at"]):
        delete_session(token)
        return

    try:
        busy = installer_running(row["container_name"])
    except Exception:
        # A failed process check must not be mistaken for an idle desktop.
        set_idle_note(token, "Activity check unavailable; idle cleanup delayed.")
        return

    if busy:
        touch_idle(token)
        set_idle_note(token, "Package installation detected.")
        return

    set_idle_note(token, "")

    if time.time() - record["last_activity"] >= IDLE_END_SECONDS:
        delete_session(token)
        with closing(connect_db()) as db:
            db.execute(
                "UPDATE lab_activity SET end_reason = 'inactivity' WHERE token = ?",
                (token,),
            )
            db.commit()


async def idle_worker():
    while True:
        await asyncio.sleep(10)
        try:
            async with creation_lock:
                with closing(connect_db()) as db:
                    rows = db.execute("""
                        SELECT s.* FROM sessions s
                        JOIN lab_activity a ON a.token = s.token
                        WHERE s.status = 'active'
                    """).fetchall()

                for row in rows:
                    try:
                        enforce_idle(row)
                    except Exception as exc:
                        print(f"Inactivity cleanup failed: {exc}", flush=True)
        except Exception as exc:
            print(f"Inactivity worker failed: {exc}", flush=True)


@app.on_event("startup")
async def start_idle_monitor():
    init_idle_db()
    app.state.idle_task = asyncio.create_task(idle_worker())


@app.on_event("shutdown")
async def stop_idle_monitor():
    task = getattr(app.state, "idle_task", None)
    if task:
        task.cancel()


def idle_response(row):
    record = get_idle_record(row["token"])
    idle = max(0, time.time() - record["last_activity"]) if record else 0

    return {
        "status": row["status"],
        "tracking": record is not None,
        "idle_seconds": int(idle),
        "warning": row["status"] == "active" and idle >= IDLE_WARNING_SECONDS,
        "seconds_until_close": max(0, int(IDLE_END_SECONDS - idle)),
        "end_reason": record["end_reason"] if record else None,
        "monitor_note": record["monitor_note"] if record else "",
    }


@app.get("/lab/{token}/activity")
async def read_lab_activity(
    token: str,
    x_session_password: str = Header(...),
):
    row = authorize_lab_session(token, x_session_password)
    return idle_response(row)


@app.post("/lab/{token}/activity")
async def record_lab_activity(
    token: str,
    x_session_password: str = Header(...),
):
    async with creation_lock:
        row = authorize_lab_session(token, x_session_password)

        # Check an existing idle deadline before allowing a reset.
        enforce_idle(row)
        row = authorize_lab_session(token, x_session_password)

        if row["status"] == "active":
            touch_idle(token)

        return idle_response(row)


# Startup readiness: HTTP service availability is distinct from a rendered desktop.
import base64
from urllib.request import Request, build_opener, ProxyHandler


def session_payload(row):
    return {
        "session_id": row["token"], "status": row["status"],
        "desktop_url": f"{PUBLIC_BASE_URL}/s/{row['token']}/",
        "desktop_username": "student", "desktop_password": row["password"],
        "expires_at": row["expires_at"], "session_minutes": row["session_minutes"] or SESSION_MINUTES,
        "college_name": row["college_name"], "classroom_name": row["classroom_name"],
        "template_name": row["template_name"],
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


def desktop_http_ready(row):
    try:
        auth = base64.b64encode(f"student:{row['password']}".encode()).decode()
        request = Request(f"http://{row['container_name']}:3000/",
                          headers={"Authorization": "Basic " + auth})
        with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
            body = response.read(65536).lower()
            return response.status == 200 and b"<html" in body and b"<script" in body
    except Exception:
        return False


@app.get("/lab/{token}/ready")
async def desktop_readiness(token: str, x_session_password: str = Header(...)):
    row = authorize_lab_session(token, x_session_password)
    ready = False
    if row["status"] in ("starting", "active"):
        ready = await asyncio.to_thread(desktop_http_ready, row)
    latest = authorize_lab_session(token, x_session_password)
    return {"status": latest["status"], "service_ready": ready,
            "expires_at": latest["expires_at"]}


@app.post("/lab/{token}/activate")
async def activate_desktop(token: str, x_session_password: str = Header(...)):
    async with creation_lock:
        row = authorize_lab_session(token, x_session_password)
        if row["status"] == "active":
            return session_payload(row)
        if row["status"] != "starting":
            raise HTTPException(409, "This session has ended.")
        if datetime.now(timezone.utc) >= datetime.fromisoformat(row["expires_at"]):
            delete_session(token)
            raise HTTPException(409, "Startup timed out. Start a new lab.")
        if not await asyncio.to_thread(desktop_http_ready, row):
            raise HTTPException(503, "Desktop is still starting. Please retry.")
        # Expiry worker could have run while the readiness check awaited I/O.
        row = authorize_lab_session(token, x_session_password)
        if row["status"] != "starting" or datetime.now(timezone.utc) >= datetime.fromisoformat(row["expires_at"]):
            raise HTTPException(409, "Startup has ended.")
        expires = datetime.now(timezone.utc) + timedelta(minutes=row["session_minutes"] or SESSION_MINUTES)
        with closing(connect_db()) as db:
            db.execute("UPDATE sessions SET status='active', expires_at=? WHERE token=?",
                       (expires.isoformat(), token))
            db.commit()
        touch_idle(token)
        return session_payload(authorize_lab_session(token, x_session_password))
