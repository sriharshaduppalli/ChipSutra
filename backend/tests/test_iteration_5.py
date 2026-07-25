"""ChipSutra Iteration 5 tests — ZERO-KEY Ollama fallback validation.

Scope (backend only):
1. GET /api/health exposes llm_providers dict with 'ollama' and 'ollama_model' keys.
2. llm_provider.available_providers() correctly reports 'ollama' true/false based on OLLAMA_URL.
3. llm_provider.stream_chat falls through to Ollama HTTP streaming (httpx) when
   no Emergent/Anthropic/OpenAI is configured — monkey-patched.
4. docker-compose.yml has mongo + ollama + ollama-pull services; backend depends on
   ollama-pull (service_completed_successfully) and gets OLLAMA_URL=http://ollama:11434.
5. backend/.env.example presets OLLAMA_URL + OLLAMA_MODEL with zero-key guidance,
   Anthropic/OpenAI/Emergent keys are commented-out.
6. backend/requirements.txt contains httpx (needed for Ollama streaming).
7. README.md Quick start section says 'zero API keys required'.
8. REGRESSION: POST /api/generate/stream module=testbench still succeeds against the
   live preview (Emergent provider path).
9. Fresh-clone verification: git clone the public repo and verify Ollama code path
   files are present and correct.
"""
import os
import re
import sys
import json
import shutil
import subprocess
import importlib
import asyncio
import pathlib
from types import SimpleNamespace

import pytest
import requests
import yaml

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://127.0.0.1:8001").rstrip("/")
API = f"{BASE_URL}/api"

TEST_USER_EMAIL = "engineer@test.com"
TEST_USER_PASSWORD = "Test@1234"

REPO_ROOT = pathlib.Path(os.environ.get("REPO_ROOT", "/app"))
if not (REPO_ROOT / "docker-compose.yml").exists():
    REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
LLM_PROVIDER_PATH = BACKEND_DIR / "llm_provider.py"
DOCKER_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = BACKEND_DIR / ".env.example"
REQUIREMENTS_PATH = BACKEND_DIR / "requirements-oss.txt"
README_PATH = REPO_ROOT / "README.md"

SV_COUNTER = (
    "module counter(input clk, input rst, output reg [7:0] q);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) q <= 0;\n"
    "    else q <= q + 1;\n"
    "endmodule\n"
)


# =====================================================================
# 1. /api/health exposes llm_providers dict with ollama + ollama_model
# =====================================================================
def test_health_exposes_ollama_provider_keys():
    try:
        r = requests.get(f"{API}/health", timeout=5)
    except requests.RequestException:
        pytest.skip("live backend not running (set REACT_APP_BACKEND_URL)")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "llm_providers" in body, f"/api/health missing llm_providers: {body}"
    providers = body["llm_providers"]
    for key in ("emergent", "anthropic", "openai", "ollama", "ollama_model"):
        assert key in providers, f"llm_providers missing '{key}': {providers}"
    # On preview OLLAMA is not set so ollama_model should be None and ollama False.
    print(f"llm_providers={providers}")


# =====================================================================
# 2. Unit-level: available_providers() reports ollama true when OLLAMA_URL set.
# =====================================================================
def _reload_llm_provider_with_env(new_env: dict):
    """Reload the backend llm_provider module with modified env vars.

    Returns the freshly imported module object.
    """
    # Ensure backend dir on sys.path
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    # Save + patch env
    old = {}
    for k, v in new_env.items():
        old[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    # Force fresh import
    if "llm_provider" in sys.modules:
        del sys.modules["llm_provider"]
    import llm_provider as _lp  # type: ignore
    return _lp, old


def _restore_env(old: dict):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_available_providers_reports_ollama_true_when_url_set():
    lp, saved = _reload_llm_provider_with_env({
        "EMERGENT_LLM_KEY": None,
        "ANTHROPIC_API_KEY": None,
        "OPENAI_API_KEY": None,
        "OLLAMA_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "chipsutra-vlsi:3b",
    })
    try:
        av = lp.available_providers()
        assert av["ollama"] is True, f"Expected ollama=True. Got: {av}"
        assert av["ollama_model"] == "chipsutra-vlsi:3b", av
        # No key providers should be enabled in this env slice
        assert av["emergent"] is False
        assert av["anthropic"] is False
        assert av["openai"] is False
    finally:
        _restore_env(saved)
        sys.modules.pop("llm_provider", None)


def test_available_providers_reports_ollama_false_when_url_unset():
    lp, saved = _reload_llm_provider_with_env({
        "EMERGENT_LLM_KEY": None,
        "ANTHROPIC_API_KEY": None,
        "OPENAI_API_KEY": None,
        "OLLAMA_URL": None,
    })
    try:
        av = lp.available_providers()
        assert av["ollama"] is False, av
        assert av["ollama_model"] is None, av
    finally:
        _restore_env(saved)
        sys.modules.pop("llm_provider", None)


# =====================================================================
# 3. stream_chat falls through to Ollama HTTP streaming (monkey-patched httpx)
# =====================================================================
class _FakeStreamResponse:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeAsyncClient:
    captured = {}

    def __init__(self, *args, **kwargs):
        _FakeAsyncClient.captured["init_kwargs"] = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, json=None):
        _FakeAsyncClient.captured["method"] = method
        _FakeAsyncClient.captured["url"] = url
        _FakeAsyncClient.captured["json"] = json
        ndjson = [
            '{"message":{"content":"Hi"},"done":false}',
            '{"message":{"content":" there"},"done":false}',
            '{"message":{"content":""},"done":true}',
        ]
        return _FakeStreamResponse(ndjson)


