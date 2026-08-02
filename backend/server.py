from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import re
import sys
import uuid
import json
import logging
import asyncio
import io
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any

import bcrypt
import jwt
import certifi
import requests
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, UploadFile, File, Form, Query, Request
from fastapi.responses import StreamingResponse, Response, RedirectResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field

# ChipSutra provider abstractions (auto-fall-back Emergent → standalone)
from llm_provider import stream_chat as llm_stream_chat, available_providers as llm_available_providers, ollama_status as llm_ollama_status
from rag import augment_generation_context, rag_status as llm_rag_status
from rtl_ports import extract_port_context_from_texts, rtl_ports_status, extract_modules
from generation_rules import (
    rules_for_module,
    default_user_prompt,
    num_predict_for_module,
    tb_golden_hint_from_ports,
)
from lint_feedback import format_lint_feedback, lint_feedback_status
from coverage_parse import parse_text_report, summarize_coverage_dat, trend_points
from coverage_merge import merge_summary_points
from coverage_loop import rank_holes, build_closure_prompt, suggest_resim_plan, closure_status
from formal_parse import parse_sby_log, find_cex_vcds
from cdc import analyze_rtl_texts
from cdc_netlist import analyze_yosys_json, merge_cdc_results
from cdc_deep import analyze_deep, merge_deep
from fst_parse import ensure_vcd, fst_status, sniff_waveform_format
import ucis_parse
from eda_tools import build_manifest, sha256_paths, tool_versions
from lint_policy import parse_policy, parse_verilator_findings, apply_lint_policy
from yosys_flow import (
    synth_script,
    equiv_script,
    eqy_config,
    parse_yosys_log,
    parse_eqy_log,
    fallback_equiv_note,
)
from cocotb_scaffold import render_cocotb_scaffold
from cocotb_runner import cocotb_available, pick_scaffold_files, build_make_cmd, parse_cocotb_log
from tb_skeleton import should_use_tb_skeleton, render_randomized_tb
from tb_lint import choose_testbench_output, lint_testbench, extract_sv
from kg_rating import auto_score_testbench, combine_with_feedback, aggregate_learning_report
from dv_planner import plan_generation, plan_to_learning
from dv_verify import verify_testbench, verify_status_for_learning, verilator_bin
from llm_router import resolve_model, prewarm_ollama, prewarm_status
from spec_checklist import analyze_spec, checklist_prompt_block
from debug_classify import classify_log, debug_prompt_block
from opensta_flow import (
    sta_bin,
    sta_command,
    build_sta_tcl,
    liberty_is_plausible,
    parse_sta_log,
    default_sdc_stub,
)
from rate_limit import enforce_rate_limit, rate_limit_status
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
def _motor_client(url: str) -> AsyncIOMotorClient:
    """Atlas (mongodb+srv) on Windows needs explicit CA bundle (certifi)."""
    kwargs: dict = {}
    if url.startswith("mongodb+srv://") or "tls=true" in url.lower():
        kwargs["tlsCAFile"] = certifi.where()
    return AsyncIOMotorClient(url, **kwargs)


def _public_ipv4_for_atlas_hint() -> str:
    try:
        r = requests.get("https://api.ipify.org", timeout=4)
        if r.ok and r.text.strip():
            return (
                f" Your public IPv4 right now: {r.text.strip()}/32."
                " For a multi-user online product (or home/ISP IP that changes), set Network Access to"
                " Allow Access from Anywhere: 0.0.0.0/0 — end users hit ChipSutra API, only the API talks to Atlas."
            )
    except Exception:
        pass
    return (
        " Check https://api.ipify.org for your IPv4."
        " Multi-user / dynamic IP: Atlas Network Access → 0.0.0.0/0."
    )


def _atlas_tls_hint(err_s: str = "") -> str:
    py = sys.version.split()[0]
    return (
        " Atlas is rejecting the TLS handshake (almost always Network Access — IP not allowed),"
        " not a bad password or missing certifi."
        " Fix: https://cloud.mongodb.com/ → Network Access → Add IP Address →"
        " Allow Access from Anywhere (0.0.0.0/0)."
        " Wait 1–2 minutes after saving."
        + _public_ipv4_for_atlas_hint()
        + " Turn off VPN. Atlas whitelist is IPv4 — do not add only an IPv6 address."
        f" Python {py}. Diagnose: python scripts/test_mongo_connect.py"
    )


async def _ping_mongo_with_retries() -> None:
    """Retry Atlas ping so whitelist propagation / brief blips do not crash-loop immediately."""
    attempts = max(1, int(os.environ.get("MONGO_STARTUP_RETRIES", "8")))
    delay = float(os.environ.get("MONGO_STARTUP_RETRY_SEC", "5"))
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            await asyncio.wait_for(client.admin.command("ping"), timeout=12.0)
            if i > 1:
                logger.info("MongoDB ping OK on attempt %d/%d", i, attempts)
            return
        except Exception as e:
            last = e
            logger.warning(
                "MongoDB ping failed (%d/%d): %s",
                i,
                attempts,
                str(e)[:180],
            )
            if i < attempts:
                await asyncio.sleep(delay)
    assert last is not None
    raise last


client = _motor_client(MONGO_URL)
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
    model_provider: str = "ollama"
    model_name: str = "chipsutra-vlsi:3b"
    prompt: Optional[str] = ""
    file_ids: Optional[List[str]] = []
    language: Optional[str] = "systemverilog"
    # Closed-loop: paste Verilator/sim log (+ optional prior code) to regenerate/fix
    tool_log: Optional[str] = None
    prior_output: Optional[str] = None
    # testbench path: auto (skeleton-first) | skeleton | llm
    gen_mode: Optional[str] = "auto"

MODULE_PROMPTS = {
    "testbench": (
        "You are an expert VLSI verification engineer. Generate a **compact Verilator-friendly** "
        "SystemVerilog testbench for the provided RTL in {language} (pure SV by default; "
        "full UVM only if the user explicitly requests UVM). "
        "Use **randomized stimulus** ($urandom_range) + a golden reference in ONE loop — "
        "do not hardcode long directed testcase lists. "
        "Must: exact DUT port map; $dumpfile/$dumpvars; $finish. "
        "Never invent ports. Output ONLY SystemVerilog (~50–70 lines)."
    ),
    "assertions": (
        "You are an expert in SystemVerilog Assertions (SVA). Generate comprehensive assertions "
        "for the provided RTL in {language}. Cover: protocol correctness, safety properties, "
        "liveness, and edge cases using ONLY real DUT ports. Output only SVA code with brief comments."
    ),
    "checkers": (
        "You are an expert verification engineer. Generate reusable checker / reference-model "
        "modules for the provided RTL in {language} using ONLY real DUT ports and behavior. "
        "Output only code."
    ),
    "covergroups": (
        "You are a coverage expert. Generate covergroups in {language} for the provided RTL. "
        "Include bins/crosses matching real ports and DUT behavior. Output only code."
    ),
    "spec2rtl": "You are an expert RTL designer. Given the specification below, generate synthesizable RTL code in {language}. Output only code with brief comments.",
    "rtl2spec": "You are a technical writer + verification expert. Given the RTL below, produce a detailed specification document in Markdown covering: overview, interface signals, functional behavior, timing, corner cases, and verification hints.",
    "testplan": "You are a verification lead. Given the RTL/spec below, produce a comprehensive testplan in Markdown covering: features, scenarios, corner cases, coverage goals, and assertion goals. Structure with sections and tables.",
    "coverage_holes": "You are a coverage closure expert. Given the coverage report / RTL below, identify coverage holes and generate additional {language} tests / sequences to close them. Output actionable test code and short rationale for each.",
    "debug": "You are a hardware debug expert. Analyze the simulation log / failure report below and provide root-cause hypotheses ranked by likelihood, with next debug steps. Output as Markdown."
}

# =========================
# Startup
# =========================
def _guard_python_for_atlas() -> None:
    """Windows + Python 3.14+ often breaks Atlas TLS; require 3.11/3.12 venv."""
    if "mongodb.net" not in MONGO_URL and not MONGO_URL.startswith("mongodb+srv://"):
        return
    if sys.platform != "win32":
        return
    if sys.version_info >= (3, 14):
        venv_py = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
        raise RuntimeError(
            f"MongoDB Atlas on Windows needs Python 3.11 or 3.12 (you are on {sys.version.split()[0]}). "
            "Do not use the default `python` on PATH. Run:\n"
            f"  cd {ROOT_DIR}\n"
            "  py -3.12 -m venv .venv\n"
            "  .\\.venv\\Scripts\\Activate.ps1\n"
            "  pip install -r requirements-oss.txt\n"
            "  python -m uvicorn server:app --host 0.0.0.0 --port 8001\n"
            "Or: .\\run-backend.ps1\n"
            + (f"(venv exists: {venv_py})" if venv_py.is_file() else "")
        )


