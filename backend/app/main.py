import hmac
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import db

APP_PASSWORD = os.environ.get("APP_PASSWORD")
SESSION_SECRET = os.environ.get("SESSION_SECRET")
HTTPS_ONLY = os.environ.get("HTTPS_ONLY", "true").lower() not in ("false", "0", "no")
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

if not APP_PASSWORD:
    raise RuntimeError("APP_PASSWORD environment variable must be set")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable must be set")

db.init_db()

app = FastAPI(title="CalcVault")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="cv_session",
    same_site="lax",
    https_only=HTTPS_ONLY,
    max_age=60 * 60 * 24 * 30,
)

# --- naive login rate limiting: per-IP attempt window ---
_login_attempts: dict[str, list[float]] = {}
MAX_ATTEMPTS = 10
WINDOW_SECONDS = 15 * 60


def _rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < WINDOW_SECONDS]
    _login_attempts[ip] = attempts
    return len(attempts) >= MAX_ATTEMPTS


def _record_attempt(ip: str):
    _login_attempts.setdefault(ip, []).append(time.time())


auth_router = APIRouter(prefix="/api")


class LoginBody(BaseModel):
    password: str


@auth_router.get("/session")
def session_status(request: Request):
    return {"authed": bool(request.session.get("authed"))}


@auth_router.post("/login")
def login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many attempts, try again later")
    _record_attempt(ip)
    if not hmac.compare_digest(body.password, APP_PASSWORD):
        raise HTTPException(status_code=401, detail="Incorrect password")
    request.session["authed"] = True
    return {"authed": True}


@auth_router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"authed": False}


def require_auth(request: Request):
    if not request.session.get("authed"):
        raise HTTPException(status_code=401, detail="Not authenticated")


api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@api.get("/tree")
def tree():
    return db.get_tree()


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None


@api.post("/folders")
def create_folder(body: FolderCreate):
    return db.create_folder(body.name, body.parent_id)


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None


@api.patch("/folders/{folder_id}")
def update_folder(folder_id: int, body: FolderUpdate):
    raw_keys = getattr(body, "model_fields_set", None) or getattr(body, "__fields_set__", set())
    updated = db.update_folder(
        folder_id,
        body.name,
        body.parent_id,
        has_parent="parent_id" in raw_keys,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Folder not found")
    return updated


@api.delete("/folders/{folder_id}")
def delete_folder(folder_id: int):
    if not db.delete_folder(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"ok": True}


class CalcCreate(BaseModel):
    name: str
    folder_id: Optional[int] = None


@api.post("/calculators")
def create_calculator(body: CalcCreate):
    return db.create_calculator(body.name, body.folder_id, "calculator")


@api.get("/calculators/{calc_id}")
def get_calculator(calc_id: int):
    calc = db.get_calculator(calc_id)
    if not calc:
        raise HTTPException(status_code=404, detail="Not found")
    return calc


class CalcUpdate(BaseModel):
    name: Optional[str] = None
    folder_id: Optional[int] = None
    data: Optional[dict] = None


@api.patch("/calculators/{calc_id}")
def update_calculator(calc_id: int, body: CalcUpdate):
    raw_keys = getattr(body, "model_fields_set", None) or getattr(body, "__fields_set__", set())
    updated = db.update_calculator(
        calc_id,
        body.name,
        body.folder_id,
        has_folder="folder_id" in raw_keys,
        data=body.data,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Not found")
    return updated


@api.delete("/calculators/{calc_id}")
def delete_calculator(calc_id: int):
    if not db.delete_calculator(calc_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


app.include_router(auth_router)
app.include_router(api)

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