def test_stream_chat_falls_through_to_ollama_when_only_ollama_configured():
    lp, saved = _reload_llm_provider_with_env({
        "EMERGENT_LLM_KEY": None,
        "ANTHROPIC_API_KEY": None,
        "OPENAI_API_KEY": None,
        "OLLAMA_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "chipsutra-vlsi:3b",
    })
    try:
        # Monkey-patch httpx.AsyncClient in the reloaded module
        import httpx as _httpx
        orig = _httpx.AsyncClient
        _httpx.AsyncClient = _FakeAsyncClient
        lp.httpx.AsyncClient = _FakeAsyncClient
        try:
            async def _run():
                out = []
                # provider label doesn't matter — with no emergent/anthropic/openai
                # configured, stream_chat must fall through to OLLAMA_URL branch.
                async for delta in lp.stream_chat(
                    provider="anthropic",
                    model="claude-sonnet-4-5-20250929",
                    system="You are a test bot.",
                    user_text="Say hi.",
                    session_id="unit-test",
                ):
                    out.append(delta)
                return out

            deltas = asyncio.run(_run())
            assert deltas == ["Hi", " there"], f"Unexpected deltas: {deltas}"

            cap = _FakeAsyncClient.captured
            assert cap["method"] == "POST", cap
            assert cap["url"].endswith("/api/chat"), cap
            assert cap["url"].startswith("http://localhost:11434"), cap
            payload = cap["json"]
            assert payload["model"] == "chipsutra-vlsi:3b", payload
            assert payload["stream"] is True, payload
            msgs = payload["messages"]
            roles = [m["role"] for m in msgs]
            assert roles == ["system", "user"], roles
            assert msgs[1]["content"] == "Say hi.", msgs
        finally:
            _httpx.AsyncClient = orig
    finally:
        _restore_env(saved)
        sys.modules.pop("llm_provider", None)


def test_stream_chat_raises_when_no_provider_configured():
    lp, saved = _reload_llm_provider_with_env({
        "EMERGENT_LLM_KEY": None,
        "ANTHROPIC_API_KEY": None,
        "OPENAI_API_KEY": None,
        "OLLAMA_URL": None,
    })
    try:
        async def _run():
            async for _ in lp.stream_chat("anthropic", "x", "sys", "hi"):
                pass

        with pytest.raises(RuntimeError):
            asyncio.run(_run())
    finally:
        _restore_env(saved)
        sys.modules.pop("llm_provider", None)