@app.on_event("startup")
async def startup():
    _guard_python_for_atlas()
    try:
        await _ping_mongo_with_retries()
    except Exception as e:
        hint = ""
        err_s = str(e)
        if "localhost" in MONGO_URL or "127.0.0.1" in MONGO_URL:
            hint = (
                " In Docker, localhost is the container — use MongoDB Atlas "
                "(mongodb+srv://...) in backend/.env, not mongodb://localhost:27017."
            )
        elif "SSL" in err_s or "TLS" in err_s or "tlsv1" in err_s.lower() or "ServerSelection" in type(e).__name__:
            hint = _atlas_tls_hint(err_s)
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
    await db.coverage_runs.create_index([("project_id", 1), ("created_at", -1)])
    await db.formal_runs.create_index([("project_id", 1), ("created_at", -1)])
    await db.cdc_runs.create_index([("project_id", 1), ("created_at", -1)])
    await db.simulations.create_index([("project_id", 1), ("created_at", -1)])
    await db.regressions.create_index([("project_id", 1), ("created_at", -1)])
    await db.synth_runs.create_index([("project_id", 1), ("created_at", -1)])
    await db.cocotb_runs.create_index([("project_id", 1), ("created_at", -1)])
    await db.sta_runs.create_index([("project_id", 1), ("created_at", -1)])
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
    # Cut first-token latency for ChipSutra-VLSI (background; never blocks startup)
    if os.environ.get("OLLAMA_URL"):
        asyncio.create_task(prewarm_ollama())

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
    mongo = {"ok": False, "error": None}
    try:
        await asyncio.wait_for(client.admin.command("ping"), timeout=2.5)
        mongo = {"ok": True, "error": None}
    except Exception as e:
        err = str(e)
        hint = None
        if "SSL" in err or "TLS" in err or "tlsv1" in err.lower():
            hint = (
                "MongoDB Atlas Network Access is blocking this host. "
                "For multi-user online ChipSutra: allow 0.0.0.0/0 (API→Atlas only; users never connect to Mongo)."
                + _public_ipv4_for_atlas_hint()
            )
        mongo = {"ok": False, "error": err[:240], "hint": hint}
    status = "healthy" if mongo["ok"] else "degraded"
    return {
        "status": status,
        "mongo": mongo,
        "storage": storage_mode(),
        "verilator": bool(_sh.which("verilator")),
        "yosys": bool(_sh.which("yosys")),
        "eqy": bool(_sh.which("eqy")),
        "sby": bool(_sh.which("sby")),
        "cocotb": bool(_sh.which("cocotb-config")),
        "opensta": bool(sta_bin()),
        "fst": fst_status(),
        "rate_limit": rate_limit_status(),
        "llm_providers": providers,
        "ollama": llm_ollama_status(),
        "rag": llm_rag_status(),
        "rtl_ports": rtl_ports_status(),
        "lint_feedback": lint_feedback_status(),
        "eda_tools": tool_versions(),
        "cdc": {"engine": "chipsutra-cdc-v0|v1-yosys", "status": "experimental"},
        "google_auth": google_mode(),
        "llm_router": {
            "prewarm": prewarm_status(),
            "verilator": bool(verilator_bin()),
        },
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
ALLOWED_EXTS = {"v", "sv", "vhd", "vhdl", "pdf", "md", "docx", "txt", "vcd", "fst", "csv", "json", "log", "rpt", "lib", "sdc", "xml"}

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
        # Always keep text RTL/spec inline so Generate works even if local storage
        # paths differ between Docker and native hosts.
        "inline_content": (
            data.decode("utf-8", errors="ignore")
            if ext in ("v", "sv", "vhd", "vhdl", "txt", "md", "vcd", "log", "rpt", "csv", "json", "lib", "sdc", "xml")
            else None
        ),
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
    inline = fdoc.get("inline_content")
    if inline:
        return inline
    path = fdoc.get("storage_path")
    if path:
        try:
            data, _ = get_object(path)
            return data.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.warning(
                "Cannot read file %s from storage_path=%s: %s",
                fdoc.get("original_filename") or fdoc.get("id"),
                path,
                e,
            )
            return ""
    return ""

def _get_file_bytes(fdoc: dict) -> bytes:
    """Raw bytes of a stored file (binary-safe — FST waveforms cannot round-trip as text)."""
    if fdoc.get("storage_path"):
        try:
            data, _ = get_object(fdoc["storage_path"])
            return data
        except Exception:
            return b""
    inline = fdoc.get("inline_content")
    if inline:
        return inline.encode("utf-8", errors="ignore")
    return b""

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
    file_bodies: List[str] = []
    missing_content: List[str] = []
    fdocs: List[dict] = []
    if inp.file_ids:
        fdocs = await db.files.find(
            {"id": {"$in": inp.file_ids}, "project_id": inp.project_id, "is_deleted": {"$ne": True}},
            {"_id": 0},
        ).to_list(50)
        found_ids = {f.get("id") for f in fdocs}
        for fid in inp.file_ids:
            if fid not in found_ids:
                missing_content.append(f"unknown-id:{fid}")

    # Stale UI selections (deleted/re-uploaded files) → fall back to project RTL.
    if inp.module in ("testbench", "assertions", "covergroups", "checkers", "spec2rtl", "formal_hints") and not fdocs:
        fdocs = await db.files.find(
            {
                "project_id": inp.project_id,
                "is_deleted": {"$ne": True},
                "$or": [
                    {"ext": {"$in": ["v", "sv", "vhd", "vhdl"]}},
                    {"original_filename": {"$regex": r"\.(v|sv|vhd|vhdl)$", "$options": "i"}},
                ],
            },
            {"_id": 0},
        ).to_list(20)
        if fdocs:
            missing_content = []
            logger.info(
                "generate: selected file_ids missing; falling back to %d project RTL file(s)",
                len(fdocs),
            )

    for f in fdocs:
        file_names.append(f.get("original_filename") or "")
        text = _get_file_text(f)
        if text:
            file_bodies.append(text)
            file_context += f"\n\n--- FILE: {f['original_filename']} (kind={f.get('kind','')}) ---\n{text[:20000]}\n"
        else:
            missing_content.append(f.get("original_filename") or f.get("id") or "file")

    lang = inp.language or proj.get("language", "systemverilog")
    system_msg = MODULE_PROMPTS[inp.module].format(language=lang)
    system_msg += "\n\nYou are ChipSutra, an EDA verification assistant. Be concise, precise, and technical."
    rag_block = augment_generation_context(
        module=inp.module,
        prompt=(inp.prompt or "") + " " + file_context[:1200],
        filenames=file_names,
        # Keep RAG short for local 3B latency (especially testbench).
        top_k=2 if inp.module in ("testbench", "assertions", "covergroups", "checkers") else 4,
    )
    if rag_block:
        system_msg += (
            "\n\n--- Domain knowledge (reference only; user RTL/spec/files override if conflict) ---\n"
            + rag_block
        )

    port_block = extract_port_context_from_texts(file_bodies)
    if port_block:
        system_msg += "\n\n--- Parsed RTL interfaces ---\n" + port_block

    extra_rules = rules_for_module(inp.module, has_ports=bool(port_block))
    if extra_rules:
        system_msg += "\n\n" + extra_rules

    dut_hint = None
    parsed_modules: List[dict] = []
    if file_bodies:
        for body in file_bodies:
            parsed_modules.extend(extract_modules(body))
        if parsed_modules:
            dut_hint = f"module {parsed_modules[0]['name']}"

    # Never let the LLM invent a fake DUT (e.g. ChipSutra / data_in) when no RTL was attached.
    if inp.module == "testbench":
        if not file_bodies:
            if not inp.file_ids and not fdocs:
                raise HTTPException(
                    400,
                    "Select at least one RTL file (.v/.sv) in the project before generating a testbench.",
                )
            names = ", ".join(missing_content[:5]) or "selected file(s)"
            raise HTTPException(
                400,
                f"Could not read RTL content for: {names}. "
                "Re-upload the .v/.sv file, then select it and Generate again.",
            )
        if not any((m.get("ports") or []) for m in parsed_modules):
            raise HTTPException(
                400,
                "Could not parse DUT ports from the selected files. Open the RTL and confirm it has a module (...) port list.",
            )

    user_text = (inp.prompt or "").strip()
    if not user_text:
        user_text = default_user_prompt(inp.module, dut_hint=dut_hint)
    if file_context:
        user_text += "\n\n" + file_context
    if inp.tool_log:
        user_text += "\n\n" + format_lint_feedback(inp.tool_log, prior_code=inp.prior_output)

    dv_plan = plan_generation(
        module=inp.module,
        prompt=inp.prompt or "",
        tool_log=inp.tool_log or "",
        gen_mode=inp.gen_mode or "auto",
        modules=parsed_modules,
        rtl_text="\n".join(file_bodies[:3]),
    )

    spec_analysis = None
    debug_analysis = None
    if inp.module == "spec2rtl":
        spec_blob = (inp.prompt or "") + "\n" + file_context[:8000]
        spec_analysis = analyze_spec(spec_blob, prompt=inp.prompt or "")
        block = checklist_prompt_block(spec_analysis)
        if block:
            system_msg += "\n\n" + block
            if not spec_analysis.get("ready"):
                user_text += (
                    "\n\n[ChipSutra] Spec checklist incomplete — generate exploratory RTL with "
                    "documented // assumptions for missing clock/reset/I/O."
                )
    if inp.module == "debug" or (inp.tool_log or "").strip():
        debug_analysis = classify_log(inp.tool_log or "", prior_code=inp.prior_output or "")
        dblock = debug_prompt_block(debug_analysis)
        if dblock and (inp.module == "debug" or (inp.tool_log or "").strip()):
            system_msg += "\n\n" + dblock

    use_skeleton = should_use_tb_skeleton(
        module=inp.module,
        prompt=inp.prompt or "",
        modules=parsed_modules,
        gen_mode=inp.gen_mode or "auto",
        tool_log=inp.tool_log,
    )
    # Align with planner when it prefers skeleton for TB smoke.
    if inp.module == "testbench" and dv_plan.get("engine_preference") == "skeleton":
        use_skeleton = True
    elif inp.module == "testbench" and dv_plan.get("engine_preference") in ("llm", "hybrid"):
        if (inp.gen_mode or "auto").lower() in ("llm", "model") or dv_plan["intent"].get("wants_uvm") or (inp.tool_log or "").strip():
            use_skeleton = False

    skeleton_sv = ""
    ref_tb = ""
    if parsed_modules and parsed_modules[0].get("ports") and inp.module == "testbench":
        cycles = 48
        seed = 1
        m_cyc = re.search(r"\bcycles\s*=\s*(\d+)\b", inp.prompt or "", re.I)
        m_seed = re.search(r"\bseed\s*=\s*(\d+)\b", inp.prompt or "", re.I)
        if m_cyc:
            cycles = int(m_cyc.group(1))
        if m_seed:
            seed = int(m_seed.group(1))
        ref_tb = render_randomized_tb(parsed_modules[0], cycles=cycles, seed=seed)

    if use_skeleton and ref_tb:
        skeleton_sv = ref_tb
    elif inp.module == "testbench" and (inp.gen_mode or "auto").lower() in ("auto", "skeleton", "fast", "template"):
        if (
            ref_tb
            and not (inp.tool_log or "").strip()
            and not re.search(r"\b(uvm|agent|sequencer)\b", inp.prompt or "", re.I)
        ):
            skeleton_sv = ref_tb

    # LLM path: feed the known-good TB as a mandatory structural reference (3B models
    # otherwise invent broken clocks / circular goldens like exp=count+1).
    if not skeleton_sv and ref_tb and inp.module == "testbench":
        port_names = [
            p.get("name") for p in (parsed_modules[0].get("ports") or []) if p.get("name")
        ] if parsed_modules else []
        hint = tb_golden_hint_from_ports(port_names)
        user_text = (
            "MANDATORY reference testbench (copy this structure; keep exact ports; "
            "do not break the clock or golden model; output ONLY SystemVerilog, no essay):\n"
            f"{ref_tb}\n\n"
            f"Golden hint: {hint}\n\n"
            "User request:\n"
            + user_text
        )

    session_id = str(uuid.uuid4())
    gen_id = str(uuid.uuid4())
    route = resolve_model(
        provider=inp.model_provider or "ollama",
        requested_model=inp.model_name or "",
        model_tier=(dv_plan.get("model_tier") or "3b"),
    )
    resolved_provider = route.get("provider") or inp.model_provider
    resolved_model = route.get("model") or inp.model_name
    gen_doc = {
        "id": gen_id,
        "project_id": inp.project_id,
        "user_id": user["id"],
        "module": inp.module,
        "provider": "skeleton" if skeleton_sv else resolved_provider,
        "model": "tb_skeleton" if skeleton_sv else resolved_model,
        "prompt": inp.prompt or "",
        "file_ids": inp.file_ids or [],
        "output": "",
        "status": "streaming",
        "engine": "skeleton" if skeleton_sv else "llm",
        "router": route,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.generations.insert_one(gen_doc)

    async def event_gen():
        yield f"data: {json.dumps({'type': 'meta', 'generation_id': gen_id, 'engine': 'skeleton' if skeleton_sv else 'llm', 'router': route, 'plan': plan_to_learning(dv_plan)})}\n\n"
        accumulated = []
        try:
            if skeleton_sv:
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'skeleton', 'message': 'Emitting verified Fast-random TB…'})}\n\n"
                # Stream in small chunks so the UI feels live without waiting on Ollama.
                chunk = 120
                for i in range(0, len(skeleton_sv), chunk):
                    delta = skeleton_sv[i : i + chunk]
                    accumulated.append(delta)
                    yield f"data: {json.dumps({'type': 'delta', 'content': delta})}\n\n"
                    await asyncio.sleep(0)
            else:
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'llm', 'message': f'Calling {resolved_model}…', 'model': resolved_model})}\n\n"
                # Buffer LLM tokens, then quality-gate before showing the user.
                raw_chunks: List[str] = []
                ntok = 0
                async for delta in llm_stream_chat(
                    provider=resolved_provider,
                    model=resolved_model,
                    system=system_msg,
                    user_text=user_text,
                    session_id=session_id,
                    num_predict=num_predict_for_module(inp.module),
                ):
                    raw_chunks.append(delta)
                    ntok += 1
                    if ntok == 1 or ntok % 24 == 0:
                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'llm', 'message': f'Generating… ({ntok} chunks)', 'chunks': ntok})}\n\n"
                raw = "".join(raw_chunks)
                final = raw
                engine_tag = "llm"
                if inp.module == "testbench" and ref_tb:
                    ports = [p.get("name") for p in (parsed_modules[0].get("ports") or []) if p.get("name")]
                    force_uvm = bool(re.search(r"\b(uvm|agent|sequencer)\b", inp.prompt or "", re.I))
                    yield f"data: {json.dumps({'type': 'progress', 'stage': 'lint', 'message': 'Quality-gating TB (lint)…'})}\n\n"
                    final, engine_tag, issues = choose_testbench_output(
                        raw,
                        skeleton=ref_tb,
                        dut_name=(parsed_modules[0].get("name") if parsed_modules else None),
                        required_ports=ports,
                        force_uvm=force_uvm,
                    )
                    if issues:
                        logger.info("TB lint issues=%s engine=%s", issues, engine_tag)
                gen_doc_engine = engine_tag
                accumulated = [final]
                # Single replace event — avoid double-append with deltas.
                yield f"data: {json.dumps({'type': 'replace', 'content': final, 'engine': engine_tag})}\n\n"
            full = "".join(accumulated)
            done_engine = "skeleton" if skeleton_sv else locals().get("gen_doc_engine", "llm")
            learning: dict = {
                "engine": done_engine,
                **plan_to_learning(dv_plan),
                "router_reason": route.get("reason"),
                "resolved_model": None if skeleton_sv else resolved_model,
            }
            if spec_analysis is not None:
                learning["spec_checklist"] = {
                    "ready": spec_analysis.get("ready"),
                    "grade": spec_analysis.get("grade"),
                    "score": spec_analysis.get("score"),
                    "gaps": (spec_analysis.get("gaps") or [])[:6],
                }
            if debug_analysis is not None and not debug_analysis.get("empty"):
                learning["debug_classify"] = {
                    "top_category": debug_analysis.get("top_category"),
                    "summary": debug_analysis.get("summary"),
                    "findings": (debug_analysis.get("findings") or [])[:5],
                }
            if inp.module == "testbench":
                ports = []
                dut_name = None
                if parsed_modules:
                    dut_name = parsed_modules[0].get("name")
                    ports = [p.get("name") for p in (parsed_modules[0].get("ports") or []) if p.get("name")]
                lint_ok, lint_issues = lint_testbench(
                    extract_sv(full) or full,
                    dut_name=dut_name,
                    required_ports=ports or None,
                )
                auto = auto_score_testbench(full, done_engine, lint_ok, lint_issues)
                learning.update(
                    {
                        "lint_ok": lint_ok,
                        "lint_issues": lint_issues,
                        **auto,
                        "final_score": auto["auto_score"],
                    }
                )
                # Verifier loop: Verilator lint-only on TB + DUT; fallback to skeleton if LLM fails compile.
                if os.environ.get("CHIPSUTRA_VERIFY_TB", "true").lower() not in ("0", "false", "no"):
                    yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': 'Verilator verify (lint-only)…'})}\n\n"
                    rtl_sources = []
                    for i, body in enumerate(file_bodies[:6]):
                        fn = (file_names[i] if i < len(file_names) else f"dut_{i}.sv") or f"dut_{i}.sv"
                        rtl_sources.append((fn, body))
                    tb_top = None
                    m_tb = re.search(r"\bmodule\s+([A-Za-z_]\w*)", full or "")
                    if m_tb:
                        tb_top = m_tb.group(1)
                    vres = verify_testbench(
                        rtl_sources,
                        extract_sv(full) or full,
                        tb_name=f"{(dut_name or 'dut')}_tb.sv",
                        mode="lint",
                    )
                    learning.update(verify_status_for_learning(vres))
                    if vres.get("ok") is False and not vres.get("skipped") and ref_tb and done_engine in ("llm", "llm_repaired"):
                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify_repair', 'message': 'Verilator failed — falling back to verified template…'})}\n\n"
                        header = (
                            "// ChipSutra: LLM TB failed Verilator verify "
                            f"({vres.get('reason')}); using verified randomized template.\n"
                        )
                        full = header + ref_tb.lstrip()
                        done_engine = "skeleton_fallback"
                        learning["engine"] = done_engine
                        learning["verify_repaired"] = True
                        yield f"data: {json.dumps({'type': 'replace', 'content': full, 'engine': done_engine})}\n\n"
                        vres2 = verify_testbench(
                            rtl_sources,
                            extract_sv(full) or full,
                            tb_name=f"{(dut_name or 'dut')}_tb.sv",
                            mode="lint",
                        )
                        learning.update(verify_status_for_learning(vres2))
                        auto2 = auto_score_testbench(full, done_engine, True, [])
                        learning.update({**auto2, "final_score": auto2["auto_score"], "lint_ok": True})
                    elif vres.get("skipped"):
                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': 'Verilator not installed — skipped compile verify'})}\n\n"
                    elif vres.get("ok"):
                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': 'Verilator lint OK'})}\n\n"
                    else:
                        verr = ", ".join((vres.get("errors") or ["failed"])[:3])
                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': f'Verilator issues: {verr}'})}\n\n"

            await db.generations.update_one(
                {"id": gen_id},
                {
                    "$set": {
                        "output": full,
                        "status": "done",
                        "engine": done_engine,
                        "learning": learning,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
            yield f"data: {json.dumps({'type': 'done', 'generation_id': gen_id, 'engine': done_engine, 'learning': learning})}\n\n"
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


class GenerationFeedbackIn(BaseModel):
    rating: int  # 1 = thumbs up, -1 = thumbs down
    note: Optional[str] = ""


@api.post("/generations/{gen_id}/feedback")
async def generation_feedback(gen_id: str, inp: GenerationFeedbackIn, user=Depends(get_current_user)):
    if inp.rating not in (-1, 1):
        raise HTTPException(400, "rating must be 1 (up) or -1 (down)")
    gen = await db.generations.find_one({"id": gen_id}, {"_id": 0})
    if not gen:
        raise HTTPException(404, "Generation not found")
    await require_project(gen["project_id"], user["id"], "editor")
    learn = dict(gen.get("learning") or {})
    auto = float(learn.get("auto_score") or 50.0)
    final = combine_with_feedback(auto, inp.rating)
    learn.update(
        {
            "user_rating": inp.rating,
            "user_note": (inp.note or "")[:500],
            "final_score": final,
            "rated_by": user["id"],
            "rated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    await db.generations.update_one({"id": gen_id}, {"$set": {"learning": learn}})
    await db.kg_feedback.insert_one(
        {
            "id": str(uuid.uuid4()),
            "generation_id": gen_id,
            "project_id": gen["project_id"],
            "user_id": user["id"],
            "module": gen.get("module"),
            "rating": inp.rating,
            "note": (inp.note or "")[:500],
            "auto_score": auto,
            "final_score": final,
            "engine": gen.get("engine"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"ok": True, "learning": learn}


@api.get("/kg/learning-score")
async def kg_learning_score(
    user=Depends(get_current_user),
    project_id: Optional[str] = None,
    limit: int = Query(50, ge=5, le=200),
):
    """Rate whether KG learning is improving from recent generations + feedback."""
    q: dict = {"status": "done", "module": "testbench"}
    if project_id:
        await require_project(project_id, user["id"], "viewer")
        q["project_id"] = project_id
    else:
        # All projects the user can access: owned + collab is heavy; scope to user's gens
        q["user_id"] = user["id"]
    docs = await db.generations.find(q, {"_id": 0, "learning": 1, "engine": 1, "created_at": 1, "module": 1}).sort(
        "created_at", -1
    ).to_list(limit)
    report = aggregate_learning_report(docs)
    report["scope"] = {"project_id": project_id, "user_id": user["id"], "limit": limit}
    return report

# =========================
# Coverage parser (simple)
# =========================
@api.post("/coverage/parse")
async def parse_coverage(
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    user=Depends(get_current_user),
):
    data = (await file.read()).decode("utf-8", errors="ignore")
    # Industry exports first (UCIS XML / IMC-URG / CSV), plain text report as the fallback.
    try:
        result = ucis_parse.detect_and_parse(data, file.filename or "")
    except ValueError:
        result = parse_text_report(data)
    if project_id:
        await require_project(project_id, user["id"], "editor")
        run_id = str(uuid.uuid4())
        doc = {
            "id": run_id,
            "project_id": project_id,
            "user_id": user["id"],
            "source": result.get("source", "text_report"),
            "detected": result.get("detected"),
            "filename": file.filename,
            "overall": result["overall"],
            "metrics": result["metrics"],
            "holes": result["holes"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.coverage_runs.insert_one(doc)
        result["coverage_run_id"] = run_id
    return result


@api.get("/projects/{pid}/coverage")
async def list_coverage_runs(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    docs = await db.coverage_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return docs


@api.get("/projects/{pid}/coverage/trends")
async def coverage_trends(pid: str, limit: int = Query(30, ge=1, le=100), user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    docs = await db.coverage_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return trend_points(docs, limit=limit)


class CoverageMergeIn(BaseModel):
    coverage_run_ids: List[str] = Field(default_factory=list)


@api.post("/projects/{pid}/coverage/merge")
async def coverage_merge(pid: str, inp: CoverageMergeIn, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "editor")
    ids = (inp.coverage_run_ids or [])[:20]
    if len(ids) < 2:
        raise HTTPException(400, "Provide at least two coverage_run_ids")
    docs = await db.coverage_runs.find(
        {"project_id": pid, "id": {"$in": ids}},
        {"_id": 0},
    ).to_list(20)
    if len(docs) < 2:
        raise HTTPException(404, "Need at least two persisted coverage runs")
    # Union merge: a point is covered if any run covered it (averaging under-reports).
    merged = merge_summary_points(docs)
    run_id = str(uuid.uuid4())
    doc = {
        "id": run_id,
        "project_id": pid,
        "user_id": user["id"],
        **merged,
        "source_ids": [d["id"] for d in docs],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.coverage_runs.insert_one(doc)
    merged["coverage_run_id"] = run_id
    return merged


async def _coverage_doc(pid: str, cov_id: str) -> dict:
    doc = await db.coverage_runs.find_one({"project_id": pid, "id": cov_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Coverage run not found")
    return doc


@api.get("/projects/{pid}/coverage/{cov_id}/holes")
async def coverage_holes(
    pid: str,
    cov_id: str,
    limit: int = Query(20, ge=1, le=200),
    user=Depends(get_current_user),
):
    await require_project(pid, user["id"], "viewer")
    doc = await _coverage_doc(pid, cov_id)
    return {"holes": rank_holes(doc, limit=limit)}


class CoverageClosureIn(BaseModel):
    rtl_file_ids: List[str] = Field(default_factory=list)
    top_module: Optional[str] = None
    limit: int = 12
    base_seed: int = 1
    max_cases: int = 6


@api.post("/projects/{pid}/coverage/{cov_id}/closure-plan")
async def coverage_closure_plan(pid: str, cov_id: str, inp: CoverageClosureIn, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "editor")
    doc = await _coverage_doc(pid, cov_id)
    rtl_names: List[str] = []
    if inp.rtl_file_ids:
        fdocs = await db.files.find(
            {"id": {"$in": inp.rtl_file_ids[:50]}, "project_id": pid, "is_deleted": {"$ne": True}},
            {"_id": 0},
        ).to_list(50)
        rtl_names = [f.get("original_filename") or f["id"] for f in fdocs]
    return {
        "coverage_run_id": cov_id,
        "prompt": build_closure_prompt(doc, rtl_names, top_module=inp.top_module, limit=inp.limit),
        "resim": suggest_resim_plan(doc, base_seed=inp.base_seed, max_cases=inp.max_cases),
        "rtl_names": rtl_names,
    }


class CoverageClosureStatusIn(BaseModel):
    before_id: str
    after_id: str


@api.post("/projects/{pid}/coverage/closure-status")
async def coverage_closure_status(pid: str, inp: CoverageClosureStatusIn, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    before = await _coverage_doc(pid, inp.before_id)
    after = await _coverage_doc(pid, inp.after_id)
    return closure_status(before, after)

# =========================
# VCD parser
# =========================
def _build_signal_hierarchy(signal_index: List[dict]) -> dict:
    root = {"name": "root", "path": "", "children": [], "signals": []}
    nodes = {"": root}
    for sig in signal_index:
        parts = sig["path"].split(".")
        scope_parts = parts[:-1]
        parent_path = ""
        for part in scope_parts:
            path = ".".join(filter(None, [parent_path, part]))
            if path not in nodes:
                node = {"name": part, "path": path, "children": [], "signals": []}
                nodes[parent_path]["children"].append(node)
                nodes[path] = node
            parent_path = path
        nodes[parent_path]["signals"].append(sig)
    return root


def parse_vcd(
    text: str,
    max_signals: int = 512,
    max_events: int = 50000,
    selected_signal_ids: Optional[List[str]] = None,
    t0: Optional[int] = None,
    t1: Optional[int] = None,
    max_tracks: int = 64,
    max_steps: int = 1000,
) -> dict:
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
    all_times = sorted({t for t, _, _ in time_events})
    if t0 is not None:
        all_times = [t for t in all_times if t >= t0]
    if t1 is not None:
        all_times = [t for t in all_times if t <= t1]
    truncated = len(all_times) > max_steps or len(time_events) >= max_events
    if len(all_times) > max_steps:
        # Uniformly sample large VCDs instead of silently showing only the start.
        step = max(1, len(all_times) // max_steps)
        times = all_times[::step][:max_steps]
    else:
        times = all_times
    render_order = [sid for sid in (selected_signal_ids or order) if sid in signals][:max_tracks]
    # Compute value at each time step by iterating events
    last = {sid: "x" for sid in render_order}
    events_by_time = {}
    for t, sid, v in time_events:
        events_by_time.setdefault(t, []).append((sid, v))
    tracks = []
    for sid in render_order:
        row = []
        for t in times:
            if t in events_by_time:
                for esid, ev in events_by_time[t]:
                    if esid == sid:
                        last[sid] = ev
            row.append(last[sid])
        tracks.append({"id": sid, "name": signals[sid]["name"], "width": signals[sid]["width"], "values": row})
    signal_index = [
        {"id": sid, "path": signals[sid]["name"], "name": signals[sid]["name"].split(".")[-1], "width": signals[sid]["width"]}
        for sid in order
    ]
    return {
        "timescale": timescale,
        "times": times,
        "tracks": tracks,
        "signal_count": len(order),
        "signal_index": signal_index,
        "hierarchy": _build_signal_hierarchy(signal_index),
        "t_min": all_times[0] if all_times else 0,
        "t_max": all_times[-1] if all_times else 0,
        "truncated": truncated,
    }

def _vcd_text_from_waveform(data: bytes, filename: str = "waveform") -> str:
    """VCD text from raw waveform bytes. FST is converted via fst2vcd; VCD passes through."""
    if sniff_waveform_format(data) != "fst":
        return data.decode("utf-8", errors="ignore")
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", filename or "waveform") or "waveform"
    if not safe.lower().endswith(".fst"):
        safe += ".fst"
    with tempfile.TemporaryDirectory(prefix="chipsutra_fst_") as tmp:
        src = os.path.join(tmp, safe)
        with open(src, "wb") as fh:
            fh.write(data)
        res = ensure_vcd(src, out_dir=tmp)
        if not res.get("ok"):
            raise HTTPException(400, res.get("note") or "FST waveform could not be converted to VCD")
        with open(res["vcd_path"], encoding="utf-8", errors="ignore") as fh:
            return fh.read()


@api.post("/waveform/parse")
async def parse_waveform(file: UploadFile = File(...), user=Depends(get_current_user)):
    data = _vcd_text_from_waveform(await file.read(), file.filename or "waveform")
    try:
        result = parse_vcd(data)
    except Exception as e:
        raise HTTPException(400, f"Invalid VCD: {e}")
    return result


class WaveformProjectIn(BaseModel):
    project_id: str
    file_id: str
    signal_ids: Optional[List[str]] = None
    t0: Optional[int] = None
    t1: Optional[int] = None


@api.post("/waveform/parse-project")
async def parse_project_waveform(inp: WaveformProjectIn, user=Depends(get_current_user)):
    await require_project(inp.project_id, user["id"], "viewer")
    f = await db.files.find_one(
        {"id": inp.file_id, "project_id": inp.project_id, "is_deleted": {"$ne": True}},
        {"_id": 0},
    )
    if not f:
        raise HTTPException(404, "VCD file not found")
    raw = _get_file_bytes(f)
    if sniff_waveform_format(raw) == "fst":
        text = _vcd_text_from_waveform(raw, f.get("original_filename") or "waveform")
    else:
        text = _get_file_text(f)
    if not text:
        raise HTTPException(400, "VCD file is empty or unreadable")
    try:
        return parse_vcd(
            text,
            selected_signal_ids=inp.signal_ids,
            t0=inp.t0,
            t1=inp.t1,
        )
    except Exception as e:
        raise HTTPException(400, f"Invalid VCD: {e}")

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
    seed: Optional[int] = None
    coverage: bool = False  # Verilator --coverage when running
    use_lint_policy: bool = True


async def _project_lint_policy(project_id: str) -> dict:
    f = await db.files.find_one(
        {
            "project_id": project_id,
            "original_filename": "chipsutra.lint.json",
            "is_deleted": {"$ne": True},
        },
        {"_id": 0},
    )
    if not f:
        return parse_policy("{}")
    try:
        return parse_policy(_get_file_text(f))
    except Exception as e:
        raise HTTPException(400, f"Invalid chipsutra.lint.json: {e}")

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
        "mode": inp.mode,
        "seed": inp.seed,
        "coverage": bool(inp.coverage),
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
                                       "--Mdir", "obj_dir"]
                                if inp.coverage:
                                    cmd += ["--coverage-line", "--coverage-toggle"]
                                cmd += [os.path.basename(p) for p in written]
                                # Provide a minimal main if testbench has no $finish — we still need main.cpp
                                main_cpp = os.path.join(tmp, "sim_main.cpp")
                                seed_line = f"    srand({int(inp.seed)});\n" if inp.seed is not None else ""
                                coverage_include = "#include <verilated_cov.h>\n" if inp.coverage else ""
                                coverage_write = '    VerilatedCov::write("coverage.dat");\n' if inp.coverage else ""
                                with open(main_cpp, "w") as fh:
                                    fh.write(f"""
#include <verilated.h>
#include <verilated_vcd_c.h>
{coverage_include}#include <cstdlib>
#include "V{top}.h"
int main(int argc, char** argv) {{
    Verilated::commandArgs(argc, argv);
{seed_line}    V{top}* top = new V{top};
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
    top->final();
{coverage_write}    delete top;
    return 0;
}}
""")
                                cmd.append(os.path.basename(main_cpp))
                                manifest = build_manifest(
                                    engine="verilator",
                                    mode="run",
                                    command=cmd,
                                    top_module=top,
                                    file_hashes=sha256_paths(written),
                                    extra={"seed": inp.seed, "coverage": inp.coverage, "sim_time_ns": inp.sim_time_ns},
                                )
                                await db.simulations.update_one({"id": sim_id}, {"$set": {"manifest": manifest}})
                                yield log(f"$ {' '.join(cmd)}")
                                yield log(f"[manifest] tools: {manifest.get('tool_versions', {})}")
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
                                        if os.name == "nt" and os.path.exists(exe_path + ".exe"):
                                            exe_path += ".exe"
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
                                            if inp.coverage:
                                                cov = summarize_coverage_dat(tmp)
                                                if cov:
                                                    cov_id = str(uuid.uuid4())
                                                    await db.coverage_runs.insert_one({
                                                        "id": cov_id,
                                                        "project_id": inp.project_id,
                                                        "user_id": user["id"],
                                                        "simulation_id": sim_id,
                                                        "source": cov.get("source", "verilator"),
                                                        "overall": cov.get("overall", 0),
                                                        "metrics": cov.get("metrics", []),
                                                        "holes": cov.get("holes", []),
                                                        "created_at": datetime.now(timezone.utc).isoformat(),
                                                    })
                                                    await db.simulations.update_one(
                                                        {"id": sim_id},
                                                        {"$set": {"coverage_run_id": cov_id, "coverage_summary": {
                                                            "overall": cov.get("overall"),
                                                            "count": cov.get("count"),
                                                            "source": cov.get("source"),
                                                        }}},
                                                    )
                                                    yield log(
                                                        f"[coverage] overall={cov.get('overall')}% holes={len(cov.get('holes') or [])} (run {cov_id[:8]})",
                                                        "success",
                                                    )
                                                    yield f"data: {json.dumps({'type':'coverage','coverage_run_id': cov_id, 'overall': cov.get('overall'), 'holes': cov.get('holes', [])[:20]})}\n\n"
                                                else:
                                                    yield log("[coverage] enabled but no coverage.dat found", "warn")
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
                                manifest = build_manifest(
                                    engine="verilator",
                                    mode="lint",
                                    command=cmd,
                                    top_module=top,
                                    file_hashes=sha256_paths(written),
                                )
                                await db.simulations.update_one({"id": sim_id}, {"$set": {"manifest": manifest}})
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
                                    findings = parse_verilator_findings("\n".join(log_lines))
                                    policy = await _project_lint_policy(inp.project_id) if inp.use_lint_policy else parse_policy("{}")
                                    lint_report = apply_lint_policy(findings, policy)
                                    await db.simulations.update_one(
                                        {"id": sim_id},
                                        {"$set": {"lint_report": lint_report}},
                                    )
                                    yield f"data: {json.dumps({'type':'lint_report', **lint_report})}\n\n"
                                    if rc == 0 and lint_report["gate_ok"]:
                                        yield log("[verilator] ✓ lint passed. Design is well-formed.", "success")
                                        status = "done"
                                    elif rc == 0:
                                        yield log(
                                            f"[lint-policy] gate failed: {lint_report['counts']['blocking']} blocking finding(s)",
                                            "error",
                                        )
                                        status = "error"
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


TOOL_LOG_MAX_CHARS = 8000

@api.get("/projects/{pid}/latest-tool-log")
async def latest_tool_log(pid: str, user=Depends(get_current_user)):
    """Tail of the newest simulation/lint log so Generate can auto-fill tool_log."""
    await require_project(pid, user["id"], "viewer")
    doc = await db.simulations.find_one(
        {"project_id": pid, "log": {"$nin": [None, ""]}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not doc:
        return {"tool_log": None, "simulation_id": None, "status": None, "created_at": None}
    log = doc.get("log") or ""
    return {
        "tool_log": log[-TOOL_LOG_MAX_CHARS:],
        "simulation_id": doc.get("id"),
        "status": doc.get("status"),
        "created_at": doc.get("created_at"),
        "truncated": len(log) > TOOL_LOG_MAX_CHARS,
    }


# =========================
# Seeded regression matrix
# =========================
class RegressionCase(BaseModel):
    name: str
    rtl_file_ids: List[str] = Field(default_factory=list)
    tb_file_id: Optional[str] = None
    top_module: Optional[str] = None
    mode: str = "run"  # lint | run
    sim_time_ns: int = 1000
    seeds: List[int] = Field(default_factory=list)
    coverage: bool = False


class RegressionIn(BaseModel):
    project_id: str
    cases: List[RegressionCase] = Field(default_factory=list)
    stop_on_fail: bool = False
    max_workers: int = 1


def _expand_regression_cases(cases: List[RegressionCase]) -> List[tuple]:
    cells: List[tuple] = []
    for case in cases:
        for seed in (case.seeds or [None]):
            cells.append((case, seed))
    return cells


async def _run_regression_cell(
    *,
    index: int,
    case: RegressionCase,
    seed: Optional[int],
    project_id: str,
    user_id: str,
    regression_id: str,
) -> dict:
    sim_id = str(uuid.uuid4())
    all_ids = list(case.rtl_file_ids)
    if case.tb_file_id and case.tb_file_id not in all_ids:
        all_ids.append(case.tb_file_id)
    cell = {
        "index": index,
        "name": case.name,
        "seed": seed,
        "simulation_id": sim_id,
        "status": "error",
    }
    logs: List[str] = []
    engine = "verilator" if VERILATOR_BIN else "mock"
    await db.simulations.insert_one(
        {
            "id": sim_id,
            "regression_id": regression_id,
            "project_id": project_id,
            "user_id": user_id,
            "engine": engine,
            "file_ids": all_ids,
            "top_module": case.top_module,
            "mode": case.mode,
            "seed": seed,
            "status": "streaming",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if not all_ids:
        logs.append("No RTL/TB files supplied")
    elif not VERILATOR_BIN:
        logs.append("[mock] Verilator unavailable; regression cell not executed")
        cell["status"] = "mock"
    else:
        with tempfile.TemporaryDirectory(prefix="chipsutra_reg_") as tmp:
            try:
                written = await _write_files_to_dir(all_ids, project_id, tmp)
                top = case.top_module
                if not top and written:
                    with open(written[0], encoding="utf-8", errors="ignore") as fh:
                        top = _extract_top_module(fh.read())
                if not top:
                    raise RuntimeError("top module not detected")
                basenames = [os.path.basename(p) for p in written]
                if case.mode == "lint":
                    cmd = [VERILATOR_BIN, "--lint-only", "-Wno-fatal", "--top-module", top] + basenames
                else:
                    main_cpp = os.path.join(tmp, "reg_main.cpp")
                    seed_line = f"srand({int(seed)});" if seed is not None else ""
                    coverage_include = "#include <verilated_cov.h>\n" if case.coverage else ""
                    coverage_write = '  VerilatedCov::write("coverage.dat");\n' if case.coverage else ""
                    with open(main_cpp, "w", encoding="utf-8") as fh:
                        fh.write(
                            f"""#include <verilated.h>
{coverage_include}#include <cstdlib>
#include "V{top}.h"
int main(int argc, char** argv) {{
  Verilated::commandArgs(argc, argv); {seed_line}
  V{top} dut;
  for (vluint64_t t = 0; t < {max(50, case.sim_time_ns)} && !Verilated::gotFinish(); ++t) dut.eval();
  dut.final();
{coverage_write}  return 0;
}}
"""
                        )
                    cmd = [
                        VERILATOR_BIN,
                        "--cc",
                        "--exe",
                        "--build",
                        "-Wno-fatal",
                        "--timing",
                        "--top-module",
                        top,
                        "--Mdir",
                        "obj_dir",
                    ]
                    if case.coverage:
                        cmd += ["--coverage-line", "--coverage-toggle"]
                    cmd += basenames + [os.path.basename(main_cpp)]
                manifest = build_manifest(
                    engine="verilator",
                    mode=case.mode,
                    command=cmd,
                    top_module=top,
                    file_hashes=sha256_paths(written),
                    extra={"seed": seed, "regression_id": regression_id},
                )
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=tmp,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                assert proc.stdout is not None
                async for raw, timed_out in _stream_with_timeout(proc, 90.0):
                    line = raw.decode("utf-8", errors="ignore").rstrip()
                    if line:
                        logs.append(line)
                    if timed_out:
                        logs.append("Regression cell timed out")
                        break
                rc = await proc.wait()
                if rc == 0 and case.mode == "run":
                    exe = os.path.join(tmp, "obj_dir", f"V{top}")
                    if os.name == "nt":
                        exe_win = exe + ".exe"
                        if os.path.exists(exe_win):
                            exe = exe_win
                    rp = await asyncio.create_subprocess_exec(
                        exe,
                        cwd=tmp,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    assert rp.stdout is not None
                    async for raw, timed_out in _stream_with_timeout(rp, 30.0):
                        line = raw.decode("utf-8", errors="ignore").rstrip()
                        if line:
                            logs.append(line)
                        if timed_out:
                            break
                    rc = await rp.wait()
                    if case.coverage:
                        cov = summarize_coverage_dat(tmp)
                        if cov:
                            cov_id = str(uuid.uuid4())
                            await db.coverage_runs.insert_one(
                                {
                                    "id": cov_id,
                                    "project_id": project_id,
                                    "user_id": user_id,
                                    "simulation_id": sim_id,
                                    "regression_id": regression_id,
                                    **cov,
                                    "created_at": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                            cell["coverage_run_id"] = cov_id
                            cell["coverage_overall"] = cov.get("overall")
                            await db.simulations.update_one(
                                {"id": sim_id},
                                {"$set": {"coverage_run_id": cov_id, "coverage_summary": cov}},
                            )
                cell["status"] = "done" if rc == 0 else "error"
                await db.simulations.update_one({"id": sim_id}, {"$set": {"manifest": manifest}})
            except Exception as e:
                logs.append(str(e))
                cell["status"] = "error"
    await db.simulations.update_one(
        {"id": sim_id},
        {"$set": {
            "status": cell["status"],
            "log": "\n".join(logs),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    cell["log_tail"] = logs[-8:]
    return cell


@api.post("/regress/stream")
async def regression_stream(inp: RegressionIn, user=Depends(get_current_user)):
    await require_project(inp.project_id, user["id"], "editor")
    cells = _expand_regression_cases(inp.cases)
    if not cells:
        raise HTTPException(400, "Provide at least one regression case")
    if len(cells) > 20:
        raise HTTPException(400, "Regression matrix is capped at 20 runs")
    max_workers = max(1, min(4, int(inp.max_workers or 1)))

    regression_id = str(uuid.uuid4())
    await db.regressions.insert_one(
        {
            "id": regression_id,
            "project_id": inp.project_id,
            "user_id": user["id"],
            "status": "streaming",
            "requested_runs": len(cells),
            "max_workers": max_workers,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    async def evgen():
        yield f"data: {json.dumps({'type':'meta','regression_id': regression_id, 'runs': len(cells), 'max_workers': max_workers})}\n\n"
        results = []
        event_q: asyncio.Queue = asyncio.Queue()
        sem = asyncio.Semaphore(max_workers)
        stop_event = asyncio.Event()

        async def worker(index: int, case: RegressionCase, seed: Optional[int]):
            if stop_event.is_set():
                return
            await event_q.put({"type": "case_start", "index": index, "name": case.name, "seed": seed, "status": "running"})
            async with sem:
                if stop_event.is_set():
                    await event_q.put({
                        "type": "case_done",
                        "index": index,
                        "name": case.name,
                        "seed": seed,
                        "status": "skipped",
                        "simulation_id": None,
                        "log_tail": ["Skipped after stop_on_fail"],
                    })
                    return
                cell = await _run_regression_cell(
                    index=index,
                    case=case,
                    seed=seed,
                    project_id=inp.project_id,
                    user_id=user["id"],
                    regression_id=regression_id,
                )
            await event_q.put({"type": "case_done", **cell})
            if inp.stop_on_fail and cell.get("status") == "error":
                stop_event.set()

        tasks = [
            asyncio.create_task(worker(index, case, seed))
            for index, (case, seed) in enumerate(cells)
        ]

        async def _join_tasks():
            await asyncio.gather(*tasks, return_exceptions=True)
            await event_q.put(None)

        joiner = asyncio.create_task(_join_tasks())
        while True:
            event = await event_q.get()
            if event is None:
                break
            if event.get("type") == "case_done":
                results.append({k: event[k] for k in event if k != "type"})
                await db.regressions.update_one(
                    {"id": regression_id},
                    {"$set": {"results": results, "passed": sum(1 for r in results if r.get("status") == "done"),
                              "failed": sum(1 for r in results if r.get("status") == "error")}},
                )
            yield f"data: {json.dumps(event)}\n\n"
        await joiner
        results.sort(key=lambda r: r.get("index", 0))
        passed = sum(1 for r in results if r.get("status") == "done")
        failed = sum(1 for r in results if r.get("status") == "error")
        final_status = "done" if failed == 0 else "error"
        await db.regressions.update_one(
            {"id": regression_id},
            {"$set": {
                "status": final_status,
                "results": results,
                "passed": passed,
                "failed": failed,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        yield f"data: {json.dumps({'type':'done','status': final_status, 'passed': passed, 'failed': failed, 'results': results})}\n\n"

    return StreamingResponse(
        evgen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/projects/{pid}/regressions")
async def list_regressions(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    return await db.regressions.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(30)


@api.get("/projects/{pid}/regressions/trends")
async def regression_trends(pid: str, limit: int = Query(30, ge=1, le=100), user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    docs = await db.regressions.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    points = []
    for d in reversed(docs):
        points.append(
            {
                "id": d.get("id"),
                "created_at": d.get("created_at"),
                "passed": d.get("passed", 0),
                "failed": d.get("failed", 0),
                "status": d.get("status"),
                "requested_runs": d.get("requested_runs"),
            }
        )
    return {"points": points, "count": len(points)}

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
# Golden reference DUTs (backend/knowledge/golden)
# =========================
GOLDEN_DIR = ROOT_DIR / "knowledge" / "golden"


def _golden_descriptions() -> dict:
    """Map filename -> one-line description from the README markdown table."""
    out: dict = {}
    readme = GOLDEN_DIR / "README.md"
    if not readme.is_file():
        return out
    try:
        text = readme.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out
    for line in text.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).replace("`", "")
    return out


def _golden_entries() -> List[dict]:
    if not GOLDEN_DIR.is_dir():
        return []
    descriptions = _golden_descriptions()
    entries = []
    for path in sorted(GOLDEN_DIR.iterdir()):
        if not path.is_file():
            continue
        entries.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "kind": _golden_kind(path.name),
                "description": descriptions.get(path.name),
            }
        )
    return entries


def _golden_kind(name: str) -> str:
    low = name.lower()
    if not low.endswith((".sv", ".v")):
        return "doc"
    return "tb" if low.endswith("_tb.sv") or low.endswith("_tb.v") else "rtl"


@api.get("/golden-duts")
async def list_golden_duts():
    """Known-good reference RTL/testbenches shipped with ChipSutra."""
    return {"files": _golden_entries(), "dir": str(GOLDEN_DIR)}


class ImportGoldenIn(BaseModel):
    names: Optional[List[str]] = None


@api.post("/projects/{pid}/import-golden")
async def import_golden_duts(pid: str, inp: ImportGoldenIn, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "editor")
    available = {e["name"]: e for e in _golden_entries()}
    if not available:
        raise HTTPException(404, "No golden DUTs available in this installation")
    if inp.names is None:
        wanted = [n for n in available if n.lower().endswith((".sv", ".v"))]
    else:
        wanted = []
        for raw in inp.names:
            # Exact basenames only — never let a caller escape the golden directory.
            name = os.path.basename(str(raw or "").strip())
            if name not in available:
                raise HTTPException(400, f"Unknown golden DUT: {raw}")
            wanted.append(name)
    if not wanted:
        raise HTTPException(400, "No golden DUTs selected")

    created = []
    for name in wanted:
        path = GOLDEN_DIR / name
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            raise HTTPException(500, f"Cannot read golden DUT {name}: {e}")
        saved = await _persist_project_text_file(
            project_id=pid,
            filename=name,
            content=content,
            kind=_golden_kind(name),
            content_type="text/plain",
        )
        created.append(saved)
    return {"files": created, "count": len(created)}

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
# Rate limiting (Redis when REDIS_URL is set, in-memory otherwise — see rate_limit.py)
# =========================
def _rate_limit(key: str, max_calls: int = 10, window_s: float = 60.0):
    return enforce_rate_limit(key, max_calls=max_calls, window_s=window_s)

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
                            props = parse_sby_log("\n".join(logs))
                            cex_fid = None
                            for vcdp in find_cex_vcds(tmp)[:1]:
                                try:
                                    vcd_bytes = vcdp.read_bytes()
                                    cex_fid = str(uuid.uuid4())
                                    vcd_name = f"formal_cex_{top}_{formal_id[:8]}.vcd"
                                    storage_path = None
                                    try:
                                        r = put_object(f"{APP_NAME}/projects/{inp.project_id}/{cex_fid}.vcd", vcd_bytes, "text/plain")
                                        storage_path = r["path"]
                                    except Exception:
                                        pass
                                    await db.files.insert_one({
                                        "id": cex_fid,
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
                                    yield log(f"[sby] counterexample VCD saved as {vcd_name}", "warn")
                                except Exception as e:
                                    yield log(f"[sby] could not save CEX VCD: {e}", "warn")
                            manifest = build_manifest(
                                engine="sby",
                                mode=inp.mode,
                                command=cmd,
                                top_module=top,
                                file_hashes=sha256_paths(written),
                                extra={"depth": inp.depth, "properties": props[:20]},
                            )
                            await db.formal_runs.update_one(
                                {"id": formal_id},
                                {"$set": {
                                    "properties": props,
                                    "cex_vcd_file_id": cex_fid,
                                    "manifest": manifest,
                                }},
                            )
                            if props:
                                yield f"data: {json.dumps({'type':'properties','items': props})}\n\n"
                            if cex_fid:
                                yield f"data: {json.dumps({'type':'cex','file_id': cex_fid})}\n\n"
                            status = "done" if rc == 0 else "error"
                            if rc == 0:
                                yield log("[sby] ✓ formal verification passed", "success")
                            elif saw_prep_error:
                                yield log("[sby] NOTE: This environment may ship an old Yosys incompatible with latest SBY 'formalff'. Prefer Yosys ≥ 0.35 / OSS CAD Suite. Use AI Formal Hints meanwhile.", "warn")
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

# ---- Yosys synthesis / equivalence / eqy LEC ----
YOSYS_BIN = shutil.which("yosys")
EQY_BIN = shutil.which("eqy")


class SynthIn(BaseModel):
    project_id: str
    rtl_file_ids: List[str] = Field(default_factory=list)
    top_module: Optional[str] = None
    mode: str = "synth"  # synth | equiv | eqy
    # Multi-revision LEC: compare two explicit file sets (eqy mode) instead of RTL vs its own netlist
    gold_file_ids: List[str] = Field(default_factory=list)
    gate_file_ids: List[str] = Field(default_factory=list)


async def _unique_project_filename(project_id: str, filename: str) -> str:
    exists = await db.files.find_one(
        {"project_id": project_id, "original_filename": filename, "is_deleted": {"$ne": True}},
        {"_id": 0, "id": 1},
    )
    if not exists:
        return filename
    if "." in filename:
        stem, ext = filename.rsplit(".", 1)
        return f"{stem}_{uuid.uuid4().hex[:8]}.{ext}"
    return f"{filename}_{uuid.uuid4().hex[:8]}"


async def _persist_project_text_file(
    *,
    project_id: str,
    filename: str,
    content: str,
    kind: str = "artifact",
    content_type: str = "text/plain",
) -> dict:
    name = await _unique_project_filename(project_id, filename)
    file_id = str(uuid.uuid4())
    data = content.encode("utf-8")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    storage_path = None
    try:
        r = put_object(f"{APP_NAME}/projects/{project_id}/{file_id}.{ext or 'txt'}", data, content_type)
        storage_path = r["path"]
    except Exception:
        pass
    doc = {
        "id": file_id,
        "project_id": project_id,
        "original_filename": name,
        "ext": ext,
        "kind": kind,
        "size": len(data),
        "content_type": content_type,
        "storage_path": storage_path,
        "inline_content": content if storage_path is None else None,
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.files.insert_one(doc)
    return {k: v for k, v in doc.items() if k not in ("inline_content", "_id")}


@api.post("/synth/stream")
async def synth_stream(inp: SynthIn, user=Depends(get_current_user)):
    await require_project(inp.project_id, user["id"], "editor")
    multi_rev = inp.mode == "eqy" and bool(inp.gold_file_ids) and bool(inp.gate_file_ids)
    if not inp.rtl_file_ids and not multi_rev:
        raise HTTPException(400, "Provide at least one synthesizable RTL file")
    if inp.mode not in ("synth", "equiv", "eqy"):
        raise HTTPException(400, "mode must be synth, equiv, or eqy")
    run_id = str(uuid.uuid4())
    await db.synth_runs.insert_one(
        {
            "id": run_id,
            "project_id": inp.project_id,
            "user_id": user["id"],
            "mode": inp.mode,
            "status": "streaming",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    async def evgen():
        engine = "yosys" if YOSYS_BIN else "mock"
        if inp.mode == "eqy" and EQY_BIN and YOSYS_BIN:
            engine = "eqy"
        yield f"data: {json.dumps({'type':'meta','synth_id': run_id,'engine': engine, 'mode': inp.mode})}\n\n"
        logs: List[str] = []
        status = "error"
        stats: dict = {}
        artifact_ids: List[str] = []
        note: Optional[str] = None

        if not YOSYS_BIN:
            msg = "[mock] Yosys unavailable. Use Docker/OSS CAD Suite for synthesis / LEC."
            logs.append(msg)
            yield f"data: {json.dumps({'type':'log','level':'warn','line':msg})}\n\n"
            status = "mock"
            stats = {"note": msg, "equivalence": None}
        else:
            with tempfile.TemporaryDirectory(prefix="chipsutra_synth_") as tmp:
                try:
                    gold_rel: List[str] = []
                    gate_rel: List[str] = []
                    if multi_rev:
                        # Separate subdirs so a revision pair with identical filenames does not collide.
                        gold_dir = os.path.join(tmp, "gold")
                        gate_dir = os.path.join(tmp, "gate")
                        os.makedirs(gold_dir, exist_ok=True)
                        os.makedirs(gate_dir, exist_ok=True)
                        gold_written = await _write_files_to_dir(inp.gold_file_ids, inp.project_id, gold_dir)
                        gate_written = await _write_files_to_dir(inp.gate_file_ids, inp.project_id, gate_dir)
                        if not gold_written or not gate_written:
                            raise RuntimeError("Multi-revision LEC needs readable gold and gate files")
                        gold_rel = ["gold/" + os.path.basename(p) for p in gold_written]
                        gate_rel = ["gate/" + os.path.basename(p) for p in gate_written]
                        written = gold_written + gate_written
                    else:
                        written = await _write_files_to_dir(inp.rtl_file_ids, inp.project_id, tmp)
                        if not written:
                            raise RuntimeError("No readable RTL files")
                    top = inp.top_module
                    if not top:
                        with open(written[0], encoding="utf-8", errors="ignore") as fh:
                            top = _extract_top_module(fh.read())
                    if not top:
                        raise RuntimeError("top module not detected")
                    basenames = gold_rel if multi_rev else [os.path.basename(p) for p in written]
                    effective_mode = inp.mode
                    if inp.mode == "eqy" and not EQY_BIN:
                        note = fallback_equiv_note(True)
                        effective_mode = "equiv"
                        if multi_rev:
                            note += (
                                " Multi-revision compare needs eqy; ran the internal Yosys equiv "
                                "check on the gold revision only."
                            )
                        warn = f"[eqy] {note}"
                        logs.append(warn)
                        yield f"data: {json.dumps({'type':'log','level':'warn','line':warn})}\n\n"

                    # --- eqy path: compare two revisions, or RTL vs its own synthesized netlist ---
                    if inp.mode == "eqy" and EQY_BIN:
                        hash_paths = list(written)
                        if multi_rev:
                            msg = (
                                f"[eqy] multi-revision LEC: gold={', '.join(gold_rel)} "
                                f"vs gate={', '.join(gate_rel)}"
                            )
                            logs.append(msg)
                            yield f"data: {json.dumps({'type':'log','level':'info','line':msg})}\n\n"
                        else:
                            syn_script = synth_script(top, basenames)
                            ys = os.path.join(tmp, "chipsutra_synth.ys")
                            with open(ys, "w", encoding="utf-8") as fh:
                                fh.write(syn_script)
                            synth_cmd = [YOSYS_BIN, "-s", os.path.basename(ys)]
                            logs.append("$ " + " ".join(synth_cmd))
                            yield f"data: {json.dumps({'type':'log','level':'info','line':logs[-1]})}\n\n"
                            proc = await asyncio.create_subprocess_exec(
                                *synth_cmd,
                                cwd=tmp,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.STDOUT,
                            )
                            assert proc.stdout is not None
                            async for raw, timed_out in _stream_with_timeout(proc, 90.0):
                                line = raw.decode("utf-8", errors="ignore").rstrip()
                                if line:
                                    logs.append(line)
                                    level = "error" if "error:" in line.lower() else "info"
                                    yield f"data: {json.dumps({'type':'log','level':level,'line':line})}\n\n"
                                if timed_out:
                                    logs.append("Yosys synth (for eqy) timed out")
                                    break
                            src = await proc.wait()
                            netlist = os.path.join(tmp, "synth_netlist.v")
                            if src != 0 or not os.path.isfile(netlist):
                                raise RuntimeError("Could not synthesize gate netlist for eqy LEC")
                            gold_rel = basenames
                            gate_rel = ["synth_netlist.v"]
                            hash_paths.append(netlist)
                        cfg = eqy_config(top, gold_rel, gate_rel)
                        eqy_path = os.path.join(tmp, "chipsutra.eqy")
                        with open(eqy_path, "w", encoding="utf-8") as fh:
                            fh.write(cfg)
                        eqy_cmd = [EQY_BIN, "-f", "chipsutra.eqy"]
                        manifest = build_manifest(
                            engine="eqy",
                            mode="eqy",
                            command=eqy_cmd,
                            top_module=top,
                            file_hashes=sha256_paths(hash_paths),
                            extra={"gold": gold_rel, "gate": gate_rel, "multi_revision": multi_rev},
                        )
                        logs.append("$ " + " ".join(eqy_cmd))
                        yield f"data: {json.dumps({'type':'log','level':'info','line':logs[-1]})}\n\n"
                        proc = await asyncio.create_subprocess_exec(
                            *eqy_cmd,
                            cwd=tmp,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                        )
                        assert proc.stdout is not None
                        async for raw, timed_out in _stream_with_timeout(proc, 180.0):
                            line = raw.decode("utf-8", errors="ignore").rstrip()
                            if line:
                                logs.append(line)
                                level = "error" if "error" in line.lower() else "info"
                                yield f"data: {json.dumps({'type':'log','level':level,'line':line})}\n\n"
                            if timed_out:
                                logs.append("eqy timed out")
                                break
                        rc = await proc.wait()
                        stats = parse_eqy_log("\n".join(logs))
                        stats.update(parse_yosys_log("\n".join(logs)))
                        stats["engine"] = "eqy"
                        status = "done" if rc == 0 and stats.get("equivalence") != "fail" and not stats.get("errors") else "error"
                        # also export synth artifacts from the gate netlist step
                        for art_name in ("synth.json", "synth_netlist.v"):
                            art_path = os.path.join(tmp, art_name)
                            if os.path.isfile(art_path):
                                with open(art_path, encoding="utf-8", errors="ignore") as fh:
                                    text = fh.read()
                                saved = await _persist_project_text_file(
                                    project_id=inp.project_id,
                                    filename=art_name,
                                    content=text,
                                    kind="artifact",
                                    content_type="application/json" if art_name.endswith(".json") else "text/plain",
                                )
                                artifact_ids.append(saved["id"])
                                yield f"data: {json.dumps({'type':'artifact','file_id': saved['id'], 'filename': saved['original_filename']})}\n\n"
                        await db.synth_runs.update_one(
                            {"id": run_id},
                            {"$set": {
                                "manifest": manifest,
                                "stats": stats,
                                "top_module": top,
                                "artifact_ids": artifact_ids,
                                "note": note,
                            }},
                        )
                        yield f"data: {json.dumps({'type':'stats','stats':stats, 'note': note})}\n\n"
                    else:
                        # synth or equiv (including eqy fallback)
                        script = (
                            synth_script(top, basenames)
                            if effective_mode == "synth"
                            else equiv_script(top, basenames)
                        )
                        ys = os.path.join(tmp, "chipsutra.ys")
                        with open(ys, "w", encoding="utf-8") as fh:
                            fh.write(script)
                        cmd = [YOSYS_BIN, "-s", os.path.basename(ys)]
                        manifest = build_manifest(
                            engine="yosys",
                            mode=effective_mode,
                            command=cmd,
                            top_module=top,
                            file_hashes=sha256_paths(written),
                            extra={"requested_mode": inp.mode, "note": note} if note else {"requested_mode": inp.mode},
                        )
                        logs.append("$ " + " ".join(cmd))
                        yield f"data: {json.dumps({'type':'log','level':'info','line':logs[-1]})}\n\n"
                        proc = await asyncio.create_subprocess_exec(
                            *cmd,
                            cwd=tmp,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                        )
                        assert proc.stdout is not None
                        async for raw, timed_out in _stream_with_timeout(proc, 90.0):
                            line = raw.decode("utf-8", errors="ignore").rstrip()
                            if line:
                                logs.append(line)
                                level = "error" if "error:" in line.lower() else "info"
                                yield f"data: {json.dumps({'type':'log','level':level,'line':line})}\n\n"
                            if timed_out:
                                logs.append("Yosys timed out")
                                break
                        rc = await proc.wait()
                        stats = parse_yosys_log("\n".join(logs))
                        if note:
                            stats["note"] = note
                            stats["fallback"] = "yosys-equiv"
                        status = "done" if rc == 0 and not stats.get("errors") else "error"
                        if effective_mode == "synth" or inp.mode == "eqy":
                            for art_name in ("synth.json", "synth_netlist.v"):
                                art_path = os.path.join(tmp, art_name)
                                if not os.path.isfile(art_path):
                                    continue
                                with open(art_path, encoding="utf-8", errors="ignore") as fh:
                                    text = fh.read()
                                saved = await _persist_project_text_file(
                                    project_id=inp.project_id,
                                    filename=art_name,
                                    content=text,
                                    kind="artifact",
                                    content_type="application/json" if art_name.endswith(".json") else "text/plain",
                                )
                                artifact_ids.append(saved["id"])
                                yield f"data: {json.dumps({'type':'artifact','file_id': saved['id'], 'filename': saved['original_filename']})}\n\n"
                        await db.synth_runs.update_one(
                            {"id": run_id},
                            {"$set": {
                                "manifest": manifest,
                                "stats": stats,
                                "top_module": top,
                                "artifact_ids": artifact_ids,
                                "note": note,
                            }},
                        )
                        yield f"data: {json.dumps({'type':'stats','stats':stats, 'note': note})}\n\n"
                except Exception as e:
                    logs.append(str(e))
                    yield f"data: {json.dumps({'type':'log','level':'error','line':str(e)})}\n\n"
        await db.synth_runs.update_one(
            {"id": run_id},
            {"$set": {
                "status": status,
                "log": "\n".join(logs),
                "stats": stats,
                "artifact_ids": artifact_ids,
                "note": note,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        yield f"data: {json.dumps({'type':'done','status':status,'synth_id':run_id,'stats':stats,'artifact_ids':artifact_ids,'note':note})}\n\n"

    return StreamingResponse(
        evgen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/projects/{pid}/synth-runs")
async def list_synth_runs(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    return await db.synth_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(30)


class CocotbScaffoldIn(BaseModel):
    rtl_file_id: str
    top_module: Optional[str] = None


@api.post("/projects/{pid}/scaffold/cocotb")
async def scaffold_cocotb(pid: str, inp: CocotbScaffoldIn, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "editor")
    rtl = await db.files.find_one(
        {"id": inp.rtl_file_id, "project_id": pid, "is_deleted": {"$ne": True}},
        {"_id": 0},
    )
    if not rtl:
        raise HTTPException(404, "RTL file not found")
    text = _get_file_text(rtl)
    top = inp.top_module or _extract_top_module(text)
    if not top:
        raise HTTPException(400, "Could not detect top module")
    generated = render_cocotb_scaffold(top, rtl["original_filename"])
    docs = []
    for name, content in generated.items():
        saved = await _persist_project_text_file(
            project_id=pid,
            filename=name,
            content=content,
            kind="tb" if name.endswith(".py") or name == "Makefile" else "doc",
        )
        docs.append(saved)
    return {"top_module": top, "files": docs, "runner": "scaffold-only", "command": "make SIM=verilator"}


class CocotbStreamIn(BaseModel):
    project_id: str
    top_module: Optional[str] = None
    sim: str = "verilator"


@api.post("/cocotb/stream")
async def cocotb_stream(inp: CocotbStreamIn, user=Depends(get_current_user)):
    await require_project(inp.project_id, user["id"], "editor")
    files = await db.files.find(
        {"project_id": inp.project_id, "is_deleted": {"$ne": True}},
        {"_id": 0},
    ).to_list(200)
    makefile, test_py, rtl = pick_scaffold_files(files)
    if not makefile or not test_py:
        raise HTTPException(
            400,
            "No cocotb scaffold found. Use Project → cocotb to generate Makefile + test_*.py first.",
        )
    if not rtl:
        raise HTTPException(400, "No RTL (.v/.sv) files found in project")
    run_id = str(uuid.uuid4())
    await db.cocotb_runs.insert_one(
        {
            "id": run_id,
            "project_id": inp.project_id,
            "user_id": user["id"],
            "status": "streaming",
            "sim": inp.sim,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    async def evgen():
        logs: List[str] = []
        status = "error"
        stats: dict = {}
        has_make = bool(shutil.which("make") or shutil.which("mingw32-make"))
        has_v = bool(VERILATOR_BIN)
        has_c = cocotb_available()
        engine = "cocotb" if (has_make and has_v and has_c) else "mock"
        yield f"data: {json.dumps({'type':'meta','cocotb_run_id': run_id, 'engine': engine})}\n\n"

        if not has_c or not has_make or not has_v:
            missing = []
            if not has_c:
                missing.append("cocotb-config")
            if not has_make:
                missing.append("make")
            if not has_v:
                missing.append("verilator")
            msg = (
                f"[mock] Missing tools for cocotb run: {', '.join(missing)}. "
                "Install cocotb + Verilator + make (or use OSS CAD Suite / Docker), "
                "then re-run. Scaffold files remain in the project."
            )
            logs.append(msg)
            yield f"data: {json.dumps({'type':'log','level':'warn','line':msg})}\n\n"
            status = "mock"
            stats = {"missing": missing, "status_hint": "mock"}
        else:
            with tempfile.TemporaryDirectory(prefix="chipsutra_cocotb_") as tmp:
                try:
                    write_docs = [makefile, test_py] + list(rtl)
                    written_paths = []
                    for f in write_docs:
                        content = _get_file_text(f)
                        if content is None:
                            continue
                        local_name = re.sub(r"[^A-Za-z0-9_.\-]", "_", f["original_filename"])
                        if local_name.lower() == "makefile":
                            local_name = "Makefile"
                        p = os.path.join(tmp, local_name)
                        with open(p, "w", encoding="utf-8") as fh:
                            fh.write(content)
                        written_paths.append(p)
                    try:
                        cmd = build_make_cmd(inp.sim or "verilator")
                    except RuntimeError as e:
                        raise RuntimeError(str(e))
                    manifest = build_manifest(
                        engine="cocotb",
                        mode="make",
                        command=cmd,
                        top_module=inp.top_module,
                        file_hashes=sha256_paths(written_paths),
                        extra={"makefile": makefile.get("original_filename"), "test": test_py.get("original_filename")},
                    )
                    logs.append("$ " + " ".join(cmd))
                    yield f"data: {json.dumps({'type':'log','level':'info','line':logs[-1]})}\n\n"
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        cwd=tmp,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        env={**os.environ},
                    )
                    assert proc.stdout is not None
                    async for raw, timed_out in _stream_with_timeout(proc, 180.0):
                        line = raw.decode("utf-8", errors="ignore").rstrip()
                        if line:
                            logs.append(line)
                            level = "error" if "error" in line.lower() or "fail" in line.lower() else "info"
                            yield f"data: {json.dumps({'type':'log','level':level,'line':line})}\n\n"
                        if timed_out:
                            logs.append("cocotb make timed out")
                            break
                    rc = await proc.wait()
                    stats = parse_cocotb_log("\n".join(logs))
                    status = "done" if rc == 0 else "error"
                    await db.cocotb_runs.update_one(
                        {"id": run_id},
                        {"$set": {"manifest": manifest, "stats": stats}},
                    )
                except Exception as e:
                    logs.append(str(e))
                    yield f"data: {json.dumps({'type':'log','level':'error','line':str(e)})}\n\n"

        await db.cocotb_runs.update_one(
            {"id": run_id},
            {"$set": {
                "status": status,
                "log": "\n".join(logs),
                "stats": stats,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        yield f"data: {json.dumps({'type':'done','status':status,'cocotb_run_id':run_id,'stats':stats})}\n\n"

    return StreamingResponse(
        evgen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/projects/{pid}/cocotb-runs")
async def list_cocotb_runs(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    return await db.cocotb_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(30)


class OpenStaScaffoldIn(BaseModel):
    rtl_file_id: Optional[str] = None
    top_module: Optional[str] = None
    clock_name: str = "clk"
    period_ns: float = 10.0
    netlist_filename: str = "synth_netlist.v"


@api.post("/projects/{pid}/scaffold/opensta")
async def scaffold_opensta(pid: str, inp: OpenStaScaffoldIn, user=Depends(get_current_user)):
    """Generate chipsutra.sdc + opensta.tcl scaffold (not a full STA run — liberty required)."""
    await require_project(pid, user["id"], "editor")
    top = inp.top_module
    netlist_name = inp.netlist_filename
    if inp.rtl_file_id:
        rtl = await db.files.find_one(
            {"id": inp.rtl_file_id, "project_id": pid, "is_deleted": {"$ne": True}},
            {"_id": 0},
        )
        if not rtl:
            raise HTTPException(404, "RTL file not found")
        if not top:
            top = _extract_top_module(_get_file_text(rtl) or "")
        # Prefer a project synth_netlist.v artifact if present
        arts = await db.files.find(
            {
                "project_id": pid,
                "is_deleted": {"$ne": True},
                "original_filename": {"$regex": r"^synth_netlist"},
            },
            {"_id": 0},
        ).sort("created_at", -1).to_list(1)
        if arts:
            netlist_name = arts[0]["original_filename"]
    sdc = default_sdc_stub(inp.clock_name or "clk", float(inp.period_ns or 10.0))
    tcl = build_sta_tcl(
        netlist=netlist_name,
        liberty=None,
        sdc="chipsutra.sdc",
        top=top,
    )
    note = (
        "OpenSTA scaffold only — full timing needs a liberty (.lib) file. "
        "Install `sta`/`opensta`, place liberty beside the TCL, then run: sta opensta.tcl"
    )
    docs = []
    for name, content, kind in (
        ("chipsutra.sdc", sdc, "constraint"),
        ("opensta.tcl", tcl, "script"),
    ):
        saved = await _persist_project_text_file(project_id=pid, filename=name, content=content, kind=kind)
        docs.append(saved)
    return {
        "files": docs,
        "top_module": top,
        "netlist": netlist_name,
        "note": note,
        "opensta_available": bool(sta_bin()),
        "runner": "scaffold-only",
    }


class StaRunIn(BaseModel):
    project_id: str
    netlist_file_id: Optional[str] = None
    liberty_file_id: Optional[str] = None
    sdc_file_id: Optional[str] = None
    top_module: Optional[str] = None
    clock_name: str = "clk"
    period_ns: float = 10.0
    max_paths: int = 10


async def _sta_pick_netlist(pid: str, file_id: Optional[str]) -> Optional[dict]:
    """Explicit netlist file, else the newest synth_netlist* artifact in the project."""
    if file_id:
        return await db.files.find_one(
            {"id": file_id, "project_id": pid, "is_deleted": {"$ne": True}},
            {"_id": 0},
        )
    docs = await db.files.find(
        {
            "project_id": pid,
            "is_deleted": {"$ne": True},
            "original_filename": {"$regex": r"^synth_netlist"},
        },
        {"_id": 0},
    ).sort("created_at", -1).to_list(1)
    return docs[0] if docs else None


def _sta_local_name(fdoc: dict, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", fdoc.get("original_filename") or "")
    return name or fallback


@api.post("/sta/stream")
async def sta_stream(inp: StaRunIn, user=Depends(get_current_user)):
    """Full OpenSTA timing run (SSE). Falls back to a mock run when sta or a liberty is missing."""
    await require_project(inp.project_id, user["id"], "editor")
    netlist_doc = await _sta_pick_netlist(inp.project_id, inp.netlist_file_id)
    if not netlist_doc:
        raise HTTPException(
            404,
            "No netlist found. Run Synthesis first (it saves synth_netlist.v) or pass netlist_file_id.",
        )
    liberty_doc = None
    if inp.liberty_file_id:
        liberty_doc = await db.files.find_one(
            {"id": inp.liberty_file_id, "project_id": inp.project_id, "is_deleted": {"$ne": True}},
            {"_id": 0},
        )
        if not liberty_doc:
            raise HTTPException(404, "Liberty file not found")
    sdc_doc = None
    if inp.sdc_file_id:
        sdc_doc = await db.files.find_one(
            {"id": inp.sdc_file_id, "project_id": inp.project_id, "is_deleted": {"$ne": True}},
            {"_id": 0},
        )
        if not sdc_doc:
            raise HTTPException(404, "SDC file not found")

    run_id = str(uuid.uuid4())
    await db.sta_runs.insert_one(
        {
            "id": run_id,
            "project_id": inp.project_id,
            "user_id": user["id"],
            "status": "streaming",
            "netlist_file_id": netlist_doc["id"],
            "liberty_file_id": (liberty_doc or {}).get("id"),
            "sdc_file_id": (sdc_doc or {}).get("id"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    async def evgen():
        logs: List[str] = []
        status = "error"
        stats: dict = {}
        note: Optional[str] = None
        binary = sta_bin()
        engine = "opensta" if (binary and liberty_doc) else "mock"
        top = inp.top_module or _extract_top_module(_get_file_text(netlist_doc))
        yield f"data: {json.dumps({'type':'meta','sta_id': run_id,'engine': engine,'top_module': top})}\n\n"

        if engine == "mock":
            missing = []
            if not binary:
                missing.append("sta/opensta binary")
            if not liberty_doc:
                missing.append("liberty (.lib) file")
            note = (
                f"[mock] Timing not run — missing: {', '.join(missing)}. "
                "Install OpenSTA (`sta`) via OSS CAD Suite / Docker and upload a liberty (.lib) "
                "for your target library, then re-run. Netlist and SDC are ready."
            )
            logs.append(note)
            yield f"data: {json.dumps({'type':'log','level':'warn','line':note})}\n\n"
            status = "mock"
            stats = {"missing": missing, "status_hint": "mock", "engine": "opensta"}
        else:
            with tempfile.TemporaryDirectory(prefix="chipsutra_sta_") as tmp:
                try:
                    netlist_name = _sta_local_name(netlist_doc, "netlist.v")
                    netlist_path = os.path.join(tmp, netlist_name)
                    with open(netlist_path, "w", encoding="utf-8") as fh:
                        fh.write(_get_file_text(netlist_doc))
                    written = [netlist_path]

                    liberty_name = _sta_local_name(liberty_doc, "library.lib")
                    liberty_text = _get_file_text(liberty_doc)
                    liberty_path = os.path.join(tmp, liberty_name)
                    with open(liberty_path, "w", encoding="utf-8") as fh:
                        fh.write(liberty_text)
                    written.append(liberty_path)
                    if not liberty_is_plausible(liberty_text):
                        warn = (
                            f"[sta] {liberty_name} does not look like a liberty file "
                            "(no library/cell sections) — link_design will probably fail"
                        )
                        logs.append(warn)
                        yield f"data: {json.dumps({'type':'log','level':'warn','line':warn})}\n\n"

                    if sdc_doc:
                        sdc_name = _sta_local_name(sdc_doc, "chipsutra.sdc")
                        sdc_text = _get_file_text(sdc_doc)
                    else:
                        sdc_name = "chipsutra.sdc"
                        sdc_text = default_sdc_stub(inp.clock_name or "clk", float(inp.period_ns or 10.0))
                        msg = f"[sta] No SDC supplied — generated a default stub ({inp.clock_name} @ {inp.period_ns}ns)"
                        logs.append(msg)
                        yield f"data: {json.dumps({'type':'log','level':'info','line':msg})}\n\n"
                    sdc_path = os.path.join(tmp, sdc_name)
                    with open(sdc_path, "w", encoding="utf-8") as fh:
                        fh.write(sdc_text)
                    written.append(sdc_path)

                    tcl = build_sta_tcl(
                        netlist=netlist_name,
                        liberty=liberty_name,
                        sdc=sdc_name,
                        top=top,
                        max_paths=max(1, int(inp.max_paths or 10)),
                    )
                    tcl_name = "chipsutra_sta.tcl"
                    with open(os.path.join(tmp, tcl_name), "w", encoding="utf-8") as fh:
                        fh.write(tcl)
                    cmd = sta_command(tcl_name)
                    manifest = build_manifest(
                        engine="opensta",
                        mode="sta",
                        command=cmd,
                        top_module=top,
                        file_hashes=sha256_paths(written),
                        extra={"netlist": netlist_name, "liberty": liberty_name, "sdc": sdc_name},
                    )
                    logs.append("$ " + " ".join(cmd))
                    yield f"data: {json.dumps({'type':'log','level':'info','line':logs[-1]})}\n\n"
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        cwd=tmp,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    assert proc.stdout is not None
                    async for raw, timed_out in _stream_with_timeout(proc, 300.0):
                        line = raw.decode("utf-8", errors="ignore").rstrip()
                        if line:
                            logs.append(line)
                            level = "error" if "error" in line.lower() else "info"
                            yield f"data: {json.dumps({'type':'log','level':level,'line':line})}\n\n"
                        if timed_out:
                            logs.append("OpenSTA timed out after 300s")
                            break
                    rc = await proc.wait()
                    stats = parse_sta_log("\n".join(logs))
                    status = "done" if rc == 0 and not stats.get("errors") else "error"
                    await db.sta_runs.update_one(
                        {"id": run_id},
                        {"$set": {"manifest": manifest, "stats": stats, "top_module": top}},
                    )
                except Exception as e:
                    logs.append(str(e))
                    yield f"data: {json.dumps({'type':'log','level':'error','line':str(e)})}\n\n"

        yield f"data: {json.dumps({'type':'stats','stats':stats,'note':note})}\n\n"
        await db.sta_runs.update_one(
            {"id": run_id},
            {"$set": {
                "status": status,
                "log": "\n".join(logs),
                "stats": stats,
                "top_module": top,
                "note": note,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        yield f"data: {json.dumps({'type':'done','status':status,'sta_id':run_id,'stats':stats,'note':note})}\n\n"

    return StreamingResponse(
        evgen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/projects/{pid}/sta-runs")
async def list_sta_runs(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    return await db.sta_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(30)


# ---- CDC / RDC analyzer (heuristic + optional Yosys JSON) ----
class CdcIn(BaseModel):
    project_id: str
    rtl_file_ids: List[str] = Field(default_factory=list)
    engine: str = "auto"  # auto | heuristic | yosys-json | deep
    top_module: Optional[str] = None


@api.post("/cdc/analyze")
async def cdc_analyze(inp: CdcIn, user=Depends(get_current_user)):
    await require_project(inp.project_id, user["id"], "editor")
    if not inp.rtl_file_ids:
        raise HTTPException(400, "Provide at least one RTL file")
    if inp.engine not in ("auto", "heuristic", "yosys-json", "deep"):
        raise HTTPException(400, "engine must be auto, heuristic, yosys-json, or deep")
    fdocs = await db.files.find(
        {"id": {"$in": inp.rtl_file_ids}, "project_id": inp.project_id, "is_deleted": {"$ne": True}},
        {"_id": 0},
    ).to_list(50)
    files = []
    for f in fdocs:
        text = _get_file_text(f)
        if text:
            files.append((f.get("original_filename") or f["id"], text))
    heuristic = analyze_rtl_texts(files)
    structural = None
    note = None
    used_engine = "heuristic"

    deep = None
    if inp.engine in ("auto", "deep") and files:
        try:
            deep = analyze_deep(files)
        except Exception as e:
            deep = None
            note = f"Deep CDC engine failed ({e}); using heuristic findings only"

    want_yosys = inp.engine in ("auto", "yosys-json")
    if want_yosys and YOSYS_BIN and files:
        try:
            with tempfile.TemporaryDirectory(prefix="chipsutra_cdc_") as tmp:
                written = await _write_files_to_dir(inp.rtl_file_ids, inp.project_id, tmp)
                if not written:
                    raise RuntimeError("No readable RTL for Yosys CDC")
                top = inp.top_module
                if not top:
                    with open(written[0], encoding="utf-8", errors="ignore") as fh:
                        top = _extract_top_module(fh.read())
                if not top:
                    raise RuntimeError("top module not detected for Yosys CDC")
                basenames = [os.path.basename(p) for p in written]
                script = synth_script(top, basenames, write_verilog=False)
                ys = os.path.join(tmp, "cdc.ys")
                with open(ys, "w", encoding="utf-8") as fh:
                    fh.write(script)
                proc = await asyncio.create_subprocess_exec(
                    YOSYS_BIN, "-s", "cdc.ys",
                    cwd=tmp,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                assert proc.stdout is not None
                out_lines = []
                async for raw, timed_out in _stream_with_timeout(proc, 90.0):
                    if timed_out:
                        raise RuntimeError("Yosys CDC synth timed out")
                    if raw:
                        out_lines.append(raw.decode("utf-8", errors="ignore"))
                rc = await proc.wait()
                json_path = os.path.join(tmp, "synth.json")
                if rc != 0 or not os.path.isfile(json_path):
                    raise RuntimeError("Yosys did not produce synth.json for CDC")
                with open(json_path, encoding="utf-8", errors="ignore") as fh:
                    structural = analyze_yosys_json(fh.read(), filename="synth.json")
                used_engine = "yosys-json"
        except Exception as e:
            note = f"Yosys-JSON CDC unavailable ({e}); using heuristic only"
            structural = None
            used_engine = "heuristic"
            if inp.engine == "yosys-json":
                # still return heuristic with clear fallback rather than hard-fail
                note = f"Requested yosys-json failed: {e}. Fell back to heuristic."
    elif want_yosys and not YOSYS_BIN:
        note = "Yosys not on PATH — CDC used heuristic engine only"
        if inp.engine == "yosys-json":
            note = "Yosys not on PATH; fell back to heuristic CDC"

    if inp.engine == "heuristic":
        result = heuristic
        used_engine = "heuristic"
    elif structural and inp.engine == "yosys-json":
        result = structural
        used_engine = "yosys-json"
    elif structural:
        result = merge_cdc_results(heuristic, structural)
        used_engine = "merged"
    else:
        result = heuristic
        used_engine = "heuristic"

    if deep is not None:
        result = merge_deep(result, deep)
        used_engine = "deep" if used_engine == "heuristic" else f"{used_engine}+deep"

    result = dict(result)
    result["requested_engine"] = inp.engine
    result["engine_used"] = used_engine
    if note:
        result["note"] = note

    run_id = str(uuid.uuid4())
    doc = {
        "id": run_id,
        "project_id": inp.project_id,
        "user_id": user["id"],
        **result,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.cdc_runs.insert_one(doc)
    result["cdc_run_id"] = run_id
    return result


@api.get("/projects/{pid}/cdc")
async def list_cdc_runs(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    return await db.cdc_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(30)

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
