from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import re
import uuid
import json
import logging
import asyncio
import io
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any

import bcrypt
import jwt
import requests
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, UploadFile, File, Form, Query, Request
from fastapi.responses import StreamingResponse, Response, RedirectResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field

# ChipSutra provider abstractions (auto-fall-back Emergent → standalone)
from llm_provider import stream_chat as llm_stream_chat, available_providers as llm_available_providers, ollama_status as llm_ollama_status
from rag import augment_generation_context, rag_status as llm_rag_status
from storage_provider import init_storage as storage_init, put_object as put_object_impl, get_object as get_object_impl, storage_mode
from google_auth import google_mode, resolve_emergent_session, build_google_auth_url, exchange_code as google_exchange_code

# =========================
# Config
# =========================
def _env(key: str, default: Optional[str] = None) -> str:
    """Read env var; strip whitespace, UTF-8 BOM, and surrounding quotes (Docker env_file keeps quotes)."""
    raw = os.environ.get(key, default)
    if raw is None:
        raise KeyError(key)
    return raw.strip().strip('"').strip("'").lstrip("\ufeff")


MONGO_URL = _env("MONGO_URL")
DB_NAME = _env("DB_NAME")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
JWT_ALGORITHM = "HS256"
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
APP_NAME = os.environ.get("APP_NAME", "chipsutra")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@chipsutra.ai")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@ChipSutra2026")