# =====================================================================
# 4. docker-compose.yml lint check
# =====================================================================
def test_docker_compose_has_mongo_ollama_and_backend_depends_on_ollama_create():
    assert DOCKER_COMPOSE_PATH.exists(), f"missing {DOCKER_COMPOSE_PATH}"
    with DOCKER_COMPOSE_PATH.open() as f:
        raw = f.read()
    doc = yaml.safe_load(raw)
    services = doc.get("services", {})
    for svc in ("mongo", "ollama", "ollama-pull", "ollama-create", "backend"):
        assert svc in services, f"docker-compose missing service '{svc}': {list(services)}"

    ollama = services["ollama"]
    assert "ollama/ollama" in ollama["image"], ollama

    ollama_pull = services["ollama-pull"]
    dep = ollama_pull.get("depends_on")
    if isinstance(dep, dict):
        assert "ollama" in dep, dep
    else:
        assert "ollama" in dep, dep
    assert "OLLAMA_BASE_MODEL" in raw or "qwen2.5-coder:3b" in raw, \
        "docker-compose should pull qwen2.5-coder:3b base for chipsutra-vlsi"
    assert "chipsutra-vlsi" in raw, "docker-compose should build chipsutra-vlsi Ollama tag"
    assert (REPO_ROOT / "models" / "chipsutra-vlsi" / "Modelfile.3b").exists(), \
        "missing models/chipsutra-vlsi/Modelfile.3b"

    backend = services["backend"]
    bdep = backend["depends_on"]
    assert isinstance(bdep, dict), f"backend.depends_on should be dict form: {bdep}"
    assert "ollama-create" in bdep, bdep
    assert bdep["ollama-create"].get("condition") == "service_completed_successfully", bdep

    env = backend.get("environment") or {}
    if isinstance(env, list):
        env_map = dict(e.split("=", 1) for e in env if "=" in e)
    else:
        env_map = env
    assert env_map.get("OLLAMA_URL") == "http://ollama:11434", env_map
    ollama_model = env_map.get("OLLAMA_MODEL") or ""
    assert "chipsutra-vlsi" in str(ollama_model) or "chipsutra-vlsi" in raw, env_map


# =====================================================================
# 5. backend/.env.example presets Ollama + commented-out paid keys
# =====================================================================
def test_env_example_has_ollama_defaults_and_zero_key_guidance():
    assert ENV_EXAMPLE_PATH.exists()
    txt = ENV_EXAMPLE_PATH.read_text()
    # OLLAMA_URL and OLLAMA_MODEL preset (uncommented)
    assert re.search(r'^\s*OLLAMA_URL\s*=', txt, re.M), "OLLAMA_URL should be preset in .env.example"
    assert re.search(r'^\s*OLLAMA_MODEL\s*=\s*"chipsutra-vlsi', txt, re.M), \
        "OLLAMA_MODEL should default to chipsutra-vlsi in .env.example"
    # Paid provider keys should be commented out (start with #)
    for pat in [r'^\s*#\s*ANTHROPIC_API_KEY', r'^\s*#\s*OPENAI_API_KEY', r'^\s*#\s*EMERGENT_LLM_KEY']:
        assert re.search(pat, txt, re.M), f".env.example should have commented-out {pat}"
    # Zero-key guidance
    assert re.search(r'zero[- ]key', txt, re.I) or re.search(r'no\s+api\s+key', txt, re.I), \
        ".env.example should mention 'zero-key' / 'no api key' guidance"


# =====================================================================
# 6. requirements.txt has httpx (added for Ollama HTTP streaming)
# =====================================================================
def test_requirements_has_httpx():
    reqs = REQUIREMENTS_PATH.read_text()
    assert re.search(r'^httpx(==|\s*$)', reqs, re.M), "requirements.txt must contain httpx"


# =====================================================================
# 7. README Quick start section says zero API keys required
# =====================================================================
def test_readme_quickstart_says_zero_api_keys():
    txt = README_PATH.read_text(encoding="utf-8")
    # Look for the zero-key claim near a Quick start heading
    assert re.search(r'##\s*(?:[\U0001F300-\U0001FAFF]\s*)?Quick\s*start', txt, re.I) or \
        re.search(r'Quick\s*start', txt, re.I), "README must have a Quick start section"
    assert re.search(r'zero\s+api\s+keys?\s+required', txt, re.I), \
        "README Quick start should say 'zero API keys required'"
    # docker compose up must appear
    assert "docker compose up" in txt or "docker-compose up" in txt


# =====================================================================
# 8. REGRESSION: /api/generate/stream module=testbench still works with Emergent
# =====================================================================
@pytest.fixture(scope="module")
def session():
    return requests.Session()


@pytest.fixture(scope="module")
def auth(session):
    r = session.post(f"{API}/auth/login", json={
        "email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD,
    })
    if r.status_code != 200:
        r = session.post(f"{API}/auth/register", json={
            "email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD,
            "name": "Test Engineer",
        })
    assert r.status_code == 200, r.text
    d = r.json()
    return d["access_token"], d["user"]


@pytest.fixture(scope="module")
def headers(auth):
    return {"Authorization": f"Bearer {auth[0]}"}


