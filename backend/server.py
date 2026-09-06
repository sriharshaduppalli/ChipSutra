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
import shutil
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
from tb_skeleton import (
    should_use_tb_skeleton,
    render_randomized_tb,
    render_class_sv_tb,
)
from tb_uvm_skeleton import render_uvm_smoke_tb
from design_analyze import analyze_design, analysis_to_learning, build_tb_context_pack
from tb_lint import (
    choose_testbench_output,
    lint_testbench,
    extract_sv,
    stamp_tb_header,
    truncate_tb_reference,
)
from kg_rating import auto_score_testbench, combine_with_feedback, aggregate_learning_report
from dv_planner import plan_generation, plan_to_learning
from dv_user_config import (
    parse_dv_config,
    prompt_block as dv_config_prompt_block,
    attach_knobs,
    merge_with_design,
    example_config as dv_example_config,
)
from tb_ral import ral_prompt_block, normalize_csr_list
from generation_persist import generation_artifact_meta
from dv_verify import verify_testbench, verify_status_for_learning, verilator_bin
from llm_router import resolve_model, prewarm_ollama, prewarm_status
from spec_checklist import (
    analyze_spec,
    checklist_prompt_block,
    exploratory_stub_rtl,
    spec_gate_blocks,
)
from spec_ir import extract_spec_ir, spec_ir_prompt_block
from debug_classify import classify_log, debug_prompt_block
from closed_loop import run_closed_loop
from evidence_pack import evidence_zip_bytes
from signoff import build_signoff_board
from tb_methodology import (
    normalize_methodology,
    is_class_methodology,
    methodology_prompt_block,
    LABELS as TB_METH_LABELS,
)