# Free-tier quota: N generations per user per day (0 = unlimited — DEFAULT OPEN ACCESS)
FREE_DAILY_QUOTA = int(os.environ.get("FREE_DAILY_QUOTA", "0"))
# Set REQUIRE_EMAIL_VERIFICATION=true to block generation for unverified emails (default off = open access)
REQUIRE_EMAIL_VERIFICATION = os.environ.get("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true"

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"  # legacy, unused

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("chipsutra")

# =========================
# Database
# =========================
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# =========================
# App
# =========================
app = FastAPI(title="ChipSutra API")
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Object Storage (delegates to storage_provider abstraction)
# =========================
def init_storage():
    return storage_init()

def put_object(path: str, data: bytes, content_type: str) -> dict:
    return put_object_impl(path, data, content_type)

def get_object(path: str) -> tuple[bytes, str]:
    return get_object_impl(path)

# =========================
# Auth helpers
# =========================
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def find_accessible_project(pid: str, user_id: str, min_role: str = "viewer") -> Optional[dict]:
    """Return project if user is owner or collaborator with sufficient role. Roles: viewer < editor < owner."""
    doc = await db.projects.find_one({"id": pid}, {"_id": 0})
    if not doc:
        return None
    if doc.get("user_id") == user_id:
        return doc
    for c in doc.get("collaborators", []):
        if c.get("user_id") == user_id:
            if min_role == "viewer":
                return doc
            if min_role == "editor" and c.get("role") in ("editor",):
                return doc
    return None

async def require_project(pid: str, user_id: str, min_role: str = "viewer") -> dict:
    doc = await find_accessible_project(pid, user_id, min_role)
    if not doc:
        raise HTTPException(404, "Project not found or insufficient permission")
    return doc

# =========================
# Models
# =========================
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class WaitlistIn(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    tier: Optional[str] = None

class ContactIn(BaseModel):
    name: str
    email: EmailStr
    message: str

class ProjectIn(BaseModel):
    name: str
    description: Optional[str] = ""
    design_type: str = "block"  # block, ip, subsystem, soc, chiplet, multi-chiplet
    language: str = "systemverilog"  # verilog, systemverilog, vhdl, uvm
    workspace_id: Optional[str] = None

class GenerateIn(BaseModel):
    project_id: str
    module: str  # testbench, assertions, checkers, covergroups, spec2rtl, rtl2spec, testplan, coverage_holes, debug
    model_provider: str = "anthropic"  # anthropic | openai
    model_name: str = "claude-sonnet-4-5-20250929"  # or gpt-5.2
    prompt: Optional[str] = ""
    file_ids: Optional[List[str]] = []
    language: Optional[str] = "systemverilog"

MODULE_PROMPTS = {
    "testbench": "You are an expert VLSI verification engineer. Generate a scalable, reusable UVM-style testbench for the provided RTL/spec in {language}. Include: interfaces, transactions, driver, monitor, scoreboard, sequences, and error injection hooks. Output only code with brief inline comments.",
    "assertions": "You are an expert in SystemVerilog Assertions (SVA). Generate comprehensive assertions for the provided RTL in {language}. Cover: protocol correctness, safety properties, liveness, and edge cases. Output only SVA code with brief comments.",
    "checkers": "You are an expert verification engineer. Generate reusable checker modules for the provided RTL/spec in {language}. Include: reference model comparisons, protocol checkers, and functional checkers. Output only code.",
    "covergroups": "You are a coverage expert. Generate covergroups in {language} for the provided RTL/spec. Include: bins, cross coverage, illegal_bins, and comments explaining each coverage point. Output only code.",
    "spec2rtl": "You are an expert RTL designer. Given the specification below, generate synthesizable RTL code in {language}. Output only code with brief comments.",
    "rtl2spec": "You are a technical writer + verification expert. Given the RTL below, produce a detailed specification document in Markdown covering: overview, interface signals, functional behavior, timing, corner cases, and verification hints.",
    "testplan": "You are a verification lead. Given the RTL/spec below, produce a comprehensive testplan in Markdown covering: features, scenarios, corner cases, coverage goals, and assertion goals. Structure with sections and tables.",
    "coverage_holes": "You are a coverage closure expert. Given the coverage report / RTL below, identify coverage holes and generate additional {language} tests / sequences to close them. Output actionable test code and short rationale for each.",
    "debug": "You are a hardware debug expert. Analyze the simulation log / failure report below and provide root-cause hypotheses ranked by likelihood, with next debug steps. Output as Markdown."
}

# =========================
# Startup
# =========================
@app.on_event("startup")
async def startup():
    try:
        await client.admin.command("ping")
    except Exception as e:
        hint = ""
        if "localhost" in MONGO_URL or "127.0.0.1" in MONGO_URL:
            hint = (
                " In Docker, localhost is the container — use MongoDB Atlas "
                "(mongodb+srv://...) in backend/.env, not mongodb://localhost:27017."
            )
        logger.error("MongoDB connection failed: %s.%s", e, hint)
        raise RuntimeError(f"MongoDB connection failed: {e}.{hint}") from e

    await db.users.create_index("email", unique=True)
    await db.projects.create_index("user_id")
    await db.files.create_index("project_id")
    await db.generations.create_index("project_id")
    await db.waitlist.create_index("email", unique=True)
    await db.workspaces.create_index("owner_id")
    await db.workspaces.create_index("members.user_id")
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.activity.create_index([("workspace_id", 1), ("created_at", -1)])
    # Seed admin
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "name": "ChipSutra Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Admin user seeded: {ADMIN_EMAIL}")
    init_storage()  # storage_provider abstraction — auto Emergent or local
    # Optional anonymous telemetry (opt-in, privacy-safe)
    if os.environ.get("TELEMETRY_ENABLED", "false").lower() == "true":
        import asyncio as _asyncio
        _asyncio.create_task(_send_telemetry_ping())

async def _send_telemetry_ping():
    """Anonymous one-time startup ping. Sends only a random UUID + version. No user data."""
    try:
        import httpx
        install_id = os.environ.get("CHIPSUTRA_INSTALL_ID")
        if not install_id:
            install_id = str(uuid.uuid4())
            logger.info(f"[telemetry] first-run install_id={install_id} (set CHIPSUTRA_INSTALL_ID to persist)")
        payload = {"install_id": install_id, "version": "0.8.0", "ts": datetime.now(timezone.utc).isoformat()}
        endpoint = os.environ.get("TELEMETRY_ENDPOINT", "https://chipsutra-verify.emergent.host/api/telemetry/hello")
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(endpoint, json=payload)
        logger.info("[telemetry] anonymous startup ping sent")
    except Exception as e:
        logger.debug(f"[telemetry] ping skipped: {e}")

@api.post("/telemetry/hello")
async def telemetry_hello(request: Request):
    """Receive anonymous install ping from self-hosted installations."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False}
    await db.telemetry.insert_one({
        "install_id": body.get("install_id"),
        "version": body.get("version"),
        "user_agent": request.headers.get("user-agent", "")[:200],
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}

@app.on_event("shutdown")
async def shutdown():
    client.close()

# =========================
# Health
# =========================
@api.get("/")
async def root():
    return {"name": "ChipSutra API", "status": "ok"}

@api.get("/health")
async def health():
    import shutil as _sh
    providers = llm_available_providers()
    return {
        "status": "healthy",
        "storage": storage_mode(),
        "verilator": bool(_sh.which("verilator")),
        "yosys": bool(_sh.which("yosys")),
        "sby": bool(_sh.which("sby")),
        "llm_providers": providers,
        "ollama": llm_ollama_status(),
        "rag": llm_rag_status(),
        "google_auth": google_mode(),
    }

# =========================
# Auth endpoints
# =========================
@api.post("/auth/register")
async def register(inp: RegisterIn):
    email = inp.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    user_id = str(uuid.uuid4())
    doc = {
        "id": user_id,
        "email": email,
        "password_hash": hash_password(inp.password),
        "name": inp.name,
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    token = create_access_token(user_id, email)
    return {"access_token": token, "user": {"id": user_id, "email": email, "name": inp.name, "role": "user"}}

@api.post("/auth/login")
async def login(inp: LoginIn):
    email = inp.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(inp.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    token = create_access_token(user["id"], user["email"])
    return {
        "access_token": token,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user.get("role", "user")}
    }

@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    # Attach usage info
    today = datetime.now(timezone.utc).date().isoformat()
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "daily_generations": 1, "daily_reset": 1})
    used_today = (u.get("daily_generations", 0) if u.get("daily_reset") == today else 0)
    user["usage"] = {
        "generations_today": used_today,
        "free_daily_quota": FREE_DAILY_QUOTA,
        "unlimited": user.get("tier") == "pro" or user.get("role") == "admin",
    }
    return user

@api.post("/auth/send-verify")
async def send_verify(user=Depends(get_current_user)):
    """Generate an email verification token. If SMTP is configured, would send email;
    for now the token is logged for manual delivery / opt-in email providers."""
    if user.get("email_verified"):
        return {"ok": True, "already_verified": True}
    token = str(uuid.uuid4()) + "-" + str(uuid.uuid4())
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "email_verify_token": token,
        "email_verify_sent_at": datetime.now(timezone.utc).isoformat(),
    }})
    verify_link = f"/api/auth/verify?token={token}"
    logger.info(f"[email-verify] user={user['email']} link={verify_link}")
    # TODO: integrate SMTP / Resend / SendGrid here
    return {"ok": True, "verify_link_hint": verify_link, "note": "In self-host mode this link is logged. Wire an email provider (Resend/SMTP) to auto-send."}

@api.get("/auth/verify")
async def verify_email(token: str = Query(...)):
    u = await db.users.find_one({"email_verify_token": token}, {"_id": 0})
    if not u:
        raise HTTPException(400, "Invalid or expired verification token")
    await db.users.update_one({"id": u["id"]}, {
        "$set": {"email_verified": True, "email_verified_at": datetime.now(timezone.utc).isoformat()},
        "$unset": {"email_verify_token": ""}
    })
    return {"ok": True, "email": u["email"], "message": "Email verified. You can now generate."}

@api.post("/auth/logout")
async def logout(user=Depends(get_current_user)):
    return {"ok": True}

# =========================
# Waitlist / Contact
# =========================
@api.post("/waitlist")
async def waitlist(inp: WaitlistIn):
    doc = {
        "id": str(uuid.uuid4()),
        "email": inp.email.lower(),
        "name": inp.name,
        "company": inp.company,
        "role": inp.role,
        "tier": inp.tier,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.waitlist.insert_one(doc)
    except Exception:
        raise HTTPException(400, "Email already on waitlist")
    return {"ok": True, "message": "Added to waitlist"}

@api.post("/contact")
async def contact(inp: ContactIn):
    doc = inp.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.contact_messages.insert_one(doc)
    return {"ok": True}

# =========================
# Projects
# =========================
@api.post("/projects")
async def create_project(inp: ProjectIn, user=Depends(get_current_user)):
    pid = str(uuid.uuid4())
    if inp.workspace_id:
        role = await get_workspace_role(inp.workspace_id, user["id"])
        if not role:
            raise HTTPException(403, "You are not a member of that workspace")
    doc = {
        "id": pid,
        "user_id": user["id"],
        "workspace_id": inp.workspace_id,
        "name": inp.name,
        "description": inp.description,
        "design_type": inp.design_type,
        "language": inp.language,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.projects.insert_one(doc)
    if inp.workspace_id:
        await log_activity(inp.workspace_id, user["id"], user.get("name") or user["email"],
                           "project_created", "project", pid, inp.name)
    doc.pop("_id", None)
    return doc

@api.get("/projects")
async def list_projects(user=Depends(get_current_user)):
    docs = await db.projects.find(
        {"$or": [{"user_id": user["id"]}, {"collaborators.user_id": user["id"]}]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    for d in docs:
        d["is_owner"] = d.get("user_id") == user["id"]
    return docs

@api.get("/projects/{pid}")
async def get_project(pid: str, user=Depends(get_current_user)):
    doc = await require_project(pid, user["id"], "viewer")
    files = await db.files.find({"project_id": pid, "is_deleted": {"$ne": True}}, {"_id": 0}).to_list(500)
    generations = await db.generations.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(200)
    doc["files"] = files
    doc["generations"] = generations
    doc["is_owner"] = doc.get("user_id") == user["id"]
    return doc

@api.delete("/projects/{pid}")
async def delete_project(pid: str, user=Depends(get_current_user)):
    res = await db.projects.delete_one({"id": pid, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Project not found or you are not the owner")
    await db.files.update_many({"project_id": pid}, {"$set": {"is_deleted": True}})
    return {"ok": True}

# =========================
# Collaboration
# =========================
class InviteIn(BaseModel):
    email: EmailStr
    role: str = "editor"  # editor | viewer

@api.post("/projects/{pid}/collaborators")
async def add_collaborator(pid: str, inp: InviteIn, user=Depends(get_current_user)):
    proj = await db.projects.find_one({"id": pid, "user_id": user["id"]})
    if not proj:
        raise HTTPException(404, "Project not found or you are not the owner")
    email = inp.email.lower()
    if email == user["email"]:
        raise HTTPException(400, "You are already the owner")
    invited_user = await db.users.find_one({"email": email})
    if not invited_user:
        raise HTTPException(404, "No ChipSutra user with that email. Ask them to sign up first.")
    for c in proj.get("collaborators", []):
        if c.get("user_id") == invited_user["id"]:
            raise HTTPException(400, "Already a collaborator")
    entry = {
        "user_id": invited_user["id"],
        "email": email,
        "name": invited_user.get("name"),
        "role": inp.role if inp.role in ("editor", "viewer") else "editor",
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.projects.update_one({"id": pid}, {"$push": {"collaborators": entry}})
    # Notify invited user
    await create_notification(
        invited_user["id"],
        kind="project_invite",
        title=f"You were added to '{proj['name']}'",
        body=f"{user.get('name') or user['email']} invited you as {entry['role']}.",
        link=f"/app/projects/{pid}",
        meta={"project_id": pid, "role": entry["role"]},
    )
    await log_activity(
        workspace_id=proj.get("workspace_id"),
        actor_id=user["id"], actor_name=user.get("name") or user["email"],
        action="collaborator_added",
        target_type="project", target_id=pid, target_name=proj["name"],
        meta={"invited_email": email, "role": entry["role"]},
    )
    return entry

@api.get("/projects/{pid}/collaborators")
async def list_collaborators(pid: str, user=Depends(get_current_user)):
    proj = await require_project(pid, user["id"], "viewer")
    return proj.get("collaborators", [])

@api.delete("/projects/{pid}/collaborators/{collab_user_id}")
async def remove_collaborator(pid: str, collab_user_id: str, user=Depends(get_current_user)):
    proj = await db.projects.find_one({"id": pid, "user_id": user["id"]})
    if not proj:
        raise HTTPException(404, "Project not found or you are not the owner")
    await db.projects.update_one({"id": pid}, {"$pull": {"collaborators": {"user_id": collab_user_id}}})
    return {"ok": True}

# =========================
# Comments on generations
# =========================
class CommentIn(BaseModel):
    text: str

@api.post("/generations/{gen_id}/comments")
async def add_comment(gen_id: str, inp: CommentIn, user=Depends(get_current_user)):
    gen = await db.generations.find_one({"id": gen_id}, {"_id": 0})
    if not gen:
        raise HTTPException(404, "Generation not found")
    await require_project(gen["project_id"], user["id"], "viewer")
    doc = {
        "id": str(uuid.uuid4()),
        "generation_id": gen_id,
        "user_id": user["id"],
        "user_name": user.get("name") or user["email"],
        "user_email": user["email"],
        "text": inp.text[:2000],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.comments.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api.get("/generations/{gen_id}/comments")
async def list_comments(gen_id: str, user=Depends(get_current_user)):
    gen = await db.generations.find_one({"id": gen_id}, {"_id": 0})
    if not gen:
        raise HTTPException(404, "Generation not found")
    await require_project(gen["project_id"], user["id"], "viewer")
    docs = await db.comments.find({"generation_id": gen_id}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return docs

@api.delete("/comments/{comment_id}")
async def delete_comment(comment_id: str, user=Depends(get_current_user)):
    doc = await db.comments.find_one({"id": comment_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Comment not found")
    if doc["user_id"] != user["id"]:
        raise HTTPException(403, "You can only delete your own comments")
    await db.comments.delete_one({"id": comment_id})
    return {"ok": True}

# =========================
# File uploads
# =========================
ALLOWED_EXTS = {"v", "sv", "vhd", "vhdl", "pdf", "md", "docx", "txt", "vcd", "csv", "json", "log", "rpt"}

@api.post("/projects/{pid}/files")
async def upload_file(pid: str, file: UploadFile = File(...), kind: str = Form("rtl"), user=Depends(get_current_user)):
    await require_project(pid, user["id"], "editor")
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin").lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported file extension: .{ext}")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 10MB)")
    file_id = str(uuid.uuid4())
    path = f"{APP_NAME}/projects/{pid}/{file_id}.{ext}"
    try:
        result = put_object(path, data, file.content_type or "application/octet-stream")
        storage_path = result["path"]
    except Exception as e:
        logger.warning(f"Storage upload failed, storing inline: {e}")
        storage_path = None
    doc = {
        "id": file_id,
        "project_id": pid,
        "original_filename": file.filename,
        "ext": ext,
        "kind": kind,
        "size": len(data),
        "content_type": file.content_type or "application/octet-stream",
        "storage_path": storage_path,
        "inline_content": data.decode("utf-8", errors="ignore") if storage_path is None and ext in ("v","sv","vhd","vhdl","txt","md","vcd","log","rpt","csv","json") else None,
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.files.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api.get("/projects/{pid}/files/{file_id}/content")
async def get_file_content(pid: str, file_id: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    doc = await db.files.find_one({"id": file_id, "project_id": pid, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "File not found")
    if doc.get("inline_content") is not None:
        return {"content": doc["inline_content"], "filename": doc["original_filename"], "ext": doc["ext"]}
    if doc.get("storage_path"):
        try:
            data, ct = get_object(doc["storage_path"])
            text = data.decode("utf-8", errors="ignore")
            return {"content": text, "filename": doc["original_filename"], "ext": doc["ext"]}
        except Exception as e:
            raise HTTPException(500, f"Cannot read file: {e}")
    return {"content": "", "filename": doc["original_filename"], "ext": doc["ext"]}

@api.delete("/projects/{pid}/files/{file_id}")
async def delete_file(pid: str, file_id: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "editor")
    await db.files.update_one({"id": file_id, "project_id": pid}, {"$set": {"is_deleted": True}})
    return {"ok": True}

# =========================
# AI Generation
# =========================
def _get_file_text(fdoc: dict) -> str:
    if fdoc.get("inline_content"):
        return fdoc["inline_content"]
    if fdoc.get("storage_path"):
        try:
            data, _ = get_object(fdoc["storage_path"])
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return ""

@api.post("/generate/stream")
async def generate_stream(inp: GenerateIn, user=Depends(get_current_user)):
    proj = await require_project(inp.project_id, user["id"], "editor")
    if inp.module not in MODULE_PROMPTS:
        raise HTTPException(400, "Unknown module")

    # ---- Quota + email verification enforcement (skip for admins & Pro tier) ----
    tier = user.get("tier", "free")
    if user.get("role") != "admin" and tier == "free":
        if REQUIRE_EMAIL_VERIFICATION and not user.get("email_verified", False) and user.get("auth_provider") != "google":
            raise HTTPException(403, "Please verify your email before generating. Check /api/auth/send-verify to resend the link.")
        if FREE_DAILY_QUOTA > 0:
            today = datetime.now(timezone.utc).date().isoformat()
            u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "daily_generations": 1, "daily_reset": 1})
            if u.get("daily_reset") != today:
                await db.users.update_one({"id": user["id"]}, {"$set": {"daily_generations": 0, "daily_reset": today}})
                used = 0
            else:
                used = u.get("daily_generations", 0)
            if used >= FREE_DAILY_QUOTA:
                raise HTTPException(429, f"Daily quota reached ({FREE_DAILY_QUOTA} generations/day on Free tier). Upgrade to Pro for unlimited.")
            await db.users.update_one({"id": user["id"]}, {"$inc": {"daily_generations": 1}})

    # Gather file contexts
    file_context = ""
    file_names: List[str] = []
    if inp.file_ids:
        fdocs = await db.files.find({"id": {"$in": inp.file_ids}, "project_id": inp.project_id}, {"_id": 0}).to_list(50)
        for f in fdocs:
            file_names.append(f.get("original_filename") or "")
            text = _get_file_text(f)
            if text:
                file_context += f"\n\n--- FILE: {f['original_filename']} (kind={f.get('kind','')}) ---\n{text[:20000]}\n"

    lang = inp.language or proj.get("language", "systemverilog")
    system_msg = MODULE_PROMPTS[inp.module].format(language=lang)
    system_msg += "\n\nYou are ChipSutra, an EDA verification assistant. Be concise, precise, and technical."
    rag_block = augment_generation_context(
        module=inp.module,
        prompt=(inp.prompt or "") + " " + file_context[:2000],
        filenames=file_names,
    )
    if rag_block:
        system_msg += (
            "\n\n--- Domain knowledge (reference only; user RTL/spec/files override if conflict) ---\n"
            + rag_block
        )

    user_text = (inp.prompt or "").strip()
    if not user_text:
        user_text = "Please generate the requested artifact based on the attached files."
    if file_context:
        user_text += "\n\n" + file_context

    session_id = str(uuid.uuid4())
    gen_id = str(uuid.uuid4())
    gen_doc = {
        "id": gen_id,
        "project_id": inp.project_id,
        "user_id": user["id"],
        "module": inp.module,
        "provider": inp.model_provider,
        "model": inp.model_name,
        "prompt": inp.prompt or "",
        "file_ids": inp.file_ids or [],
        "output": "",
        "status": "streaming",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.generations.insert_one(gen_doc)

    async def event_gen():
        yield f"data: {json.dumps({'type': 'meta', 'generation_id': gen_id})}\n\n"
        accumulated = []
        try:
            async for delta in llm_stream_chat(
                provider=inp.model_provider,
                model=inp.model_name,
                system=system_msg,
                user_text=user_text,
                session_id=session_id,
            ):
                accumulated.append(delta)
                yield f"data: {json.dumps({'type': 'delta', 'content': delta})}\n\n"
            full = "".join(accumulated)
            await db.generations.update_one({"id": gen_id}, {"$set": {"output": full, "status": "done", "completed_at": datetime.now(timezone.utc).isoformat()}})
            yield f"data: {json.dumps({'type': 'done', 'generation_id': gen_id})}\n\n"
        except Exception as e:
            logger.exception("Generation error")
            err = str(e)
            await db.generations.update_one({"id": gen_id}, {"$set": {"status": "error", "error": err}})
            yield f"data: {json.dumps({'type': 'error', 'error': err})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@api.get("/generations/{gen_id}")
async def get_generation(gen_id: str, user=Depends(get_current_user)):
    doc = await db.generations.find_one({"id": gen_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Generation not found")
    await require_project(doc["project_id"], user["id"], "viewer")
    return doc

@api.get("/projects/{pid}/generations")
async def list_generations(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    docs = await db.generations.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return docs

# =========================
# Coverage parser (simple)
# =========================
@api.post("/coverage/parse")
async def parse_coverage(file: UploadFile = File(...), user=Depends(get_current_user)):
    data = (await file.read()).decode("utf-8", errors="ignore")
    lines = data.splitlines()
    metrics = []
    # Look for lines like: "Statement coverage: 87.5%" or "line: 92%"
    pat = re.compile(r"([A-Za-z][A-Za-z _\-]{2,40})\s*[:=]\s*([0-9]{1,3}(?:\.[0-9]+)?)\s*%")
    for line in lines:
        for m in pat.finditer(line):
            name = m.group(1).strip()
            try:
                pct = float(m.group(2))
                if 0 <= pct <= 100:
                    metrics.append({"name": name, "pct": pct})
            except Exception:
                pass
    # deduplicate by name (keep last)
    seen = {}
    for m in metrics:
        seen[m["name"].lower()] = m
    metrics = list(seen.values())[:40]

    holes = [m for m in metrics if m["pct"] < 90]
    overall = round(sum(m["pct"] for m in metrics) / len(metrics), 1) if metrics else 0.0
    return {
        "overall": overall,
        "metrics": metrics,
        "holes": sorted(holes, key=lambda x: x["pct"]),
        "count": len(metrics),
    }

# =========================
# VCD parser (simple)
# =========================
def parse_vcd(text: str, max_signals: int = 32, max_events: int = 2000) -> dict:
    lines = text.splitlines()
    signals = {}  # id -> {name, width}
    order = []
    timescale = "1ns"
    current_scope = []
    i = 0
    in_header = True
    time_events = []  # list of (time, id, value)
    current_time = 0

    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line.startswith("$timescale"):
            # read until $end
            buf = []
            while i < len(lines) and "$end" not in line:
                line = lines[i].strip(); i += 1
                buf.append(line)
            timescale = " ".join(buf).replace("$end", "").strip() or timescale
            continue
        if line.startswith("$scope"):
            parts = line.split()
            if len(parts) >= 3:
                current_scope.append(parts[2])
            continue
        if line.startswith("$upscope"):
            if current_scope:
                current_scope.pop()
            continue
        if line.startswith("$var"):
            parts = line.split()
            # $var wire 1 ! clk $end
            if len(parts) >= 5:
                width = int(parts[2]) if parts[2].isdigit() else 1
                sid = parts[3]
                name = parts[4]
                full = ".".join(current_scope + [name]) if current_scope else name
                if sid not in signals and len(signals) < max_signals:
                    signals[sid] = {"name": full, "width": width}
                    order.append(sid)
            continue
        if line.startswith("$enddefinitions"):
            in_header = False
            continue
        if line.startswith("#"):
            try:
                current_time = int(line[1:])
            except Exception:
                pass
            continue
        if not in_header and line and not line.startswith("$"):
            # value change
            if line[0] in ("0", "1", "x", "z", "X", "Z"):
                val = line[0]
                sid = line[1:]
                if sid in signals and len(time_events) < max_events:
                    time_events.append((current_time, sid, val))
            elif line[0] in ("b", "B"):
                # bit vector
                parts = line.split()
                if len(parts) >= 2:
                    val = parts[0][1:]
                    sid = parts[1]
                    if sid in signals and len(time_events) < max_events:
                        time_events.append((current_time, sid, val))

    # Build timeline per signal
    times = sorted({t for t, _, _ in time_events})
    times = times[:200]  # limit
    per_sig = {sid: [] for sid in order}
    # Compute value at each time step by iterating events
    last = {sid: "x" for sid in order}
    events_by_time = {}
    for t, sid, v in time_events:
        events_by_time.setdefault(t, []).append((sid, v))
    tracks = []
    for sid in order:
        row = []
        for t in times:
            if t in events_by_time:
                for esid, ev in events_by_time[t]:
                    if esid == sid:
                        last[sid] = ev
            row.append(last[sid])
        tracks.append({"id": sid, "name": signals[sid]["name"], "width": signals[sid]["width"], "values": row})
    return {"timescale": timescale, "times": times, "tracks": tracks, "signal_count": len(order)}

@api.post("/waveform/parse")
async def parse_waveform(file: UploadFile = File(...), user=Depends(get_current_user)):
    data = (await file.read()).decode("utf-8", errors="ignore")
    try:
        result = parse_vcd(data)
    except Exception as e:
        raise HTTPException(400, f"Invalid VCD: {e}")
    return result

# =========================
# Verilator simulation
# =========================
import shutil
import subprocess
import tempfile

VERILATOR_BIN = shutil.which("verilator")

class SimulateIn(BaseModel):
    project_id: str
    rtl_file_ids: List[str] = []
    tb_file_id: Optional[str] = None
    top_module: Optional[str] = None
    mode: str = "lint"  # lint | run
    sim_time_ns: int = 1000  # for run mode

def _extract_top_module(sv_text: str) -> Optional[str]:
    m = re.search(r"\bmodule\s+([A-Za-z_]\w*)", sv_text or "")
    return m.group(1) if m else None

async def _aiter(stream):
    """Yield each line from an asyncio stream."""
    while True:
        line = await stream.readline()
        if not line:
            break
        yield line

async def _stream_with_timeout(proc, timeout_s: float):
    """Yield (line, elapsed) from proc.stdout until process ends or timeout."""
    import time as _t
    start = _t.time()
    while True:
        remaining = timeout_s - (_t.time() - start)
        if remaining <= 0:
            proc.kill()
            yield (b"__TIMEOUT__", True)
            return
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
        except asyncio.TimeoutError:
            proc.kill()
            yield (b"__TIMEOUT__", True)
            return
        if not line:
            return
        yield (line, False)

async def _write_files_to_dir(file_ids: List[str], project_id: str, work_dir: str) -> List[str]:
    """Fetch RTL/TB files and write them to work_dir. Return list of local paths."""
    written = []
    if not file_ids:
        return written
    fdocs = await db.files.find({"id": {"$in": file_ids}, "project_id": project_id, "is_deleted": {"$ne": True}}, {"_id": 0}).to_list(50)
    for f in fdocs:
        content = _get_file_text(f)
        if not content:
            continue
        local_name = re.sub(r"[^A-Za-z0-9_.\-]", "_", f["original_filename"])
        # Verilator wants .sv / .v extensions
        if not local_name.endswith((".v", ".sv")):
            local_name += ".sv"
        p = os.path.join(work_dir, local_name)
        with open(p, "w") as fh:
            fh.write(content)
        written.append(p)
    return written

@api.post("/simulate/stream")
async def simulate_stream(inp: SimulateIn, user=Depends(get_current_user)):
    proj = await require_project(inp.project_id, user["id"], "editor")

    all_ids = list(inp.rtl_file_ids)
    if inp.tb_file_id and inp.tb_file_id not in all_ids:
        all_ids.append(inp.tb_file_id)
    if not all_ids:
        raise HTTPException(400, "Provide at least one RTL/TB file")

    sim_id = str(uuid.uuid4())
    sim_doc = {
        "id": sim_id,
        "project_id": inp.project_id,
        "user_id": user["id"],
        "engine": "verilator" if VERILATOR_BIN else "mock",
        "file_ids": all_ids,
        "top_module": inp.top_module,
        "status": "streaming",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.simulations.insert_one(sim_doc)

    async def evgen():
        yield f"data: {json.dumps({'type':'meta','simulation_id': sim_id, 'engine': sim_doc['engine']})}\n\n"
        log_lines = []
        def log(line: str, level: str = "info"):
            log_lines.append(line)
            return f"data: {json.dumps({'type':'log','level':level,'line':line})}\n\n"

        if not VERILATOR_BIN:
            # MOCK fallback
            yield log("[mock] Verilator not available in this environment", "warn")
            yield log("[mock] Parsing RTL files ...")
            await asyncio.sleep(0.2)
            fdocs = await db.files.find({"id": {"$in": all_ids}, "project_id": inp.project_id, "is_deleted": {"$ne": True}}, {"_id": 0}).to_list(50)
            for f in fdocs:
                yield log(f"[mock] parsed {f['original_filename']} ({f.get('size',0)} bytes)")
                await asyncio.sleep(0.15)
            yield log("[mock] Elaborating design hierarchy ...")
            await asyncio.sleep(0.3)
            yield log("[mock] Compiling C++ testbench harness ...")
            await asyncio.sleep(0.3)
            yield log("[mock] Running simulation for 1000 ns ...")
            await asyncio.sleep(0.4)
            yield log("[mock] Simulation complete. 0 errors, 0 warnings.", "success")
            status = "done"
        else:
            with tempfile.TemporaryDirectory(prefix="chipsutra_sim_") as tmp:
                try:
                    yield log(f"[verilator] work dir: {tmp}")
                    written = await _write_files_to_dir(all_ids, inp.project_id, tmp)
                    if not written:
                        yield log("[verilator] no readable RTL files", "error")
                        status = "error"
                    else:
                        for p in written:
                            yield log(f"[verilator] source: {os.path.basename(p)}")

                        top = inp.top_module
                        if not top:
                            # try TB first
                            probe = None
                            if inp.tb_file_id:
                                for p in written:
                                    if inp.tb_file_id in p:
                                        probe = p; break
                            probe = probe or written[-1]
                            with open(probe) as fh:
                                top = _extract_top_module(fh.read())
                        if not top:
                            yield log("[verilator] could not detect top module. Pass top_module explicitly.", "error")
                            status = "error"
                        else:
                            yield log(f"[verilator] top module: {top}")
                            vcd_path = None
                            if inp.mode == "run":
                                # Compile + run: needs a testbench with $dumpfile/$dumpvars or auto-inject a main
                                # We will inject a C++ main and let $dumpfile/$dumpvars trigger VCD, else fall back to lint
                                exe_name = f"V{top}"
                                cmd = [VERILATOR_BIN, "--cc", "--exe", "--build",
                                       "-Wno-fatal", "--trace", "--timing",
                                       "--top-module", top,
                                       "--Mdir", "obj_dir"] + [os.path.basename(p) for p in written]
                                # Provide a minimal main if testbench has no $finish — we still need main.cpp
                                main_cpp = os.path.join(tmp, "sim_main.cpp")
                                with open(main_cpp, "w") as fh:
                                    fh.write(f"""
#include <verilated.h>
#include <verilated_vcd_c.h>
#include "V{top}.h"
int main(int argc, char** argv) {{
    Verilated::commandArgs(argc, argv);
    V{top}* top = new V{top};
    Verilated::traceEverOn(true);
    VerilatedVcdC* tfp = new VerilatedVcdC;
    top->trace(tfp, 99);
    tfp->open("dump.vcd");
    vluint64_t t = 0;
    while (t < {max(50, inp.sim_time_ns)} && !Verilated::gotFinish()) {{
        top->eval();
        tfp->dump(t);
        t++;
    }}
    tfp->close();
    delete top;
    return 0;
}}
""")
                                cmd.append(os.path.basename(main_cpp))
                                yield log(f"$ {' '.join(cmd)}")
                                try:
                                    proc = await asyncio.create_subprocess_exec(
                                        *cmd, cwd=tmp,
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.STDOUT,
                                    )
                                    assert proc.stdout is not None
                                    timed_out = False
                                    async for raw, is_timeout in _stream_with_timeout(proc, 60.0):
                                        if is_timeout:
                                            timed_out = True
                                            yield log("[verilator] compile timed out after 60s", "error")
                                            break
                                        line = raw.decode("utf-8", errors="ignore").rstrip()
                                        if not line: continue
                                        lvl = "error" if "%Error" in line or "error:" in line.lower() else ("warn" if "%Warning" in line or "warning:" in line.lower() else "info")
                                        yield log(line, lvl)
                                    rc = await proc.wait()
                                    if rc == 0 and not timed_out:
                                        # Run the built executable
                                        exe_path = os.path.join(tmp, "obj_dir", exe_name)
                                        if os.path.exists(exe_path):
                                            yield log(f"$ ./obj_dir/{exe_name}")
                                            rp = await asyncio.create_subprocess_exec(exe_path, cwd=tmp,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                                            assert rp.stdout is not None
                                            async for raw, is_timeout in _stream_with_timeout(rp, 30.0):
                                                if is_timeout:
                                                    yield log("[verilator] runtime exceeded 30s", "error")
                                                    break
                                                line = raw.decode("utf-8", errors="ignore").rstrip()
                                                if not line: continue
                                                yield log(line, "info")
                                            _ = await rp.wait()
                                            vcd_file = os.path.join(tmp, "dump.vcd")
                                            if os.path.exists(vcd_file) and os.path.getsize(vcd_file) > 0:
                                                # Store VCD as a file in the project
                                                with open(vcd_file, "rb") as fh:
                                                    vcd_bytes = fh.read()
                                                new_fid = str(uuid.uuid4())
                                                vcd_name = f"sim_{top}_{sim_id[:8]}.vcd"
                                                storage_path = None
                                                try:
                                                    r = put_object(f"{APP_NAME}/projects/{inp.project_id}/{new_fid}.vcd", vcd_bytes, "text/plain")
                                                    storage_path = r["path"]
                                                except Exception:
                                                    pass
                                                await db.files.insert_one({
                                                    "id": new_fid,
                                                    "project_id": inp.project_id,
                                                    "original_filename": vcd_name,
                                                    "ext": "vcd",
                                                    "kind": "vcd",
                                                    "size": len(vcd_bytes),
                                                    "content_type": "text/plain",
                                                    "storage_path": storage_path,
                                                    "inline_content": vcd_bytes.decode("utf-8", errors="ignore") if storage_path is None else None,
                                                    "is_deleted": False,
                                                    "created_at": datetime.now(timezone.utc).isoformat(),
                                                })
                                                vcd_path = new_fid
                                                yield log(f"[verilator] ✓ simulation complete. VCD saved as {vcd_name}", "success")
                                            else:
                                                yield log("[verilator] simulation ran but no VCD was produced (add $dumpfile/$dumpvars in TB)", "warn")
                                            status = "done"
                                        else:
                                            yield log("[verilator] executable not found after build", "error")
                                            status = "error"
                                    else:
                                        yield log(f"[verilator] build failed with exit code {rc}", "error")
                                        status = "error"
                                except Exception as e:
                                    yield log(f"[verilator] execution error: {e}", "error")
                                    status = "error"
                            else:
                                # Lint-only mode
                                cmd = [VERILATOR_BIN, "--lint-only", "-Wno-fatal", "--top-module", top] + [os.path.basename(p) for p in written]
                                yield log(f"$ {' '.join(cmd)}")
                                try:
                                    proc = await asyncio.create_subprocess_exec(
                                        *cmd, cwd=tmp,
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.STDOUT,
                                    )
                                    assert proc.stdout is not None
                                    async for raw in proc.stdout:
                                        line = raw.decode("utf-8", errors="ignore").rstrip()
                                        if not line: continue
                                        lvl = "error" if "%Error" in line else ("warn" if "%Warning" in line else "info")
                                        yield log(line, lvl)
                                    rc = await proc.wait()
                                    if rc == 0:
                                        yield log("[verilator] ✓ lint passed. Design is well-formed.", "success")
                                        status = "done"
                                    else:
                                        yield log(f"[verilator] finished with exit code {rc}", "error")
                                        status = "error"
                                except Exception as e:
                                    yield log(f"[verilator] execution error: {e}", "error")
                                    status = "error"
                except Exception as e:
                    yield log(f"[verilator] fatal: {e}", "error")
                    status = "error"

        await db.simulations.update_one({"id": sim_id}, {"$set": {"status": status, "log": "\n".join(log_lines), "vcd_file_id": (locals().get('vcd_path')), "mode": inp.mode, "completed_at": datetime.now(timezone.utc).isoformat()}})
        yield f"data: {json.dumps({'type': 'done', 'status': status, 'simulation_id': sim_id, 'vcd_file_id': locals().get('vcd_path')})}\n\n"

    return StreamingResponse(evgen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@api.get("/projects/{pid}/simulations")
async def list_simulations(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    docs = await db.simulations.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return docs

# =========================
# Chiplet Templates (UCIe/BoW)
# =========================
CHIPLET_TEMPLATES = [
    {
        "id": "ucie-basic",
        "name": "UCIe Basic Interconnect",
        "category": "UCIe",
        "description": "Universal Chiplet Interconnect Express — physical + link layer verification skeleton with lane-repair, sideband, and mainband checkers.",
        "tags": ["UCIe", "Chiplet", "Interconnect", "Physical Layer"],
        "modules": ["testbench", "assertions", "covergroups"],
        "prompt_seed": "Generate a UCIe 1.0 verification testbench for the mainband and sideband channels. Cover: lane repair, sideband init sequence, retimer/redriver modes, error injection on FLIT boundaries, and CRC checks. Include SVA for protocol correctness."
    },
    {
        "id": "ucie-flit",
        "name": "UCIe FLIT Layer",
        "category": "UCIe",
        "description": "FLIT-level protocol verification: 64B/256B FLIT formatting, CRC, retry buffers, and credit-based flow control.",
        "tags": ["UCIe", "FLIT", "Flow Control"],
        "modules": ["testbench", "assertions", "coverage_holes"],
        "prompt_seed": "Generate verification for UCIe FLIT layer including 64B and 256B FLIT modes, CRC validation, retry buffer overflow tests, and credit-based flow control assertions."
    },
    {
        "id": "bow-basic",
        "name": "BoW Interconnect",
        "category": "BoW",
        "description": "Bunch-of-Wires die-to-die interconnect: single-ended parallel bus with source-synchronous clocking. Includes eye monitor and skew checks.",
        "tags": ["BoW", "OCP", "Die-to-Die", "SerDes"],
        "modules": ["testbench", "assertions", "covergroups"],
        "prompt_seed": "Generate a BoW (Bunch of Wires) verification environment for a 16-bit slice. Include source-synchronous clock, eye monitor, skew tolerance tests, and per-wire error injection."
    },
    {
        "id": "chiplet-power",
        "name": "Chiplet Power Domain",
        "category": "Chiplet",
        "description": "Multi-chiplet power sequencing, isolation cells and level shifters verification.",
        "tags": ["Power", "UPF", "Isolation", "Multi-Chiplet"],
        "modules": ["testbench", "assertions", "checkers"],
        "prompt_seed": "Generate assertions and checkers for chiplet power sequencing: verify isolation cell activation ordering, level shifter enable, and retention sequencing across sleep/wake transitions."
    },
    {
        "id": "chiplet-security",
        "name": "Chiplet Root-of-Trust",
        "category": "Chiplet",
        "description": "Cross-chiplet root-of-trust attestation and secure boot verification patterns.",
        "tags": ["Security", "Root-of-Trust", "Secure Boot"],
        "modules": ["testbench", "assertions", "checkers"],
        "prompt_seed": "Generate a verification environment for cross-chiplet root-of-trust attestation: challenge-response flow, secure boot chain-of-trust, and side-channel resistance checks."
    },
    {
        "id": "axi4-ip",
        "name": "AXI4 IP Block",
        "category": "IP",
        "description": "AMBA AXI4 master/slave IP verification with burst types, out-of-order responses, and QoS.",
        "tags": ["AXI4", "AMBA", "IP"],
        "modules": ["testbench", "assertions", "covergroups"],
        "prompt_seed": "Generate a UVM testbench for an AXI4 slave with support for INCR/WRAP bursts, out-of-order response IDs, and QoS-based arbitration. Include cover groups for burst types × QoS × response codes."
    },
]

@api.get("/templates")
async def list_templates():
    return CHIPLET_TEMPLATES

@api.get("/templates/{tid}")
async def get_template(tid: str):
    for t in CHIPLET_TEMPLATES:
        if t["id"] == tid:
            return t
    raise HTTPException(404, "Template not found")

# =========================
# Google OAuth (Emergent-managed OR standalone)
# =========================
class GoogleSessionIn(BaseModel):
    session_id: str

@api.post("/auth/google/session")
async def google_session(inp: GoogleSessionIn, request: Request):
    """Emergent-managed Google auth: exchange session_id from hash callback for JWT."""
    if google_mode() != "emergent":
        raise HTTPException(400, "Emergent Google Auth is not enabled on this deployment. Use /auth/google/url instead.")
    # Rate limit: 20 attempts per IP per 5 minutes (honor X-Forwarded-For behind ingress)
    xff = request.headers.get("x-forwarded-for", "")
    client_ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")
    _rate_limit(f"gauth:{client_ip}", max_calls=20, window_s=300)
    try:
        userinfo = resolve_emergent_session(inp.session_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(401, f"Google auth failed: {e}")
    return await _issue_google_user_token(userinfo)

@api.get("/auth/google/url")
async def google_auth_url(request: Request):
    """Standalone Google OAuth: returns the URL the frontend should redirect to."""
    if google_mode() != "standalone":
        raise HTTPException(400, "Standalone Google OAuth is not configured. Set GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI.")
    return {"url": build_google_auth_url()}

@api.get("/auth/google/callback")
async def google_auth_callback(code: str = Query(...), state: Optional[str] = Query(None), request: Request = None):
    """Standalone Google OAuth: Google redirects here with ?code=... — we exchange, issue JWT, redirect to app."""
    if google_mode() != "standalone":
        raise HTTPException(400, "Standalone Google OAuth is not configured.")
    xff = request.headers.get("x-forwarded-for", "") if request else ""
    client_ip = xff.split(",")[0].strip() if xff else "unknown"
    _rate_limit(f"gauth:{client_ip}", max_calls=20, window_s=300)
    try:
        userinfo = google_exchange_code(code)
    except Exception as e:
        raise HTTPException(401, f"Google exchange failed: {e}")
    result = await _issue_google_user_token(userinfo)
    # Redirect back to frontend with token in hash
    frontend_root = os.environ.get("FRONTEND_URL", "").rstrip("/")
    if frontend_root:
        return RedirectResponse(url=f"{frontend_root}/#gtoken={result['access_token']}")
    # Fallback: return JSON if FRONTEND_URL is not set
    return result

async def _issue_google_user_token(userinfo: dict) -> dict:
    email = (userinfo.get("email") or "").lower()
    name = userinfo.get("name") or email.split("@")[0]
    picture = userinfo.get("picture")
    if not email:
        raise HTTPException(400, "Google returned no email")
    user = await db.users.find_one({"email": email})
    if not user:
        user_id = str(uuid.uuid4())
        await db.users.insert_one({
            "id": user_id, "email": email, "name": name, "role": "user",
            "picture": picture, "auth_provider": "google",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        user_id = user["id"]
        if picture and user.get("picture") != picture:
            await db.users.update_one({"id": user_id}, {"$set": {"picture": picture, "name": name}})
    token = create_access_token(user_id, email)
    return {"access_token": token, "user": {"id": user_id, "email": email, "name": name, "role": "user", "picture": picture}}

# =========================
# Users search (for invites)
# =========================
@api.get("/users/lookup")
async def lookup_user(email: str = Query(...), user=Depends(get_current_user)):
    doc = await db.users.find_one({"email": email.lower()}, {"_id": 0, "password_hash": 0})
    if not doc:
        return {"found": False}
    return {"found": True, "id": doc["id"], "email": doc["email"], "name": doc.get("name")}

# =========================
# Notifications + Activity helpers
# =========================
async def create_notification(user_id: str, kind: str, title: str, body: str = "", link: str = "", meta: dict = None):
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "kind": kind,
        "title": title,
        "body": body,
        "link": link,
        "meta": meta or {},
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.notifications.insert_one(doc)
    return doc

async def log_activity(workspace_id: Optional[str], actor_id: str, actor_name: str, action: str,
                       target_type: str = "", target_id: str = "", target_name: str = "", meta: dict = None):
    if not workspace_id:
        return
    doc = {
        "id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "target_name": target_name,
        "meta": meta or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.activity.insert_one(doc)

@api.get("/notifications")
async def list_notifications(user=Depends(get_current_user), unread_only: bool = False):
    q = {"user_id": user["id"]}
    if unread_only:
        q["read"] = False
    docs = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    unread = await db.notifications.count_documents({"user_id": user["id"], "read": False})
    return {"items": docs, "unread": unread}

@api.post("/notifications/{nid}/read")
async def mark_notif_read(nid: str, user=Depends(get_current_user)):
    await db.notifications.update_one({"id": nid, "user_id": user["id"]}, {"$set": {"read": True}})
    return {"ok": True}

@api.post("/notifications/read-all")
async def mark_all_read(user=Depends(get_current_user)):
    await db.notifications.update_many({"user_id": user["id"], "read": False}, {"$set": {"read": True}})
    return {"ok": True}

# =========================
# Workspaces (Orgs)
# =========================
class WorkspaceIn(BaseModel):
    name: str
    description: Optional[str] = ""

from typing import Literal
class WorkspaceMemberIn(BaseModel):
    email: EmailStr
    role: Literal["admin", "member"] = "member"

async def get_workspace_role(ws_id: str, user_id: str) -> Optional[str]:
    ws = await db.workspaces.find_one({"id": ws_id}, {"_id": 0})
    if not ws:
        return None
    if ws.get("owner_id") == user_id:
        return "owner"
    for m in ws.get("members", []):
        if m.get("user_id") == user_id:
            return m.get("role", "member")
    return None

async def require_workspace(ws_id: str, user_id: str, min_role: str = "member") -> dict:
    role = await get_workspace_role(ws_id, user_id)
    if role is None:
        raise HTTPException(404, "Workspace not found")
    order = {"member": 0, "admin": 1, "owner": 2}
    if order[role] < order[min_role]:
        raise HTTPException(403, "Insufficient workspace role")
    ws = await db.workspaces.find_one({"id": ws_id}, {"_id": 0})
    ws["current_role"] = role
    return ws

@api.post("/workspaces")
async def create_workspace(inp: WorkspaceIn, user=Depends(get_current_user)):
    wid = str(uuid.uuid4())
    doc = {
        "id": wid,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "name": inp.name,
        "description": inp.description or "",
        "members": [],
        "seat_limit": 5,  # billing seat concept — Free tier default
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.workspaces.insert_one(doc)
    await log_activity(wid, user["id"], user.get("name") or user["email"], "workspace_created", "workspace", wid, inp.name)
    doc.pop("_id", None)
    return doc

@api.get("/workspaces")
async def list_workspaces(user=Depends(get_current_user)):
    docs = await db.workspaces.find(
        {"$or": [{"owner_id": user["id"]}, {"members.user_id": user["id"]}]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    for d in docs:
        d["is_owner"] = d.get("owner_id") == user["id"]
        d["project_count"] = await db.projects.count_documents({"workspace_id": d["id"]})
    return docs

@api.get("/workspaces/{wid}")
async def get_workspace(wid: str, user=Depends(get_current_user)):
    ws = await require_workspace(wid, user["id"], "member")
    ws["project_count"] = await db.projects.count_documents({"workspace_id": wid})
    return ws

@api.post("/workspaces/{wid}/members")
async def add_workspace_member(wid: str, inp: WorkspaceMemberIn, user=Depends(get_current_user)):
    ws = await require_workspace(wid, user["id"], "admin")
    if len(ws.get("members", [])) + 1 > ws.get("seat_limit", 5):
        raise HTTPException(400, f"Seat limit reached ({ws.get('seat_limit', 5)}). Upgrade to add more seats.")
    email = inp.email.lower()
    invited = await db.users.find_one({"email": email})
    if not invited:
        raise HTTPException(404, "No ChipSutra user with that email")
    if invited["id"] == ws["owner_id"]:
        raise HTTPException(400, "This user is already the owner")
    for m in ws.get("members", []):
        if m.get("user_id") == invited["id"]:
            raise HTTPException(400, "Already a member")
    entry = {
        "user_id": invited["id"],
        "email": email,
        "name": invited.get("name"),
        "role": inp.role if inp.role in ("admin", "member") else "member",
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.workspaces.update_one({"id": wid}, {"$push": {"members": entry}})
    await create_notification(invited["id"], "workspace_invite",
                              f"Added to workspace '{ws['name']}'",
                              f"{user.get('name') or user['email']} invited you as {entry['role']}.",
                              "/app/workspaces", {"workspace_id": wid})
    await log_activity(wid, user["id"], user.get("name") or user["email"], "member_added",
                       "workspace", wid, ws["name"], {"invited_email": email, "role": entry["role"]})
    return entry

@api.delete("/workspaces/{wid}/members/{uid}")
async def remove_workspace_member(wid: str, uid: str, user=Depends(get_current_user)):
    ws = await require_workspace(wid, user["id"], "admin")
    await db.workspaces.update_one({"id": wid}, {"$pull": {"members": {"user_id": uid}}})
    await log_activity(wid, user["id"], user.get("name") or user["email"], "member_removed",
                       "workspace", wid, ws["name"], {"user_id": uid})
    return {"ok": True}

@api.delete("/workspaces/{wid}")
async def delete_workspace(wid: str, user=Depends(get_current_user)):
    ws = await db.workspaces.find_one({"id": wid, "owner_id": user["id"]})
    if not ws:
        raise HTTPException(404, "Workspace not found or you are not the owner")
    # Unlink projects (don't cascade-delete)
    await db.projects.update_many({"workspace_id": wid}, {"$set": {"workspace_id": None}})
    await db.workspaces.delete_one({"id": wid})
    await db.activity.delete_many({"workspace_id": wid})
    return {"ok": True}

@api.get("/workspaces/{wid}/activity")
async def workspace_activity(wid: str, user=Depends(get_current_user)):
    await require_workspace(wid, user["id"], "member")
    docs = await db.activity.find({"workspace_id": wid}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return docs

@api.get("/workspaces/{wid}/projects")
async def workspace_projects(wid: str, user=Depends(get_current_user)):
    await require_workspace(wid, user["id"], "member")
    docs = await db.projects.find({"workspace_id": wid}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

# =========================
# Rate limiting (in-memory)
# =========================
_rate_buckets: dict[str, list[float]] = {}
def _rate_limit(key: str, max_calls: int = 10, window_s: float = 60.0):
    import time as _t
    now = _t.time()
    buf = _rate_buckets.setdefault(key, [])
    # Purge old
    while buf and buf[0] < now - window_s:
        buf.pop(0)
    if len(buf) >= max_calls:
        raise HTTPException(429, "Too many requests. Try again in a moment.")
    buf.append(now)

# =========================
# Include router
# =========================
# ---- Formal Verification (SymbiYosys) ----
SBY_BIN = shutil.which("sby")

class FormalIn(BaseModel):
    project_id: str
    rtl_file_ids: List[str] = []
    top_module: Optional[str] = None
    depth: int = 10
    mode: str = "prove"  # prove | bmc

@api.post("/formal/stream")
async def formal_stream(inp: FormalIn, user=Depends(get_current_user)):
    await require_project(inp.project_id, user["id"], "editor")
    if not inp.rtl_file_ids:
        raise HTTPException(400, "Provide at least one RTL file with assertions")

    fdocs = await db.files.find({"id": {"$in": inp.rtl_file_ids}, "project_id": inp.project_id, "is_deleted": {"$ne": True}}, {"_id": 0}).to_list(50)
    if not fdocs:
        raise HTTPException(400, "No readable RTL files")

    formal_id = str(uuid.uuid4())
    await db.formal_runs.insert_one({
        "id": formal_id, "project_id": inp.project_id, "user_id": user["id"],
        "engine": "sby" if SBY_BIN else "mock",
        "status": "streaming", "mode": inp.mode, "depth": inp.depth,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    async def evgen():
        yield f"data: {json.dumps({'type': 'meta', 'formal_id': formal_id, 'engine': 'sby' if SBY_BIN else 'mock'})}\n\n"
        logs = []
        def log(line: str, lvl: str = "info"):
            logs.append(line)
            return f"data: {json.dumps({'type':'log','level':lvl,'line':line})}\n\n"

        if not SBY_BIN:
            yield log("[mock] SymbiYosys not available — running LLM-only formal hint mode", "warn")
            yield log("[mock] Parsing assertions ...")
            await asyncio.sleep(0.3)
            for f in fdocs:
                yield log(f"[mock] scanning {f['original_filename']} for `assert`/`assume`/`cover` properties")
                await asyncio.sleep(0.2)
            yield log("[mock] No SAT solver invoked. Use the LLM Formal Suggestions module for property drafts.", "info")
            status = "done"
        else:
            with tempfile.TemporaryDirectory(prefix="chipsutra_formal_") as tmp:
                try:
                    written = []
                    for f in fdocs:
                        text = _get_file_text(f)
                        if not text: continue
                        local = re.sub(r"[^A-Za-z0-9_.\-]", "_", f["original_filename"])
                        if not local.endswith((".v", ".sv")): local += ".sv"
                        p = os.path.join(tmp, local)
                        with open(p, "w") as fh: fh.write(text)
                        written.append(p)
                    top = inp.top_module or _extract_top_module(open(written[0]).read())
                    if not top:
                        yield log("[sby] top module not detected", "error")
                        status = "error"
                    else:
                        yield log(f"[sby] top module: {top}")
                        sby_file = os.path.join(tmp, "chipsutra.sby")
                        with open(sby_file, "w") as fh:
                            fh.write(f"""[options]
mode {inp.mode}
depth {min(max(inp.depth, 1), 30)}

[engines]
smtbmc z3

[script]
read -formal -DFORMAL {' '.join(os.path.basename(p) for p in written)}
prep -top {top}

[files]
{chr(10).join(os.path.basename(p) for p in written)}
""")
                        cmd = [SBY_BIN, "-f", "chipsutra.sby"]
                        yield log(f"$ {' '.join(cmd)}")
                        try:
                            proc = await asyncio.create_subprocess_exec(*cmd, cwd=tmp,
                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                            assert proc.stdout is not None
                            saw_prep_error = False
                            async for raw, is_timeout in _stream_with_timeout(proc, 45.0):
                                if is_timeout:
                                    yield log("[sby] timed out after 45s", "error"); break
                                line = raw.decode("utf-8", errors="ignore").rstrip()
                                if not line: continue
                                if "formalff" in line or "prep: ERROR" in line:
                                    saw_prep_error = True
                                lvl = "error" if "FAIL" in line or "ERROR" in line else ("success" if "PASS" in line else "info")
                                yield log(line, lvl)
                            rc = await proc.wait()
                            status = "done" if rc == 0 else "error"
                            if rc == 0:
                                yield log("[sby] ✓ formal verification passed", "success")
                            elif saw_prep_error:
                                yield log("[sby] NOTE: This environment ships Yosys 0.23 which is incompatible with the latest SBY 'formalff' pass. Full formal proofs need Yosys ≥ 0.35 built from source. For now, use the AI 'Formal Hints' module to draft SVA properties.", "warn")
                            else:
                                yield log(f"[sby] returned {rc} — see log for details.", "error")
                        except Exception as e:
                            yield log(f"[sby] error: {e}", "error"); status = "error"
                except Exception as e:
                    yield log(f"[sby] fatal: {e}", "error"); status = "error"

        await db.formal_runs.update_one({"id": formal_id}, {"$set": {"status": status, "log": "\n".join(logs), "completed_at": datetime.now(timezone.utc).isoformat()}})
        yield f"data: {json.dumps({'type':'done','status': status, 'formal_id': formal_id})}\n\n"

    return StreamingResponse(evgen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# Add a new AI module: formal_hints (LLM)
MODULE_PROMPTS["formal_hints"] = "You are a formal-verification expert. Given the RTL below, generate 8–12 SVA-style formal properties suitable for SymbiYosys / JasperGold: mix of `assert property`, `assume property`, and `cover property`. Include a short comment for each explaining the intent and expected proof depth. Output only SystemVerilog code."

# ---- GitHub Actions CI ----
@api.get("/ci/github-workflow")
async def ci_github_workflow():
    """Return a downloadable GitHub Actions workflow YAML for ChipSutra."""
    yaml = """name: ChipSutra Verification
on:
  pull_request:
    paths: ['**/*.v', '**/*.sv', '**/*.vhd', '**/*.md']
  workflow_dispatch:

jobs:
  chipsutra-verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Verilator
        run: sudo apt-get update && sudo apt-get install -y verilator
      - name: Lint RTL with Verilator
        run: |
          for f in $(git diff --name-only origin/main...HEAD | grep -E '\\.(v|sv)$'); do
            echo "Linting $f"
            verilator --lint-only -Wno-fatal "$f" || exit 1
          done
      - name: Trigger ChipSutra AI review (optional)
        if: env.CHIPSUTRA_TOKEN != ''
        env:
          CHIPSUTRA_TOKEN: ${{ secrets.CHIPSUTRA_TOKEN }}
        run: |
          curl -X POST https://chipsutra.ai/api/ci/webhook \\
            -H "Authorization: Bearer $CHIPSUTRA_TOKEN" \\
            -H "Content-Type: application/json" \\
            -d '{"repo":"'${{ github.repository }}'","pr":"'${{ github.event.number }}'","sha":"'${{ github.sha }}'"}'
"""
    return Response(content=yaml, media_type="text/yaml", headers={"Content-Disposition": "attachment; filename=chipsutra.yml"})

class CIWebhookIn(BaseModel):
    repo: str
    pr: Optional[str] = None
    sha: Optional[str] = None
    event: Optional[str] = "pull_request"

@api.post("/ci/webhook")
async def ci_webhook(inp: CIWebhookIn, user=Depends(get_current_user)):
    """Placeholder GitHub CI webhook. Persists the event; future: kick off AI review."""
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "repo": inp.repo,
        "pr": inp.pr,
        "sha": inp.sha,
        "event": inp.event,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.ci_events.insert_one(doc)
    return {"ok": True, "event_id": doc["id"], "message": "Event queued. AI review will run when webhook worker ships."}

@api.get("/ci/events")
async def list_ci_events(user=Depends(get_current_user)):
    docs = await db.ci_events.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    return docs

# ---- Include router ----
app.include_router(api)