@pytest.fixture(scope="module")
def project_and_file(session, headers):
    import uuid
    r = session.post(f"{API}/projects", headers=headers, json={
        "name": f"TEST_ITER5_TB_{uuid.uuid4().hex[:6]}",
        "description": "ollama-fallback regression",
        "design_type": "block",
        "language": "systemverilog",
    })
    assert r.status_code == 200, r.text
    proj = r.json()

    files = {"file": ("counter.sv", SV_COUNTER, "text/plain")}
    r = session.post(
        f"{API}/projects/{proj['id']}/files?kind=rtl",
        headers=headers, files=files,
    )
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    yield proj, fid
    # cleanup best-effort
    try:
        session.delete(f"{API}/projects/{proj['id']}", headers=headers)
    except Exception:
        pass


def _consume_sse(response, max_seconds=90):
    events = []
    start = __import__("time").time()
    for line in response.iter_lines(decode_unicode=True):
        if __import__("time").time() - start > max_seconds:
            break
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            events.append(obj)
            if obj.get("type") == "done" or obj.get("done"):
                break
    return events


def test_regression_generate_stream_testbench_still_works(session, headers, project_and_file):
    proj, fid = project_and_file
    body = {
        "project_id": proj["id"],
        "module": "testbench",
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "rtl_file_ids": [fid],
        "prompt": "Generate a simple SystemVerilog testbench for the counter module.",
    }
    with session.post(
        f"{API}/generate/stream",
        headers={**headers, "Accept": "text/event-stream"},
        json=body, stream=True, timeout=120,
    ) as r:
        assert r.status_code == 200, r.text[:500]
        events = _consume_sse(r, max_seconds=120)

    assert events, "no SSE events received"
    delta_texts = []
    done_seen = False
    for ev in events:
        if ev.get("type") == "delta":
            delta_texts.append(ev.get("text") or ev.get("content") or "")
        if ev.get("type") == "done":
            done_seen = True
    combined = "".join(delta_texts)
    assert done_seen, f"no 'done' event; last events: {events[-3:]}"
    assert len(combined) > 50, f"delta text too short: {combined!r}"
    assert "module" in combined.lower(), f"testbench output missing 'module' keyword: {combined[:400]}"


# =====================================================================
# 9. Fresh-clone verification (git clone the public repo)
# =====================================================================
FRESH_DIR = pathlib.Path("/tmp/FreshChipSutra_v08")


def test_fresh_clone_has_ollama_wiring():
    if FRESH_DIR.exists():
        shutil.rmtree(FRESH_DIR)
    proc = subprocess.run(
        ["git", "clone", "--depth", "1",
         "https://github.com/sriharshaduppalli/ChipSutra.git",
         str(FRESH_DIR)],
        capture_output=True, text=True, timeout=90,
    )
    if proc.returncode != 0:
        pytest.skip(f"git clone failed (network?): {proc.stderr[:300]}")

    # docker-compose.yml has ollama + ollama-pull
    compose = (FRESH_DIR / "docker-compose.yml").read_text()
    assert "ollama:" in compose, "fresh clone docker-compose missing ollama service"
    assert "ollama-pull" in compose, "fresh clone docker-compose missing ollama-pull"
    assert "chipsutra-vlsi" in compose or "qwen2.5-coder" in compose, \
        "fresh clone docker-compose missing VLSI model wiring"

    # llm_provider.py has stream_chat + OLLAMA_URL fallback
    lp = (FRESH_DIR / "backend" / "llm_provider.py").read_text()
    assert "stream_chat" in lp, "fresh clone llm_provider.py missing stream_chat"
    assert "OLLAMA_URL" in lp, "fresh clone llm_provider.py missing OLLAMA_URL fallback"
    assert "/api/chat" in lp, "fresh clone llm_provider.py missing /api/chat endpoint"

    # .env.example has OLLAMA_URL preset
    env = (FRESH_DIR / "backend" / ".env.example").read_text()
    assert re.search(r'^\s*OLLAMA_URL\s*=', env, re.M), "fresh clone .env.example missing OLLAMA_URL preset"

    # README quick start says zero API keys
    readme = (FRESH_DIR / "README.md").read_text()
    assert re.search(r'zero\s+api\s+keys?\s+required', readme, re.I), \
        "fresh clone README missing 'zero API keys required'"

    # requirements.txt has httpx
    reqs = (FRESH_DIR / "backend" / "requirements-oss.txt").read_text()
    assert re.search(r'^httpx', reqs, re.M), "fresh clone requirements-oss.txt missing httpx"