from opensta_flow import (
    sta_bin,
    sta_command,
    build_sta_tcl,
    liberty_is_plausible,
    parse_sta_log,
    default_sdc_stub,
    demo_liberty_path,
)
from lab_flow import (
    classify_hdl_files,
    plan_lab_stages,
    stage_failed,
    pipeline_status,
    run_verible_lint,
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

# Public / multi-user portal mode: tighter defaults for abuse + sim honesty
PUBLIC_MODE = os.environ.get("CHIPSUTRA_PUBLIC_MODE", "false").lower() in (
    "1",
    "true",
    "yes",
)
# Free-tier quota: N generations per user per day (0 = unlimited lab mode)
_quota_default = "50" if PUBLIC_MODE else "0"
FREE_DAILY_QUOTA = int(os.environ.get("FREE_DAILY_QUOTA", _quota_default))
# Set REQUIRE_EMAIL_VERIFICATION=true to block generation for unverified emails
REQUIRE_EMAIL_VERIFICATION = os.environ.get(
    "REQUIRE_EMAIL_VERIFICATION", "true" if PUBLIC_MODE else "false"
).lower() == "true"
# Refuse mock Verilator success in public mode (default on when PUBLIC_MODE)
REFUSE_MOCK_SIM = os.environ.get(
    "CHIPSUTRA_REFUSE_MOCK_SIM", "true" if PUBLIC_MODE else "false"
).lower() in ("1", "true", "yes")
_WEAK_JWT = frozenset({"", "dev-secret", "change-me", "secret", "changeme"})

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

_cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000" if PUBLIC_MODE else "*")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
if PUBLIC_MODE and ("*" in _cors_origins or not _cors_origins):
    logger.warning(
        "CHIPSUTRA_PUBLIC_MODE=true but CORS_ORIGINS is open/empty — "
        "pin to your portal origin(s)"
    )
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _assert_jwt_safe_for_public() -> None:
    secret = (JWT_SECRET or "").strip()
    if not PUBLIC_MODE:
        if secret.lower() in _WEAK_JWT or len(secret) < 16:
            logger.warning(
                "JWT_SECRET is weak/default — fine for local lab; "
                "set a strong secret before any shared deploy"
            )
        return
    if secret.lower() in _WEAK_JWT or len(secret) < 32:
        raise RuntimeError(
            "CHIPSUTRA_PUBLIC_MODE requires a strong JWT_SECRET "
            "(>=32 chars, not 'dev-secret'). "
            "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
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
    model_name: str = "chipsutra-vlsi:7b"
    prompt: Optional[str] = ""
    file_ids: Optional[List[str]] = []
    language: Optional[str] = "systemverilog"
    # Closed-loop: paste Verilator/sim log (+ optional prior code) to regenerate/fix
    tool_log: Optional[str] = None
    prior_output: Optional[str] = None
    # testbench path: auto (skeleton-first) | skeleton | llm
    gen_mode: Optional[str] = "auto"
    # testbench methodology: sv | uvm | ovm | vmm (default pure SV)
    tb_methodology: Optional[str] = "sv"
    # Optional user DV knobs: scale, protocol_knobs, memory_map, csr_list, topology
    dv_config: Optional[dict] = None

MODULE_PROMPTS = {
    "testbench": (
        "You are an expert VLSI verification engineer. Generate a Verilator-friendly "
        "SystemVerilog testbench for the provided RTL in {language}. "
        "Default: layered Pure SV (interface, generator, driver, monitor, scoreboard, env, test). "
        "UVM only when methodology=uvm. Exact DUT ports; independent golden; "
        "$dumpfile/$dumpvars/$finish. Never invent ports. Output ONLY SystemVerilog."
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
    _assert_jwt_safe_for_public()
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
    asyncio.create_task(_warm_rag_index())


async def _warm_rag_index():
    try:
        import rag_vector

        await asyncio.to_thread(rag_vector.warm_index)
        logger.info("RAG vector index warm: %s", rag_vector.rag_vector_status().get("backend"))
    except Exception as e:
        logger.debug("RAG vector warm skipped: %s", e)

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
        "iverilog": bool(_sh.which("iverilog")),
        "verible": bool(_sh.which("verible-verilog-lint")),
        "slang": bool(_sh.which("slang")),
        "opensta": bool(sta_bin()),
        "fst": fst_status(),
        "rate_limit": rate_limit_status(),
        "llm_providers": providers,
        "ollama": llm_ollama_status(),
        "rag": llm_rag_status(),
        "rtl_ports": rtl_ports_status(),
        "lint_feedback": lint_feedback_status(),
        "asfigo": __import__("asfigo_bridge").tool_status(),
        "eda_tools": tool_versions(),
        "cdc": {"engine": "chipsutra-cdc-v0|v1-yosys", "status": "experimental"},
        "google_auth": google_mode(),
        "llm_router": {
            "prewarm": prewarm_status(),
            "verilator": bool(verilator_bin()),
        },
        "public_mode": PUBLIC_MODE,
        "free_daily_quota": FREE_DAILY_QUOTA,
        "refuse_mock_sim": REFUSE_MOCK_SIM,
    }

# =========================
# Auth endpoints
# =========================
@api.post("/auth/register")
async def register(inp: RegisterIn, request: Request):
    _rate_limit(f"register:{_client_ip(request)}", max_calls=10, window_s=600)
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
async def login(inp: LoginIn, request: Request):
    _rate_limit(f"login:{_client_ip(request)}", max_calls=30, window_s=300)
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
async def waitlist(inp: WaitlistIn, request: Request):
    _rate_limit(f"waitlist:{_client_ip(request)}", max_calls=20, window_s=3600)
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
async def contact(inp: ContactIn, request: Request):
    _rate_limit(f"contact:{_client_ip(request)}", max_calls=20, window_s=3600)
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


@api.post("/projects/quickstart")
async def quickstart_counter(user=Depends(get_current_user)):
    """First-project wizard: create a project and import the golden counter DUT."""
    pid = str(uuid.uuid4())
    doc = {
        "id": pid,
        "user_id": user["id"],
        "workspace_id": None,
        "name": "First project — counter",
        "description": "60-second wizard: golden counter.sv → Generate testbench → Simulate.",
        "design_type": "block",
        "language": "systemverilog",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "wizard": True,
    }
    await db.projects.insert_one(doc)
    path = GOLDEN_DIR / "counter.sv"
    if not path.is_file():
        raise HTTPException(404, "Golden counter.sv missing from this install")
    saved = await _persist_project_text_file(
        project_id=pid,
        filename="counter.sv",
        content=path.read_text(encoding="utf-8"),
        kind="rtl",
        content_type="text/plain",
    )
    doc.pop("_id", None)
    return {
        "project": doc,
        "files": [saved],
        "steps": [
            "Select counter.sv",
            "Generate → Testbench (Pure SV)",
            "Simulate (Verilator)",
        ],
    }

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
async def generate_stream(
    inp: GenerateIn,
    request: Request,
    user=Depends(get_current_user),
):
    _rate_limit(f"generate:{user['id']}", max_calls=40, window_s=3600)
    _rate_limit(f"generate_ip:{_client_ip(request)}", max_calls=80, window_s=3600)
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
            _rtl_cap = (
                4000
                if inp.module == "testbench"
                else 8000
                if inp.module in ("assertions", "covergroups", "checkers")
                else 20000
            )
            file_context += (
                f"\n\n--- FILE: {f['original_filename']} (kind={f.get('kind','')}) ---\n"
                f"{text[:_rtl_cap]}\n"
            )
        else:
            missing_content.append(f.get("original_filename") or f.get("id") or "file")

    lang = inp.language or proj.get("language", "systemverilog")
    system_msg = MODULE_PROMPTS[inp.module].format(language=lang)
    system_msg += "\n\nYou are ChipSutra, an EDA verification assistant. Be concise, precise, and technical."
    # RAG injected after DV plan (adaptive top_k for simple DUTs — G10 latency).

    port_block = extract_port_context_from_texts(file_bodies)
    if port_block:
        system_msg += "\n\n--- Parsed RTL interfaces ---\n" + port_block

    extra_rules = rules_for_module(
        inp.module,
        has_ports=bool(port_block),
        tb_methodology=inp.tb_methodology or "sv",
    )
    if extra_rules:
        system_msg += "\n\n" + extra_rules

    tb_meth = normalize_methodology(inp.tb_methodology or "sv", prompt=inp.prompt or "")
    if inp.module == "testbench":
        system_msg += "\n\n" + methodology_prompt_block(tb_meth)
        # Soften MODULE_PROMPTS default when class methodology selected
        if is_class_methodology(tb_meth):
            system_msg += (
                f"\nUser selected methodology={tb_meth} ({TB_METH_LABELS.get(tb_meth, tb_meth)}). "
                "Do not emit a pure SV Fast-random TB unless explicitly asked."
            )

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
        user_text = default_user_prompt(inp.module, dut_hint=dut_hint, tb_methodology=tb_meth)
    if file_context:
        user_text += "\n\n" + file_context
    if inp.tool_log:
        user_text += "\n\n" + format_lint_feedback(inp.tool_log, prior_code=inp.prior_output)

    dv_cfg = parse_dv_config(inp.dv_config, prompt=inp.prompt or "")
    dv_cfg = merge_with_design(
        dv_cfg,
        parsed_modules,
        rtl_text="\n".join(file_bodies[:3]) if file_bodies else "",
        tb_methodology=tb_meth if inp.module == "testbench" else "sv",
    )
    if parsed_modules:
        attach_knobs(parsed_modules[0], dv_cfg)

    dv_plan = plan_generation(
        module=inp.module,
        prompt=inp.prompt or "",
        tool_log=inp.tool_log or "",
        gen_mode=inp.gen_mode or "auto",
        tb_methodology=tb_meth if inp.module == "testbench" else "sv",
        modules=parsed_modules,
        rtl_text="\n".join(file_bodies[:3]),
        user_config=dv_cfg,
    )

    # Design analysis FIRST — tight context pack (brief + VIP), not a knowledge dump
    design_analysis = None
    if inp.module == "testbench" and parsed_modules:
        design_analysis = analyze_design(
            parsed_modules,
            rtl_text="\n".join(file_bodies[:3]),
            tb_methodology=tb_meth,
            prompt=inp.prompt or "",
            user_config=dv_cfg,
        )
        pack = build_tb_context_pack(design_analysis, max_chars=4000, vip_chars=2000)
        if pack:
            system_msg += "\n\n" + pack
        dv_plan = dict(dv_plan)
        dv_plan["design_analysis"] = analysis_to_learning(design_analysis)
        if design_analysis.get("protocol_variant"):
            dv_plan["protocol_variant"] = design_analysis["protocol_variant"]
        cfg_block = dv_config_prompt_block(dv_cfg)
        if cfg_block:
            system_msg += "\n\n" + cfg_block
        ral_block = ral_prompt_block(
            normalize_csr_list(dv_cfg.get("csr_list") or []),
            methodology=tb_meth,
            enable_ral=bool(dv_cfg.get("enable_ral")),
        )
        if ral_block:
            system_msg += "\n\n" + ral_block

    # Adaptive RAG: protocol-routed, small budget (VIP already in analysis pack)
    _simple_proto = {
        "counter", "parity", "mux", "alu", "shifter", "edge", "cdc",
        "encoder", "gray", "debounce", "pwm", "generic", "switch",
    }
    _proto = (
        (design_analysis or {}).get("protocol")
        or dv_plan.get("protocol_pack")
        or "generic"
    ).lower()
    _variant = ((design_analysis or {}).get("protocol_variant") or "").lower()
    if inp.module == "testbench":
        _rag_k = 1 if _proto in _simple_proto else 2
        _rag_chars = 1800 if _proto in _simple_proto else 2800
        if tb_meth == "uvm":
            _rag_k = max(_rag_k, 2)
            _rag_chars = max(_rag_chars, 2400)
    elif inp.module in ("assertions", "covergroups", "checkers"):
        _rag_k, _rag_chars = 2, 2800
    else:
        _rag_k, _rag_chars = 3, 3200
    rag_block = augment_generation_context(
        module=inp.module,
        prompt=(inp.prompt or "") + " " + file_context[:800],
        filenames=file_names,
        top_k=_rag_k,
        protocol=_proto,
        protocol_variant=_variant,
        methodology=tb_meth if inp.module == "testbench" else "",
        max_chars=_rag_chars,
    )
    if rag_block:
        system_msg += (
            "\n\n--- Retrieved knowledge (secondary; RTL/analysis override) ---\n"
            + rag_block
        )
    try:
        from asfigo_packs import prompt_block as _asfigo_pack_prompt
        _pack = _asfigo_pack_prompt(module=inp.module)
        if _pack:
            system_msg += "\n\n" + _pack
    except Exception:
        pass
    if dv_cfg.get("enable_ral") and inp.module == "testbench":
        ral_rag = augment_generation_context(
            module=inp.module,
            prompt="RAL uvm_reg_block user CSR map",
            filenames=file_names,
            top_k=2,
            protocol="ral",
            protocol_variant="uvm_ral" if tb_meth == "uvm" else "ral",
            methodology=tb_meth,
            max_chars=1600,
        )
        if ral_rag:
            system_msg += "\n\n--- RAL knowledge (user map only) ---\n" + ral_rag
    _scale = (dv_cfg.get("scale") or "block").lower()
    if inp.module == "testbench" and _scale not in ("block", ""):
        scale_rag = augment_generation_context(
            module=inp.module,
            prompt=f"scale {_scale} testbench orchestration topology",
            filenames=file_names,
            top_k=2,
            protocol=_scale,
            protocol_variant=_scale,
            methodology=tb_meth,
            max_chars=1400,
        )
        if scale_rag:
            system_msg += f"\n\n--- Scale knowledge ({_scale}) ---\n" + scale_rag

    spec_analysis = None
    spec_ir = None
    debug_analysis = None
    if inp.module == "spec2rtl":
        spec_blob = (inp.prompt or "") + "\n" + file_context[:8000]
        spec_analysis = analyze_spec(spec_blob, prompt=inp.prompt or "")
        spec_ir = extract_spec_ir(spec_blob, prompt=inp.prompt or "")
        block = checklist_prompt_block(spec_analysis)
        ir_block = spec_ir_prompt_block(spec_ir)
        if block:
            system_msg += "\n\n" + block
            if not spec_analysis.get("ready"):
                user_text += (
                    "\n\n[ChipSutra] Spec checklist incomplete — generate exploratory RTL with "
                    "documented // assumptions for missing clock/reset/I/O."
                )
        if ir_block:
            system_msg += "\n\n" + ir_block
    if inp.module == "debug" or (inp.tool_log or "").strip():
        debug_analysis = classify_log(inp.tool_log or "", prior_code=inp.prior_output or "")
        dblock = debug_prompt_block(debug_analysis)
        if dblock and (inp.module == "debug" or (inp.tool_log or "").strip()):
            system_msg += "\n\n" + dblock

    protocol_pack = dv_plan.get("protocol_pack") or "generic"
    cycles = 32
    seed = 1
    m_cyc = re.search(r"\bcycles\s*=\s*(\d+)\b", inp.prompt or "", re.I)
    m_seed = re.search(r"\bseed\s*=\s*(\d+)\b", inp.prompt or "", re.I)
    if m_cyc:
        cycles = int(m_cyc.group(1))
    if m_seed:
        seed = int(m_seed.group(1))

    # Product intent: ALWAYS call the LLM for testbench. Templates are STYLE HINTS only.
    # UVM: DUT-correct smoke skeleton is also the lint fallback when LLM fails hard.
    skeleton_sv = ""
    template_engine = ""
    ref_tb = ""
    hint_tb = ""
    gen_mode_l = (inp.gen_mode or "auto").lower().strip()
    if inp.module == "testbench" and parsed_modules and parsed_modules[0].get("ports"):
        ref_tb = render_randomized_tb(parsed_modules[0], cycles=max(cycles, 48), seed=seed)
        if tb_meth == "sv" and gen_mode_l in ("skeleton", "fast", "template", "smoke"):
            hint_tb = ref_tb
            style = "procedural_smoke"
        elif tb_meth == "sv":
            hint_tb = render_class_sv_tb(parsed_modules[0], cycles=cycles, seed=seed)
            # Bus Pure-SV: procedural smoke has proven AXI/APB handshakes for sim gate.
            _bus_proto = (
                (design_analysis or {}).get("protocol")
                or protocol_pack
                or ""
            ).lower()
            if _bus_proto in ("axi_lite", "axi4_lite", "axi", "apb", "apb3", "apb4"):
                skeleton_sv = ref_tb  # render_randomized_tb — VIP handshake + model_reg
            else:
                skeleton_sv = hint_tb
            style = "class_sv"
        elif tb_meth == "uvm":
            hint_tb = render_uvm_smoke_tb(parsed_modules[0], cycles=cycles)
            skeleton_sv = hint_tb  # DUT-correct fallback for choose_testbench_output
            style = "uvm"
        else:
            style = tb_meth

        port_names = [
            p.get("name") for p in (parsed_modules[0].get("ports") or []) if p.get("name")
        ]
        golden_hint = tb_golden_hint_from_ports(port_names)
        # Simple DUTs: short outline only (full gold/skeleton in prompt = multi-minute CPU TTFT).
        # Bus protocols: optional full golden few-shot.
        try:
            from generation_rules import golden_ref_for_protocol, style_ref_for_protocol

            golden_ref = golden_ref_for_protocol(protocol_pack)
            ref_compact = style_ref_for_protocol(
                protocol_pack, hint_tb, max_lines=40, methodology=tb_meth
            )
        except Exception:
            golden_ref = ""
            ref_compact = truncate_tb_reference(hint_tb, max_lines=40) if hint_tb else ""
        if golden_ref and tb_meth == "sv":
            ref_compact = (
                "GOLD reference TB for this protocol class (adapt module/port names "
                "to THIS DUT exactly):\n" + golden_ref
            )

        if is_class_methodology(tb_meth):
            shape = (
                (design_analysis or {}).get("recommendation") or {}
            ).get("tb_shape") or "uvm_smoke"
            variant = (design_analysis or {}).get("protocol_variant") or protocol_pack
            prefix = (
                f"Generate a {tb_meth.upper()} testbench via ChipSutra-VLSI LLM. "
                f"First follow DESIGN ANALYSIS above (protocol={protocol_pack}, "
                f"variant={variant}, shape={shape}). "
                f"Golden/port hint: {golden_hint}. "
                f"Methodology: {TB_METH_LABELS.get(tb_meth, tb_meth)}. "
                "MUST include: DUT instance + interface + uvm_config_db set + run_test(); "
                "scoreboard uvm_analysis_imp + write(); TLM only in connect_phase; "
                "phase.raise_objection in test. "
                "Copy ChipVerify first-TB wiring: monitor extends uvm_monitor (NOT uvm_subscriber); "
                "drv.seq_item_port.connect(sqr.seq_item_export); mon.ap.connect(sb.imp); "
                "sequence class with task body() — never uvm_sequence#(T) seq=new(). "
                "Real UVM only — not Pure-SV $urandom smoke.\n"
            )
            if ref_compact and tb_meth == "uvm":
                # Keep skeleton compact — VIP rules already in DESIGN ANALYSIS pack
                prefix += (
                    "DUT-correct UVM STYLE skeleton (adapt golden/predict; keep top structure):\n"
                    f"{ref_compact}\n\n"
                )
            else:
                prefix += "\n"
        elif style == "procedural_smoke":
            prefix = (
                "Generate a procedural Pure SV smoke testbench via LLM (NO UVM). "
                f"Golden/port hint: {golden_hint}. "
                "YOU write the code; use this only as STYLE/port guidance:\n"
                f"{ref_compact}\n\n"
            )
        else:
            prefix = (
                "Generate a LAYERED Pure SystemVerilog testbench via LLM "
                "(NO uvm_*/ovm_*/vmm_*). Required components: interface, generator, "
                "driver, monitor, scoreboard, environment, test, and top "
                "(mailboxes + virtual interface; NOT txn+scoreboard-only). "
                f"Golden/port hint: {golden_hint}.\n"
            )
            if ref_compact:
                prefix += (
                    "Structural STYLE reference (adapt to this DUT; do not paste blindly):\n"
                    f"{ref_compact}\n\n"
                )
        user_text = prefix + "User request:\n" + user_text

    session_id = str(uuid.uuid4())
    gen_id = str(uuid.uuid4())
    route = resolve_model(
        provider=inp.model_provider or "ollama",
        requested_model=inp.model_name or "",
        model_tier=(dv_plan.get("model_tier") or "3b"),
    )
    resolved_provider = route.get("provider") or inp.model_provider
    resolved_model = route.get("model") or inp.model_name
    emit_engine = "llm"
    emit_model = resolved_model
    gen_doc = {
        "id": gen_id,
        "project_id": inp.project_id,
        "user_id": user["id"],
        "module": inp.module,
        "provider": resolved_provider,
        "model": resolved_model,
        "prompt": inp.prompt or "",
        "file_ids": inp.file_ids or [],
        "output": "",
        "status": "streaming",
        "engine": "llm",
        "router": route,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.generations.insert_one(gen_doc)

    async def event_gen():
        _plan_learn = plan_to_learning(dv_plan)
        if design_analysis is not None:
            _plan_learn["design_analysis"] = analysis_to_learning(design_analysis)
        yield f"data: {json.dumps({'type': 'meta', 'generation_id': gen_id, 'engine': 'llm', 'tb_methodology': tb_meth if inp.module == 'testbench' else None, 'router': route, 'plan': _plan_learn})}\n\n"
        if design_analysis is not None:
            _da = design_analysis
            _rec = _da.get("recommendation") or {}
            yield "data: " + json.dumps({
                "type": "progress",
                "stage": "design_analysis",
                "message": (
                    f"Analyzed DUT: protocol={_da.get('protocol')} "
                    f"variant={_da.get('protocol_variant')} "
                    f"timing={_da.get('timing_style')} → "
                    f"{_rec.get('methodology')}/{_rec.get('tb_shape')}"
                ),
                "protocol": _da.get("protocol"),
                "protocol_variant": _da.get("protocol_variant"),
                "timing_style": _da.get("timing_style"),
                "tb_shape": _rec.get("tb_shape"),
                "brief": (_da.get("brief") or "")[:800],
            }) + "\n\n"
        if spec_analysis is not None:
            _spec_msg = (
                f"Spec checklist: {spec_analysis.get('grade')} "
                f"(score={spec_analysis.get('score')})"
            )
            yield "data: " + json.dumps({
                "type": "progress",
                "stage": "spec_checklist",
                "message": _spec_msg,
                "grade": spec_analysis.get("grade"),
                "ready": spec_analysis.get("ready"),
            }) + "\n\n"
        if debug_analysis is not None and not debug_analysis.get("empty"):
            yield "data: " + json.dumps({
                "type": "progress",
                "stage": "debug_classify",
                "message": debug_analysis.get("summary"),
                "top_category": debug_analysis.get("top_category"),
            }) + "\n\n"
        accumulated = []
        try:
            raw_chunks: List[str] = []
            ntok = 0
            streamed = 0
            cancelled = False
            skip_llm = False
            raw = ""
            final = ""
            engine_tag = "llm"
            issues: List[str] = []
            if inp.module == "testbench" and skeleton_sv and parsed_modules:
                try:
                    from tb_skeleton import prefer_known_golden_skeleton

                    skip_llm = prefer_known_golden_skeleton(
                        gen_mode=gen_mode_l,
                        tb_methodology=tb_meth,
                        parsed_module=parsed_modules[0],
                        prompt=inp.prompt or "",
                    )
                except Exception:
                    skip_llm = False

            if inp.module == "spec2rtl" and spec_analysis is not None and spec_gate_blocks(spec_analysis):
                skip_llm = True
                final = exploratory_stub_rtl(spec_analysis, prompt=inp.prompt or "")
                engine_tag = "spec_gate"

            async def _client_gone():
                return await request.is_disconnected()

            if skip_llm:
                if engine_tag == "spec_gate":
                    yield "data: " + json.dumps({
                        "type": "progress",
                        "stage": "spec_gate",
                        "message": (
                            "Spec incomplete (clock/reset/I/O) — emitting exploratory stub. "
                            "Set CHIPSUTRA_SPEC_GATE=0 to force LLM."
                        ),
                        "grade": (spec_analysis or {}).get("grade"),
                    }) + "\n\n"
                else:
                    yield "data: " + json.dumps({
                        "type": "progress",
                        "stage": "skeleton",
                        "message": (
                            "DUT-matched golden skeleton (skipped LLM — faster and lint-clean). "
                            "Set gen_mode=llm to force chipsutra-vlsi."
                        ),
                    }) + "\n\n"
                    final = skeleton_sv
                    engine_tag = "skeleton"
            else:
                yield "data: " + json.dumps({
                    "type": "progress",
                    "stage": "llm",
                    "message": (
                        f"Calling {resolved_model}… "
                        "(unknown/generic DUT: LLM + skeleton floor; time-boxed)"
                    ),
                    "model": resolved_model,
                }) + "\n\n"
                try:
                    async for delta in llm_stream_chat(
                        provider=resolved_provider,
                        model=resolved_model,
                        system=system_msg,
                        user_text=user_text,
                        session_id=session_id,
                        num_predict=num_predict_for_module(
                            inp.module,
                            tb_methodology=tb_meth,
                            protocol=(dv_plan.get("protocol_pack") or "generic"),
                        ),
                        cancel_check=_client_gone,
                    ):
                        if await request.is_disconnected():
                            cancelled = True
                            break
                        raw_chunks.append(delta)
                        ntok += 1
                        accumulated.append(delta)
                        yield "data: " + json.dumps({"type": "delta", "content": delta}) + "\n\n"
                        streamed += 1
                        if ntok == 1 or ntok % 24 == 0:
                            yield "data: " + json.dumps({
                                "type": "progress",
                                "stage": "llm",
                                "message": f"Generating… ({ntok} chunks)",
                                "chunks": ntok,
                            }) + "\n\n"
                except Exception as llm_err:
                    if inp.module == "testbench" and skeleton_sv:
                        logger.warning("LLM generate failed; using skeleton: %s", llm_err)
                        yield "data: " + json.dumps({
                            "type": "progress",
                            "stage": "skeleton",
                            "message": f"LLM timed out or failed ({type(llm_err).__name__}); using DUT skeleton.",
                        }) + "\n\n"
                        final = skeleton_sv
                        engine_tag = "skeleton_fallback"
                        issues = ["llm_timeout_or_error"]
                    else:
                        raise
                else:
                    if cancelled or await request.is_disconnected():
                        await db.generations.update_one(
                            {"id": gen_id},
                            {"$set": {"status": "cancelled", "error": "client_disconnected"}},
                        )
                        yield f"data: {json.dumps({'type': 'error', 'error': 'client_disconnected'})}\n\n"
                        return
                    raw = "".join(raw_chunks)
                    final = raw
                    engine_tag = "llm"
            sva_learning: Optional[dict] = None
            checker_learning: Optional[dict] = None
            fcov_learning: Optional[dict] = None
            fpga_learning: Optional[dict] = None
            soft_gate: Optional[dict] = None
            dut_outs: List[str] = []
            if parsed_modules:
                for p in parsed_modules[0].get("ports") or []:
                    d = (p.get("direction") or "").lower()
                    n = p.get("name")
                    if n and d in ("output", "out", "inout"):
                        dut_outs.append(n)
            if inp.module == "testbench" and engine_tag not in ("skeleton", "skeleton_fallback"):
                ports = [
                    p.get("name")
                    for p in (parsed_modules[0].get("ports") or [])
                    if p.get("name")
                ] if parsed_modules else []
                port_specs = list((parsed_modules[0].get("ports") or [])) if parsed_modules else []
                protocol_name = (dv_plan.get("protocol_pack") or protocol_pack or "generic")
                yield "data: " + json.dumps({
                    "type": "progress",
                    "stage": "lint",
                    "message": f"Quality-gating {tb_meth.upper()} LLM TB (lint/repair — no template replace)…",
                }) + "\n\n"
                # LLM-first; UVM may fall back to DUT-correct smoke skeleton if lint fails hard.
                final, engine_tag, issues = choose_testbench_output(
                    raw,
                    skeleton=skeleton_sv,
                    dut_name=(parsed_modules[0].get("name") if parsed_modules else None),
                    required_ports=ports if tb_meth == "sv" else None,
                    dut_outputs=dut_outs or None,
                    force_uvm=is_class_methodology(tb_meth),
                    protocol=protocol_name,
                    port_specs=port_specs or None,
                )
                final = extract_sv(final) or final
                # Second-pass LLM repair when class-SV still below premium bar
                try:
                    from tb_class_lint import score_class_sv_competitive
                    from tb_llm_repair import should_llm_repair, llm_repair_class_sv
                except Exception:
                    score_class_sv_competitive = None  # type: ignore
                    should_llm_repair = None  # type: ignore
                    llm_repair_class_sv = None  # type: ignore
                if (
                    engine_tag not in ("skeleton", "skeleton_fallback")
                    and score_class_sv_competitive
                    and should_llm_repair
                    and llm_repair_class_sv
                    and re.search(r"\bclass\b", final or "")
                    and not re.search(r"\b(uvm_|ovm_|vmm_)", final or "", re.I)
                ):
                    comp0 = score_class_sv_competitive(
                        final,
                        required_ports=ports if tb_meth == "sv" else None,
                        dut_outputs=dut_outs or None,
                        protocol=protocol_name,
                        port_specs=port_specs or None,
                    )
                    if should_llm_repair(
                        issues=issues or comp0.get("issues") or [],
                        competitive_score=comp0.get("score"),
                        premium_bar=bool(comp0.get("premium_bar")),
                    ):
                        yield "data: " + json.dumps({
                            "type": "progress",
                            "stage": "repair",
                            "message": f"LLM self-repair via {resolved_model} (score={comp0.get('score')})…",
                        }) + "\n\n"
                        dut_hint = ""
                        if parsed_modules:
                            dut_hint = str(parsed_modules[0].get("name") or "")
                            if ports:
                                dut_hint += " ports=" + ",".join(ports[:16])
                        repaired_raw, ok_stream = await llm_repair_class_sv(
                            provider=resolved_provider,
                            model=resolved_model,
                            broken_sv=final,
                            issues=issues or comp0.get("issues") or [],
                            dut_hint=dut_hint,
                            session_id=session_id,
                        )
                        if ok_stream and repaired_raw:
                            final2, eng2, issues2 = choose_testbench_output(
                                repaired_raw,
                                skeleton=skeleton_sv,
                                dut_name=(parsed_modules[0].get("name") if parsed_modules else None),
                                required_ports=ports if tb_meth == "sv" else None,
                                dut_outputs=dut_outs or None,
                                force_uvm=is_class_methodology(tb_meth),
                                protocol=protocol_name,
                                port_specs=port_specs or None,
                            )
                            final2 = extract_sv(final2) or final2
                            comp1 = score_class_sv_competitive(
                                final2,
                                required_ports=ports if tb_meth == "sv" else None,
                                dut_outputs=dut_outs or None,
                                protocol=protocol_name,
                                port_specs=port_specs or None,
                            )
                            if (comp1.get("score") or 0) >= (comp0.get("score") or 0):
                                final, engine_tag, issues = final2, "llm_repaired", issues2
                                logger.info(
                                    "LLM repair kept score %s -> %s",
                                    comp0.get("score"),
                                    comp1.get("score"),
                                )
                if engine_tag not in ("llm", "llm_repaired", "skeleton", "skeleton_fallback"):
                    engine_tag = "llm"
                if issues:
                    logger.info("TB lint issues=%s engine=%s (kept LLM output)", issues, engine_tag)
            elif inp.module in ("assertions", "formal_hints"):
                # SVA quality gate (mirror TB lint/repair path, lighter)
                try:
                    from sva_lint import lint_sva, repair_sva, score_sva
                    from tb_lint import extract_sv as _extract_sv

                    ports = [
                        p.get("name")
                        for p in (parsed_modules[0].get("ports") or [])
                        if p.get("name")
                    ] if parsed_modules else []
                    final = _extract_sv(final) or final
                    ok_s, iss_s = lint_sva(final, required_ports=ports or None)
                    if not ok_s or iss_s:
                        clk = "clk"
                        rst = "rst_n"
                        for n in ports or []:
                            nl = n.lower()
                            if nl in ("clk", "aclk", "pclk", "hclk"):
                                clk = n
                            if nl in ("rst_n", "aresetn", "presetn", "hresetn"):
                                rst = n
                        final = repair_sva(
                            final, clk=clk, rst_n=rst, required_ports=ports or None
                        )
                        ok_s, iss_s = lint_sva(final, required_ports=ports or None)
                        engine_tag = "llm_repaired"
                    sva_learning = score_sva(final, required_ports=ports or None)
                    try:
                        from asfigo_bridge import merge_into
                        from asfigo_packs import ft_sva_catalog
                        merge_into(sva_learning, final, kind="svalint")
                        cat = ft_sva_catalog()
                        if cat.get("available"):
                            sva_learning["ft_sva"] = {
                                "chapters": cat.get("chapters"),
                                "examples": (cat.get("examples") or [])[:8],
                            }
                    except Exception:
                        pass
                except Exception:
                    logger.exception("SVA lint failed; keeping raw LLM output")
                    engine_tag = "llm"
            elif inp.module == "covergroups":
                try:
                    from fcov_lint import lint_fcov, repair_fcov, score_fcov
                    from tb_lint import extract_sv as _extract_sv

                    ports = [
                        p.get("name")
                        for p in (parsed_modules[0].get("ports") or [])
                        if p.get("name")
                    ] if parsed_modules else []
                    final = _extract_sv(final) or final
                    ok_f, iss_f = lint_fcov(final, required_ports=ports or None)
                    if not ok_f or iss_f:
                        final = repair_fcov(final)
                        ok_f, iss_f = lint_fcov(final, required_ports=ports or None)
                        engine_tag = "llm_repaired"
                    fcov_learning = score_fcov(final, required_ports=ports or None)
                    try:
                        from asfigo_bridge import merge_into
                        merge_into(fcov_learning, final, kind="fcovlint")
                    except Exception:
                        pass
                except Exception:
                    logger.exception("FCOV lint failed; keeping raw LLM output")
                    engine_tag = "llm"
            elif inp.module == "checkers":
                try:
                    from checker_lint import lint_checker, repair_checker, score_checker
                    from tb_lint import extract_sv as _extract_sv

                    ports = [
                        p.get("name")
                        for p in (parsed_modules[0].get("ports") or [])
                        if p.get("name")
                    ] if parsed_modules else []
                    final = _extract_sv(final) or final
                    ok_c, iss_c = lint_checker(final, required_ports=ports or None)
                    if not ok_c or iss_c:
                        final = repair_checker(final)
                        ok_c, iss_c = lint_checker(final, required_ports=ports or None)
                        engine_tag = "llm_repaired"
                    checker_learning = score_checker(final, required_ports=ports or None)
                except Exception:
                    logger.exception("Checker lint failed; keeping raw LLM output")
                    engine_tag = "llm"
            elif inp.module == "spec2rtl":
                # Gate (G12): incomplete specs emit exploratory stub when CHIPSUTRA_SPEC_GATE is on.
                has_mod = bool(re.search(r"\bmodule\b", final or "", re.I))
                gated = engine_tag == "spec_gate"
                soft_gate = {
                    "module": "spec2rtl",
                    "ok": bool(has_mod and (spec_analysis is None or spec_analysis.get("ready"))),
                    "has_module": has_mod,
                    "spec_ready": (spec_analysis or {}).get("ready"),
                    "grade": (spec_analysis or {}).get("grade"),
                    "gated": gated,
                }
                engine_tag = engine_tag if gated else "llm"
                try:
                    from fpga_lint import lint_fpga, score_fpga
                    from asfigo_bridge import merge_into
                    from asfigo_packs import mathlib_status
                    from tb_lint import extract_sv as _extract_sv

                    body = _extract_sv(final) or final
                    ok_f, iss_f = lint_fpga(body)
                    fpga_learning = score_fpga(body)
                    fpga_learning["ok"] = ok_f
                    fpga_learning["issues"] = iss_f
                    merge_into(fpga_learning, body, kind="fpgalint")
                    ml = mathlib_status()
                    if ml.get("available"):
                        fpga_learning["mathlib"] = {"root": ml.get("root"), "packages": ml.get("packages")}
                except Exception:
                    logger.exception("FPGA lint failed; keeping RTL")
            elif inp.module == "debug":
                soft_gate = {
                    "module": "debug",
                    "ok": bool(
                        debug_analysis
                        and not debug_analysis.get("empty")
                        and debug_analysis.get("top_category")
                    ),
                    "top_category": (debug_analysis or {}).get("top_category"),
                    "summary": (debug_analysis or {}).get("summary"),
                }
                engine_tag = "llm"
            else:
                engine_tag = "llm"
            stamp_engine = (
                engine_tag
                if engine_tag in ("skeleton", "skeleton_fallback", "llm_repaired")
                else "llm"
            )
            final = stamp_tb_header(
                final,
                engine=stamp_engine,
                model=resolved_model or "llm",
                protocol=f"{protocol_pack}/{tb_meth}" if inp.module == "testbench" else protocol_pack,
            )
            gen_doc_engine = stamp_engine
            accumulated = [final]
            yield "data: " + json.dumps({
                "type": "replace",
                "content": final,
                "engine": stamp_engine,
            }) + "\n\n"
            full = "".join(accumulated)
            done_engine = stamp_engine
            if inp.module == "testbench" and not full.startswith("// ChipSutra engine="):
                full = stamp_tb_header(
                    full,
                    engine=stamp_engine,
                    model=resolved_model or "llm",
                    protocol=f"{protocol_pack}/{tb_meth}",
                )
                accumulated = [full]
            learning: dict = {
                "engine": stamp_engine,
                **plan_to_learning(dv_plan),
                "router_reason": route.get("reason"),
                "resolved_model": resolved_model,
            }
            if sva_learning is not None:
                learning["sva"] = sva_learning
                learning["lint_ok"] = sva_learning.get("ok")
                learning["lint_issues"] = sva_learning.get("issues")
                learning["premium_bar"] = sva_learning.get("premium_bar")
            if checker_learning is not None:
                learning["checker"] = checker_learning
                learning["lint_ok"] = checker_learning.get("ok")
                learning["lint_issues"] = checker_learning.get("issues")
                learning["premium_bar"] = checker_learning.get("premium_bar")
            if fcov_learning is not None:
                learning["fcov"] = fcov_learning
                learning["lint_ok"] = fcov_learning.get("ok")
                learning["lint_issues"] = fcov_learning.get("issues")
                learning["premium_bar"] = fcov_learning.get("premium_bar")
            if fpga_learning is not None:
                learning["fpga"] = fpga_learning
            if soft_gate is not None:
                learning["soft_gate"] = soft_gate
            if spec_analysis is not None:
                learning["spec_checklist"] = {
                    "ready": spec_analysis.get("ready"),
                    "grade": spec_analysis.get("grade"),
                    "score": spec_analysis.get("score"),
                    "gaps": (spec_analysis.get("gaps") or [])[:6],
                }
            if spec_ir is not None:
                learning["spec_ir"] = {
                    "port_count": spec_ir.get("port_count"),
                    "requirement_count": spec_ir.get("requirement_count"),
                    "clocks": spec_ir.get("clocks"),
                    "resets": spec_ir.get("resets"),
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
                dut_outs = []
                port_specs = []
                if parsed_modules:
                    dut_name = parsed_modules[0].get("name")
                    ports = [p.get("name") for p in (parsed_modules[0].get("ports") or []) if p.get("name")]
                    port_specs = list(parsed_modules[0].get("ports") or [])
                    for p in parsed_modules[0].get("ports") or []:
                        d = (p.get("direction") or "").lower()
                        n = p.get("name")
                        if n and d in ("output", "out", "inout"):
                            dut_outs.append(n)
                protocol_name = (dv_plan.get("protocol_pack") or protocol_pack or "generic")
                body_sv = extract_sv(full) or full
                is_class_sv = bool(
                    re.search(r"\bclass\b", body_sv)
                    and not re.search(r"\b(uvm_|ovm_|vmm_)", body_sv, re.I)
                )
                if is_class_sv:
                    from tb_class_lint import lint_class_sv_tb, score_class_sv_competitive

                    lint_ok, lint_issues = lint_class_sv_tb(
                        body_sv,
                        dut_name=dut_name,
                        required_ports=ports or None,
                        dut_outputs=dut_outs or None,
                        protocol=protocol_name,
                        port_specs=port_specs or None,
                    )
                    competitive = score_class_sv_competitive(
                        body_sv,
                        required_ports=ports or None,
                        dut_outputs=dut_outs or None,
                        protocol=protocol_name,
                        port_specs=port_specs or None,
                    )
                    auto = auto_score_testbench(full, stamp_engine, lint_ok, lint_issues)
                    learning.update(
                        {
                            "lint_ok": lint_ok,
                            "lint_issues": lint_issues,
                            **auto,
                            "final_score": auto["auto_score"],
                            "competitive": competitive,
                            "premium_bar": competitive.get("premium_bar"),
                        }
                    )
                else:
                    lint_ok, lint_issues = lint_testbench(
                        body_sv,
                        dut_name=dut_name,
                        required_ports=ports or None,
                        dut_outputs=dut_outs or None,
                    )
                    if re.search(r"\b(uvm_|ovm_|vmm_)", body_sv, re.I):
                        try:
                            from tb_uvm_lint import lint_uvm_tb

                            _uok, uiss = lint_uvm_tb(body_sv)
                            lint_issues = list(dict.fromkeys((lint_issues or []) + uiss))
                            lint_ok = lint_ok and _uok
                        except Exception:
                            pass
                    auto = auto_score_testbench(full, stamp_engine, lint_ok, lint_issues)
                    learning.update(
                        {
                            "lint_ok": lint_ok,
                            "lint_issues": lint_issues,
                            **auto,
                            "final_score": auto["auto_score"],
                        }
                    )
                try:
                    from asfigo_bridge import merge_into
                    merge_into(learning, body_sv, kind="svck")
                except Exception:
                    pass
                # Verilator when available (auto) or when CHIPSUTRA_VERIFY_TB=true — never template-replace.
                _verify_env = os.environ.get("CHIPSUTRA_VERIFY_TB", "auto").lower()
                _do_verify = _verify_env in ("1", "true", "yes") or (
                    _verify_env in ("auto", "") and bool(verilator_bin())
                )
                if _do_verify and tb_meth == "sv":
                    yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': 'Verilator lint (auto when installed)…'})}\n\n"
                    rtl_sources = []
                    for i, body in enumerate(file_bodies[:6]):
                        fn = (file_names[i] if i < len(file_names) else f"dut_{i}.sv") or f"dut_{i}.sv"
                        rtl_sources.append((fn, body))
                    vres = verify_testbench(
                        rtl_sources,
                        extract_sv(full) or full,
                        tb_name=f"{(dut_name or 'dut')}_tb.sv",
                        mode="lint",
                    )
                    learning.update(verify_status_for_learning(vres))
                    if vres.get("skipped"):
                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': 'Verilator not installed — skipped'})}\n\n"
                    elif vres.get("ok"):
                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': 'Verilator lint OK'})}\n\n"
                    else:
                        verr = ", ".join((vres.get("errors") or ["failed"])[:3])
                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': f'Verilator issues (LLM output kept): {verr}'})}\n\n"
                        _compile_fixed = False
                        # 1) Mechanical re-pass, then RE-VERIFY the fixed output
                        if is_class_sv:
                            try:
                                from tb_class_lint import repair_class_sv_tb, lint_class_sv_tb as _lcs

                                fixed = repair_class_sv_tb(
                                    extract_sv(full) or full,
                                    required_ports=ports or None,
                                    dut_outputs=dut_outs or None,
                                    port_specs=port_specs or None,
                                    dut_name=dut_name,
                                )
                                _okf, _issf = _lcs(
                                    fixed,
                                    dut_name=dut_name,
                                    required_ports=ports or None,
                                    dut_outputs=dut_outs or None,
                                    protocol=protocol_name,
                                    port_specs=port_specs or None,
                                )
                                vres_fix = verify_testbench(
                                    rtl_sources, fixed,
                                    tb_name=f"{(dut_name or 'dut')}_tb.sv", mode="lint",
                                )
                                if vres_fix.get("ok") or _okf or len(_issf) < len(lint_issues or []):
                                    full = stamp_tb_header(
                                        fixed,
                                        engine="llm_repaired",
                                        model=resolved_model or "llm",
                                        protocol=f"{protocol_pack}/{tb_meth}",
                                    )
                                    learning["lint_issues"] = _issf
                                    learning["lint_ok"] = _okf
                                    learning["verify_post_repair"] = True
                                    learning.update(verify_status_for_learning(vres_fix))
                                    _compile_fixed = bool(vres_fix.get("ok"))
                                    yield "data: " + json.dumps({
                                        "type": "replace",
                                        "content": full,
                                        "engine": "llm_repaired",
                                    }) + "\n\n"
                                    if _compile_fixed:
                                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': 'Verilator OK after mechanical repair'})}\n\n"
                                    else:
                                        vres = vres_fix  # feed latest errors to the LLM pass
                            except Exception:
                                pass
                        # 2) Compiler-error LLM self-repair — feed real %Error lines to the model
                        _comp_repair_on = os.environ.get(
                            "CHIPSUTRA_COMPILER_REPAIR", "true"
                        ).lower() not in ("0", "false", "no")
                        if (
                            not _compile_fixed
                            and _comp_repair_on
                            # Procedural bus-protocol TBs (AXI/APB) need it too
                            and (is_class_sv or protocol_pack in ("axi_lite", "axi4_lite", "apb"))
                            and llm_repair_class_sv
                            and (vres.get("errors") or [])
                        ):
                            try:
                                from tb_class_lint import repair_class_sv_tb as _mech

                                yield f"data: {json.dumps({'type': 'progress', 'stage': 'repair', 'message': f'Compiler-error self-repair via {resolved_model}…'})}\n\n"
                                cand_raw, _oks = await llm_repair_class_sv(
                                    provider=resolved_provider,
                                    model=resolved_model,
                                    broken_sv=extract_sv(full) or full,
                                    issues=learning.get("lint_issues") or [],
                                    dut_hint=(dut_name or ""),
                                    session_id=session_id,
                                    compiler_errors=vres.get("errors") or [],
                                )
                                if _oks and cand_raw:
                                    cand = extract_sv(cand_raw) or cand_raw
                                    cand = _mech(
                                        cand,
                                        required_ports=ports or None,
                                        dut_outputs=dut_outs or None,
                                        port_specs=port_specs or None,
                                        dut_name=dut_name,
                                    )
                                    vres2 = verify_testbench(
                                        rtl_sources, cand,
                                        tb_name=f"{(dut_name or 'dut')}_tb.sv", mode="lint",
                                    )
                                    if vres2.get("ok"):
                                        full = stamp_tb_header(
                                            cand,
                                            engine="llm_repaired",
                                            model=resolved_model or "llm",
                                            protocol=f"{protocol_pack}/{tb_meth}",
                                        )
                                        learning.update(verify_status_for_learning(vres2))
                                        learning["verify_compiler_repair"] = True
                                        yield "data: " + json.dumps({
                                            "type": "replace",
                                            "content": full,
                                            "engine": "llm_repaired",
                                        }) + "\n\n"
                                        yield f"data: {json.dumps({'type': 'progress', 'stage': 'verify', 'message': 'Verilator OK after compiler-error self-repair'})}\n\n"
                            except Exception:
                                logger.exception("compiler-error self-repair failed")

                        # 3) Closed loop: sim-run → classify/repair ≤N → skeleton → mutation → evidence
                        if tb_meth == "sv" and rtl_sources:
                            try:
                                from tb_class_lint import repair_class_sv_tb as _loop_mech

                                async def _loop_llm(tb_code, classified, vrun, extra_hint=""):
                                    if not llm_repair_class_sv:
                                        return tb_code, False
                                    errs = list(vrun.get("errors") or [])[:8]
                                    templates = list((classified or {}).get("templates") or [])[:4]
                                    if extra_hint:
                                        templates.append(extra_hint[:400])
                                    return await llm_repair_class_sv(
                                        provider=resolved_provider,
                                        model=resolved_model,
                                        broken_sv=extract_sv(tb_code) or tb_code,
                                        issues=learning.get("lint_issues") or [],
                                        dut_hint=(dut_name or ""),
                                        session_id=session_id,
                                        compiler_errors=errs + templates,
                                    )

                                def _mech(code: str) -> str:
                                    return _loop_mech(
                                        extract_sv(code) or code,
                                        required_ports=ports or None,
                                        dut_outputs=dut_outs or None,
                                        port_specs=port_specs or None,
                                        dut_name=dut_name,
                                    )

                                loop = await run_closed_loop(
                                    tb_sv=extract_sv(full) or full,
                                    rtl_sources=rtl_sources,
                                    tb_name=f"{(dut_name or 'dut')}_tb.sv",
                                    dut_name=dut_name or "dut",
                                    protocol=protocol_name or protocol_pack or "generic",
                                    skeleton_sv=skeleton_sv or "",
                                    stamp=lambda code, engine, model, protocol: stamp_tb_header(
                                        code, engine=engine, model=model, protocol=protocol
                                    ),
                                    mechanical_repair=_mech if is_class_sv else None,
                                    llm_repair=_loop_llm if llm_repair_class_sv else None,
                                    analysis=design_analysis,
                                    tool_versions=tool_versions(),
                                    model=resolved_model or "llm",
                                )
                                for ev in loop.events:
                                    yield f"data: {json.dumps(ev)}\n\n"
                                if loop.tb_sv and loop.tb_sv.strip():
                                    full = loop.tb_sv
                                if loop.engine:
                                    done_engine = loop.engine
                                learning.update(loop.learning or {})
                            except Exception:
                                logger.exception("closed-loop sim/repair/mutation failed")

            saved_file = None
            try:
                dut_save = "dut"
                if parsed_modules:
                    dut_save = parsed_modules[0].get("name") or "dut"
                saved_file = await _persist_generation_output(
                    project_id=inp.project_id,
                    module=inp.module,
                    content=full,
                    dut_name=dut_save,
                    methodology=tb_meth if inp.module == "testbench" else "sv",
                )
                if saved_file:
                    learning["saved_file"] = {
                        "id": saved_file.get("id"),
                        "name": saved_file.get("original_filename"),
                        "kind": saved_file.get("kind"),
                    }
            except Exception:
                logger.exception("auto-save generated artifact failed")
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
            done_payload = {
                "type": "done",
                "generation_id": gen_id,
                "engine": done_engine,
                "learning": learning,
            }
            if saved_file:
                done_payload["saved_file"] = {
                    "id": saved_file.get("id"),
                    "name": saved_file.get("original_filename"),
                    "kind": saved_file.get("kind"),
                }
            yield f"data: {json.dumps(done_payload)}\n\n"
        except Exception as e:
            logger.exception("Generation error")
            # Timeout exceptions often have empty str() — keep the class name
            err = str(e).strip() or type(e).__name__
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


@api.get("/generations/{gen_id}/evidence")
async def download_generation_evidence(gen_id: str, user=Depends(get_current_user)):
    """ZIP: evidence.json + TB + attached RTL. Community sign-off lite, not UCIS."""
    doc = await db.generations.find_one({"id": gen_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Generation not found")
    await require_project(doc["project_id"], user["id"], "viewer")
    learn = doc.get("learning") or {}
    evidence = learn.get("evidence") or {
        "chipsutra_evidence": "1.0",
        "dut_name": "dut",
        "sim_pass": learn.get("sim_pass"),
        "mutation": learn.get("mutation") or {},
        "notes": ["Rebuilt on download — original evidence.json missing."],
    }
    files: dict = {}
    tb = doc.get("output") or ""
    if tb.strip():
        files["tb.sv"] = tb
    for fid in (doc.get("file_ids") or [])[:8]:
        fdoc = await db.files.find_one(
            {"id": fid, "project_id": doc["project_id"], "is_deleted": {"$ne": True}},
            {"_id": 0},
        )
        if not fdoc:
            continue
        name = fdoc.get("original_filename") or f"{fid}.sv"
        files[f"rtl/{name}"] = _get_file_text(fdoc)
    sim_tail = (learn.get("verify_errors") or [])
    if sim_tail:
        files["sim_errors.txt"] = "\n".join(str(x) for x in sim_tail)
    blob = evidence_zip_bytes(document=evidence, files=files)
    dut = (evidence.get("dut_name") or "dut").replace(" ", "_")
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="chipsutra_{dut}_evidence.zip"'},
    )


@api.get("/projects/{pid}/signoff")
async def project_signoff(pid: str, user=Depends(get_current_user)):
    """Community readiness tiles. ChipSutra does not claim vendor sign-off."""
    await require_project(pid, user["id"], "viewer")
    gens = await db.generations.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(40)
    covs = await db.coverage_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(10)
    cdcs = await db.cdc_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(10)
    formals = await db.formal_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(10)
    sims = await db.simulations.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(10)
    synths = await db.synth_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(5)
    stas = await db.sta_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(5)
    board = build_signoff_board(
        generations=gens,
        coverage_runs=covs,
        cdc_runs=cdcs,
        formal_runs=formals,
        simulations=sims,
        synth_runs=synths,
        sta_runs=stas,
    )
    board["project_id"] = pid
    return board


@api.get("/projects/{pid}/signoff.zip")
async def project_signoff_zip(pid: str, user=Depends(get_current_user)):
    """ZIP: signoff.json + latest TB evidence. Not a vendor UCIS dump."""
    await require_project(pid, user["id"], "viewer")
    gens = await db.generations.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(40)
    board = build_signoff_board(generations=gens)
    files: dict = {"signoff.json": json.dumps(board, indent=2)}
    tb = next((g for g in gens if g.get("module") == "testbench"), None)
    if tb and (tb.get("output") or "").strip():
        files["tb.sv"] = tb["output"]
        ev = (tb.get("learning") or {}).get("evidence")
        if ev:
            files["evidence.json"] = json.dumps(ev, indent=2)
    blob = evidence_zip_bytes(document=board, files=files)
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="chipsutra_{pid[:8]}_signoff.zip"'},
    )

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
        log_lines = []
        def log(line: str, level: str = "info"):
            log_lines.append(line)
            return f"data: {json.dumps({'type':'log','level':level,'line':line})}\n\n"

        from commercial_sim_pack import looks_like_uvm, uvm_refuse_message, uvm_test_name

        tb_blob = ""
        fdocs = await db.files.find(
            {"id": {"$in": all_ids}, "project_id": inp.project_id, "is_deleted": {"$ne": True}},
            {"_id": 0},
        ).to_list(50)
        for f in fdocs:
            body = _get_file_text(f)
            if inp.tb_file_id and f.get("id") == inp.tb_file_id:
                tb_blob = body
                break
            if looks_like_uvm(body):
                tb_blob = body
        if looks_like_uvm(tb_blob):
            test = uvm_test_name(tb_blob)
            await db.simulations.update_one(
                {"id": sim_id},
                {"$set": {"status": "export", "engine": "vendor_export", "logs": [uvm_refuse_message(test)]}},
            )
            yield f"data: {json.dumps({'type':'meta','simulation_id': sim_id, 'engine': 'vendor_export'})}\n\n"
            yield log(uvm_refuse_message(test), "warn")
            yield log("Use Export vendor pack in Simulate for filelist + Questa/VCS/Xcelium scripts.", "info")
            yield f"data: {json.dumps({'type':'vendor_pack','test': test, 'simulation_id': sim_id})}\n\n"
            yield f"data: {json.dumps({'type':'done','simulation_id': sim_id, 'status': 'export', 'engine': 'vendor_export'})}\n\n"
            return

        yield f"data: {json.dumps({'type':'meta','simulation_id': sim_id, 'engine': sim_doc['engine']})}\n\n"

        if not VERILATOR_BIN:
            if REFUSE_MOCK_SIM:
                yield log(
                    "[error] Verilator not installed — refusing mock PASS "
                    "(set CHIPSUTRA_REFUSE_MOCK_SIM=false for lab demos only)",
                    "error",
                )
                status = "error"
                await db.simulations.update_one(
                    {"id": sim_id},
                    {"$set": {"status": status, "engine": "unavailable", "logs": log_lines}},
                )
                yield f"data: {json.dumps({'type':'done','simulation_id': sim_id, 'status': status, 'engine': 'unavailable'})}\n\n"
                return
            # MOCK fallback (lab / demos only)
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

@api.get("/dv-config/example")
async def dv_config_example():
    """Example CHIPSUTRA_DV_CONFIG / GenerateIn.dv_config. RTL ports still win."""
    return dv_example_config()


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


async def _upsert_project_text_file(
    *,
    project_id: str,
    filename: str,
    content: str,
    kind: str = "artifact",
    content_type: str = "text/plain",
) -> dict:
    """Replace the live generate artifact of the same name+kind, or insert it."""
    existing = await db.files.find_one(
        {
            "project_id": project_id,
            "original_filename": filename,
            "kind": kind,
            "is_deleted": {"$ne": True},
        },
        {"_id": 0},
    )
    data = content.encode("utf-8")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if existing:
        file_id = existing["id"]
        storage_path = existing.get("storage_path")
        try:
            r = put_object(
                f"{APP_NAME}/projects/{project_id}/{file_id}.{ext or 'txt'}",
                data,
                content_type,
            )
            storage_path = r["path"]
        except Exception:
            pass
        updates = {
            "size": len(data),
            "content_type": content_type,
            "storage_path": storage_path,
            "inline_content": content if storage_path is None else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.files.update_one({"id": file_id, "project_id": project_id}, {"$set": updates})
        doc = {**existing, **updates, "original_filename": filename, "kind": kind}
        return {k: v for k, v in doc.items() if k not in ("inline_content", "_id")}
    file_id = str(uuid.uuid4())
    storage_path = None
    try:
        r = put_object(f"{APP_NAME}/projects/{project_id}/{file_id}.{ext or 'txt'}", data, content_type)
        storage_path = r["path"]
    except Exception:
        pass
    doc = {
        "id": file_id,
        "project_id": project_id,
        "original_filename": filename,
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


async def _persist_generation_output(
    *,
    project_id: str,
    module: str,
    content: str,
    dut_name: str,
    methodology: str = "sv",
) -> Optional[dict]:
    text = (content or "").strip()
    if len(text) < 8:
        return None
    kind, filename = generation_artifact_meta(module, dut_name, methodology)
    return await _upsert_project_text_file(
        project_id=project_id,
        filename=filename,
        content=content,
        kind=kind,
        content_type="text/plain",
    )


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
    generated = render_cocotb_scaffold(top, rtl["original_filename"], rtl_text=text)
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
        demo_path = None if liberty_doc else demo_liberty_path()
        if binary and liberty_doc:
            engine = "opensta"
        elif binary and demo_path:
            engine = "opensta_demo"
        else:
            engine = "mock"
        top = inp.top_module or _extract_top_module(_get_file_text(netlist_doc))
        yield f"data: {json.dumps({'type':'meta','sta_id': run_id,'engine': engine,'top_module': top})}\n\n"

        if engine == "mock":
            missing = []
            if not binary:
                missing.append("sta/opensta binary")
            if not liberty_doc and not demo_path:
                missing.append("liberty (.lib) file")
            note = (
                f"[mock] Timing not run — missing: {', '.join(missing)}. "
                "Install OpenSTA (`sta`) via OSS CAD Suite / Docker. "
                "ChipSutra ships backend/fixtures/chipsutra_demo.lib for smoke; "
                "sky130/foundry .lib for real STA — see docs/STA_LIBERTY.md."
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

                    liberty_name = _sta_local_name(liberty_doc, "library.lib") if liberty_doc else "chipsutra_demo.lib"
                    if liberty_doc:
                        liberty_text = _get_file_text(liberty_doc)
                    else:
                        liberty_text = Path(demo_path).read_text(encoding="utf-8")
                        yield f"data: {json.dumps({'type':'log','level':'info','line':'[sta] using ChipSutra demo liberty (not a foundry PDK)'})}\n\n"
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


# ---- One-click Lab: lint → sim → synth → STA ----
class LabIn(BaseModel):
    project_id: str
    rtl_file_ids: List[str] = Field(default_factory=list)
    tb_file_id: Optional[str] = None
    top_module: Optional[str] = None
    skip_sim: bool = False
    sim_time_ns: int = 1000
    liberty_file_id: Optional[str] = None
    sdc_file_id: Optional[str] = None
    clock_name: str = "clk"
    period_ns: float = 10.0
    stop_on_fail: bool = True
    scaffold_sta: bool = True


async def _iter_sse_json(body_iterator):
    """Parse SSE `data: {...}` frames from a StreamingResponse body iterator."""
    buf = ""
    async for chunk in body_iterator:
        text = chunk.decode("utf-8", errors="ignore") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        buf += text
        while "\n\n" in buf:
            part, buf = buf.split("\n\n", 1)
            line = part.strip()
            if not line.startswith("data:"):
                continue
            try:
                yield json.loads(line[5:].strip())
            except Exception:
                continue


@api.post("/lab/plan")
async def lab_plan(inp: LabIn, user=Depends(get_current_user)):
    """Return the stage plan for a project without running tools."""
    await require_project(inp.project_id, user["id"], "viewer")
    files = await db.files.find(
        {"project_id": inp.project_id, "is_deleted": {"$ne": True}},
        {"_id": 0},
    ).to_list(500)
    buckets = classify_hdl_files(files)
    rtl_ids = list(inp.rtl_file_ids) or [f["id"] for f in buckets["rtl"]]
    tb_id = inp.tb_file_id or (buckets["tb"][0]["id"] if buckets["tb"] else None)
    stages = plan_lab_stages(
        has_rtl=bool(rtl_ids),
        has_tb=bool(tb_id),
        skip_sim=bool(inp.skip_sim),
        has_verible=bool(shutil.which("verible-verilog-lint")),
    )
    return {
        "rtl_file_ids": rtl_ids,
        "tb_file_id": tb_id,
        "liberty_file_id": inp.liberty_file_id or (buckets["liberty"][0]["id"] if buckets["liberty"] else None),
        "sdc_file_id": inp.sdc_file_id or (buckets["sdc"][0]["id"] if buckets["sdc"] else None),
        "stages": stages,
    }


@api.post("/lab/stream")
async def lab_stream(inp: LabIn, user=Depends(get_current_user)):
    """Compose lint → (sim) → synth → STA into one SSE stream."""
    await require_project(inp.project_id, user["id"], "editor")
    files = await db.files.find(
        {"project_id": inp.project_id, "is_deleted": {"$ne": True}},
        {"_id": 0},
    ).to_list(500)
    buckets = classify_hdl_files(files)
    rtl_ids = list(inp.rtl_file_ids) or [f["id"] for f in buckets["rtl"]]
    if not rtl_ids:
        raise HTTPException(400, "No synthesizable RTL files found for Lab pipeline")
    tb_id = inp.tb_file_id
    if tb_id is None and buckets["tb"]:
        tb_id = buckets["tb"][0]["id"]
    liberty_id = inp.liberty_file_id or (buckets["liberty"][0]["id"] if buckets["liberty"] else None)
    sdc_id = inp.sdc_file_id or (buckets["sdc"][0]["id"] if buckets["sdc"] else None)
    stages = plan_lab_stages(
        has_rtl=True,
        has_tb=bool(tb_id),
        skip_sim=bool(inp.skip_sim),
        has_verible=bool(shutil.which("verible-verilog-lint")),
    )
    lab_id = str(uuid.uuid4())
    await db.lab_runs.insert_one(
        {
            "id": lab_id,
            "project_id": inp.project_id,
            "user_id": user["id"],
            "status": "streaming",
            "stages": [s["id"] for s in stages],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    async def evgen():
        results: List[dict] = []
        yield f"data: {json.dumps({'type': 'meta', 'lab_id': lab_id, 'stages': stages})}\n\n"

        for stage in stages:
            sid = stage["id"]
            yield f"data: {json.dumps({'type': 'stage_start', 'stage': sid, 'label': stage['label']})}\n\n"
            status = "error"
            note = None
            try:
                if sid == "verible":
                    rtl_docs = [f for f in files if f.get("id") in set(rtl_ids)]
                    named = [
                        (f.get("original_filename") or "dut.sv", _get_file_text(f))
                        for f in rtl_docs
                    ]
                    vr = run_verible_lint(named)
                    status = vr.get("status") or "error"
                    note = vr.get("note")
                    for line in (vr.get("log") or note or "verible lint").splitlines()[:40]:
                        if line:
                            yield f"data: {json.dumps({'type': 'log', 'stage': sid, 'level': 'info', 'line': line})}\n\n"
                    resp = None
                elif sid == "lint":
                    resp = await simulate_stream(
                        SimulateIn(
                            project_id=inp.project_id,
                            rtl_file_ids=rtl_ids,
                            tb_file_id=tb_id,
                            top_module=inp.top_module,
                            mode="lint",
                            use_lint_policy=True,
                        ),
                        user,
                    )
                elif sid == "sim":
                    resp = await simulate_stream(
                        SimulateIn(
                            project_id=inp.project_id,
                            rtl_file_ids=rtl_ids,
                            tb_file_id=tb_id,
                            top_module=inp.top_module,
                            mode="run",
                            sim_time_ns=max(50, int(inp.sim_time_ns or 1000)),
                            use_lint_policy=True,
                        ),
                        user,
                    )
                elif sid == "synth":
                    resp = await synth_stream(
                        SynthIn(
                            project_id=inp.project_id,
                            rtl_file_ids=rtl_ids,
                            top_module=inp.top_module,
                            mode="synth",
                        ),
                        user,
                    )
                elif sid == "sta":
                    nonlocal_sdc = sdc_id
                    if inp.scaffold_sta and not nonlocal_sdc:
                        try:
                            scaffolded = await scaffold_opensta(
                                inp.project_id,
                                OpenStaScaffoldIn(
                                    rtl_file_id=rtl_ids[0],
                                    top_module=inp.top_module,
                                    clock_name=inp.clock_name or "clk",
                                    period_ns=float(inp.period_ns or 10.0),
                                ),
                                user,
                            )
                            if isinstance(scaffolded, dict):
                                for fdoc in scaffolded.get("files") or []:
                                    fname = (fdoc.get("original_filename") or "").lower()
                                    if fname.endswith(".sdc") and fdoc.get("id"):
                                        nonlocal_sdc = fdoc["id"]
                                        break
                                msg = "[lab] OpenSTA SDC scaffold generated"
                                yield f"data: {json.dumps({'type': 'log', 'stage': sid, 'level': 'info', 'line': msg})}\n\n"
                        except Exception as e:
                            warn = f"[lab] STA scaffold skipped: {e}"
                            yield f"data: {json.dumps({'type': 'log', 'stage': sid, 'level': 'warn', 'line': warn})}\n\n"
                    resp = await sta_stream(
                        StaRunIn(
                            project_id=inp.project_id,
                            netlist_file_id=None,
                            liberty_file_id=liberty_id,
                            sdc_file_id=nonlocal_sdc,
                            top_module=inp.top_module,
                            clock_name=inp.clock_name or "clk",
                            period_ns=float(inp.period_ns or 10.0),
                        ),
                        user,
                    )
                else:
                    yield f"data: {json.dumps({'type': 'log', 'stage': sid, 'level': 'error', 'line': f'unknown stage {sid}'})}\n\n"
                    resp = None

                if resp is not None:
                    async for event in _iter_sse_json(resp.body_iterator):
                        et = event.get("type")
                        if et == "done":
                            status = event.get("status") or "error"
                            note = event.get("note") or note
                            yield f"data: {json.dumps({**event, 'stage': sid})}\n\n"
                        elif et == "log":
                            yield f"data: {json.dumps({**event, 'stage': sid})}\n\n"
                        elif et in ("meta", "stats", "artifact", "lint_report"):
                            yield f"data: {json.dumps({**event, 'stage': sid})}\n\n"
                            if et == "stats" and event.get("note"):
                                note = event.get("note")
            except HTTPException as he:
                status = "error"
                msg = f"[lab] {sid} HTTP {he.status_code}: {he.detail}"
                yield f"data: {json.dumps({'type': 'log', 'stage': sid, 'level': 'error', 'line': msg})}\n\n"
            except Exception as e:
                status = "error"
                msg = f"[lab] {sid} failed: {e}"
                yield f"data: {json.dumps({'type': 'log', 'stage': sid, 'level': 'error', 'line': msg})}\n\n"

            failed = stage_failed(sid, status)
            results.append({"stage": sid, "status": status, "failed": failed, "note": note})
            yield f"data: {json.dumps({'type': 'stage_done', 'stage': sid, 'status': status, 'failed': failed, 'note': note})}\n\n"
            if failed and inp.stop_on_fail:
                yield f"data: {json.dumps({'type': 'log', 'stage': sid, 'level': 'error', 'line': f'[lab] aborting pipeline after {sid} failure'})}\n\n"
                break

        overall = pipeline_status(results)
        await db.lab_runs.update_one(
            {"id": lab_id},
            {
                "$set": {
                    "status": overall,
                    "results": results,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
        yield f"data: {json.dumps({'type': 'done', 'status': overall, 'lab_id': lab_id, 'results': results})}\n\n"

    return StreamingResponse(
        evgen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/projects/{pid}/lab-runs")
async def list_lab_runs(pid: str, user=Depends(get_current_user)):
    await require_project(pid, user["id"], "viewer")
    return await db.lab_runs.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(30)


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


class FormalPackIn(BaseModel):
    spec: str = ""
    prompt: str = ""
    dut: str = "dut"
    depth: int = 20
    sby_log: Optional[str] = None


@api.post("/formal/pack")
async def formal_pack_from_spec(inp: FormalPackIn, user=Depends(get_current_user)):
    """Spec IR → SVA + .sby. Optional CEX log classification."""
    from formal_pack import build_formal_pack, classify_cex

    pack = build_formal_pack(inp.spec, prompt=inp.prompt, dut=inp.dut or "dut", depth=inp.depth)
    if inp.sby_log:
        pack["cex_debug"] = classify_cex(inp.sby_log, prior_sva=pack.get("sva") or "")
    return pack


class DebugClassifyIn(BaseModel):
    tool_log: str = ""
    prior_output: Optional[str] = None


class DvPackIn(BaseModel):
    project_id: str
    file_ids: List[str] = []
    tb_methodology: str = "sv"


class VendorPackIn(BaseModel):
    project_id: str
    rtl_file_ids: List[str] = []
    tb_file_id: Optional[str] = None


@api.post("/debug/classify")
async def debug_classify_log(inp: DebugClassifyIn, user=Depends(get_current_user)):
    """Ranked fail causes from a sim/lint log. No LLM."""
    _ = user
    return classify_log(inp.tool_log or "", prior_code=inp.prior_output or "")


@api.post("/generate/pack")
async def generate_dv_pack(inp: DvPackIn, user=Depends(get_current_user)):
    """TB + SVA + covergroup + testplan ZIP from parsed RTL (skeleton, no LLM)."""
    from dv_pack import build_dv_pack, dv_pack_zip

    await require_project(inp.project_id, user["id"], "editor")
    ids = list(inp.file_ids or [])
    fdocs = []
    if ids:
        fdocs = await db.files.find(
            {"id": {"$in": ids}, "project_id": inp.project_id, "is_deleted": {"$ne": True}},
            {"_id": 0},
        ).to_list(20)
    if not fdocs:
        fdocs = await db.files.find(
            {
                "project_id": inp.project_id,
                "is_deleted": {"$ne": True},
                "$or": [
                    {"ext": {"$in": ["v", "sv"]}},
                    {"original_filename": {"$regex": r"\.(v|sv)$", "$options": "i"}},
                ],
            },
            {"_id": 0},
        ).to_list(20)
    rtl = "\n\n".join(_get_file_text(f) for f in fdocs if _get_file_text(f))
    if not rtl.strip():
        raise HTTPException(400, "Upload RTL (.v/.sv) before generating a DV pack")
    pack = build_dv_pack(rtl, methodology=inp.tb_methodology or "sv")
    blob = dv_pack_zip(pack)
    dut = (pack.get("dut") or "dut").replace(" ", "_")
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="chipsutra_{dut}_dv_pack.zip"'},
    )


@api.post("/simulate/vendor-pack")
async def simulate_vendor_pack(inp: VendorPackIn, user=Depends(get_current_user)):
    """UVM filelist + Questa/VCS/Xcelium scripts. Not a Verilator run."""
    from commercial_sim_pack import build_vendor_files, vendor_pack_zip

    await require_project(inp.project_id, user["id"], "editor")
    ids = list(inp.rtl_file_ids or [])
    if inp.tb_file_id and inp.tb_file_id not in ids:
        ids.append(inp.tb_file_id)
    fdocs = await db.files.find(
        {"id": {"$in": ids}, "project_id": inp.project_id, "is_deleted": {"$ne": True}},
        {"_id": 0},
    ).to_list(30)
    sources = []
    tb_sv = ""
    tb_name = "tb.sv"
    for f in fdocs:
        name = f.get("original_filename") or "src.sv"
        body = _get_file_text(f)
        sources.append((name, body))
        if inp.tb_file_id and f.get("id") == inp.tb_file_id:
            tb_sv = body
            tb_name = name
    if not sources:
        raise HTTPException(400, "Select RTL/TB files for the vendor pack")
    files = build_vendor_files(sources, tb_name=tb_name, tb_sv=tb_sv)
    blob = vendor_pack_zip(files)
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="chipsutra_uvm_vendor_pack.zip"'},
    )


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
          CHIPSUTRA_API: ${{ vars.CHIPSUTRA_API }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.number }}
          GITHUB_SHA: ${{ github.sha }}
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
        run: |
          python3 - <<'PY'
          import json, os, subprocess, urllib.request
          base = os.environ.get("BASE_SHA") or "HEAD~1"
          head = os.environ.get("GITHUB_SHA") or "HEAD"
          try:
              diff = subprocess.check_output(["git", "diff", f"{base}...{head}"], text=True, errors="replace")
          except subprocess.CalledProcessError:
              diff = ""
          payload = json.dumps({
              "repo": os.environ.get("GITHUB_REPOSITORY", ""),
              "pr": str(os.environ.get("PR_NUMBER") or ""),
              "sha": head,
              "diff": diff,
              "comment": True,
          }).encode()
          url = (os.environ.get("CHIPSUTRA_API") or "https://chipsutra.ai/api").rstrip("/") + "/ci/webhook"
          req = urllib.request.Request(
              url, data=payload,
              headers={
                  "Authorization": "Bearer " + os.environ["CHIPSUTRA_TOKEN"],
                  "Content-Type": "application/json",
              },
              method="POST",
          )
          urllib.request.urlopen(req, timeout=60)
          PY
"""
    return Response(content=yaml, media_type="text/yaml", headers={"Content-Disposition": "attachment; filename=chipsutra.yml"})

class CIWebhookIn(BaseModel):
    repo: str = "local"
    pr: Optional[str] = None
    sha: Optional[str] = None
    event: Optional[str] = "pull_request"
    diff: Optional[str] = None
    comment: bool = False


@api.post("/ci/webhook")
async def ci_webhook(inp: CIWebhookIn, user=Depends(get_current_user)):
    """Review a PR diff (lint + classify). Optionally post a GitHub comment."""
    from ci_review import maybe_post_github_comment, review_diff

    review = review_diff(inp.diff or "")
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "repo": inp.repo,
        "pr": inp.pr,
        "sha": inp.sha,
        "event": inp.event,
        "status": "done" if review.get("ok") else "needs_attention",
        "review": review,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    posted = {"posted": False}
    if inp.comment and inp.pr:
        posted = maybe_post_github_comment(
            repo=inp.repo,
            pr=str(inp.pr),
            body=review.get("comment") or "",
        )
        doc["github_comment"] = posted
    await db.ci_events.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "event_id": doc["id"], "review": review, "github_comment": posted}


@api.post("/ci/review-diff")
async def ci_review_diff(inp: CIWebhookIn, user=Depends(get_current_user)):
    """Paste a unified diff for an on-box review (no GitHub required)."""
    from ci_review import review_diff

    return review_diff(inp.diff or "")

@api.get("/ci/events")
async def list_ci_events(user=Depends(get_current_user)):
    docs = await db.ci_events.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    return docs

# ---- Include router ----
app.include_router(api)
