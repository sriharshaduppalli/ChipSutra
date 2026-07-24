"""ChipSutra backend E2E tests using pytest + requests.

Covers: health, waitlist, contact, auth, projects, files (with real storage),
coverage parse, waveform parse, and AI SSE generation (Anthropic + OpenAI via
Emergent universal key).
"""
import os
import json
import time
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

TEST_USER_EMAIL = "engineer@test.com"
TEST_USER_PASSWORD = "Test@1234"

MINIMAL_VCD = (
    "$timescale 1ns $end\n"
    "$scope module tb $end\n"
    "$var wire 1 ! clk $end\n"
    "$upscope $end\n"
    "$enddefinitions $end\n"
    "#0\n0!\n#5\n1!\n#10\n0!\n"
)

COVERAGE_TEXT = "Statement coverage: 87.5%\nBranch coverage: 72%\nToggle coverage: 95%\n"

SV_SNIPPET = "module debug_dut(input logic clk, input logic rst_n); endmodule\n"


# ---------- Shared session with token ----------
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    return s


@pytest.fixture(scope="session")
def auth(session):
    """Ensure test user exists; return (token, user)."""
    # Try login first
    r = session.post(f"{API}/auth/login", json={
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
    })
    if r.status_code == 200:
        data = r.json()
        return data["access_token"], data["user"]
    # Register
    r = session.post(f"{API}/auth/register", json={
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
        "name": "Test Engineer",
    })
    if r.status_code != 200:
        pytest.fail(f"Cannot login or register test user: {r.status_code} {r.text}")
    data = r.json()
    return data["access_token"], data["user"]


@pytest.fixture(scope="session")
def headers(auth):
    token, _ = auth
    return {"Authorization": f"Bearer {token}"}


# ---------- Health ----------
def test_health(session):
    r = session.get(f"{API}/health", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["storage"] is True, "Storage must be initialized"


# ---------- Waitlist & Contact ----------
def test_waitlist(session):
    email = f"waitlist+{uuid.uuid4().hex[:8]}@test.com"
    r = session.post(f"{API}/waitlist", json={"email": email, "name": "WL Tester"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_contact(session):
    r = session.post(f"{API}/contact", json={
        "name": "Ping",
        "email": f"contact+{uuid.uuid4().hex[:6]}@test.com",
        "message": "Hello ChipSutra"
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ---------- Auth ----------
def test_register_unique_email(session):
    email = f"engineer+{int(time.time())}@test.com"
    r = session.post(f"{API}/auth/register", json={
        "email": email, "password": "Test@1234", "name": "New Engineer"
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data and isinstance(data["access_token"], str)
    assert data["user"]["email"] == email
    assert data["user"]["role"] == "user"


def test_login_and_me(session, auth, headers):
    # login flow already validated in fixture; verify /me
    r = session.get(f"{API}/auth/me", headers=headers)
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == TEST_USER_EMAIL
    assert "password_hash" not in me


# ---------- Projects ----------
@pytest.fixture(scope="session")
def project(session, headers):
    r = session.post(f"{API}/projects", headers=headers, json={
        "name": f"TEST_Project_{uuid.uuid4().hex[:6]}",
        "description": "backend_test.py",
        "design_type": "block",
        "language": "systemverilog",
    })
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["name"].startswith("TEST_Project_")
    yield doc
    # teardown
    session.delete(f"{API}/projects/{doc['id']}", headers=headers)


def test_create_project(project):
    assert project["id"]
    assert project["design_type"] == "block"
    assert project["language"] == "systemverilog"


def test_list_projects(session, headers, project):
    r = session.get(f"{API}/projects", headers=headers)
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert project["id"] in ids


def test_get_project_detail(session, headers, project):
    r = session.get(f"{API}/projects/{project['id']}", headers=headers)
    assert r.status_code == 200
    doc = r.json()
    assert doc["id"] == project["id"]
    assert isinstance(doc.get("files"), list)
    assert isinstance(doc.get("generations"), list)


# ---------- Files ----------
@pytest.fixture(scope="session")
def uploaded_file(session, headers, project):
    files = {"file": ("debug_dut.sv", SV_SNIPPET, "text/plain")}
    data = {"kind": "rtl"}
    r = session.post(f"{API}/projects/{project['id']}/files",
                     headers=headers, files=files, data=data)
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_file(uploaded_file):
    assert uploaded_file["ext"] == "sv"
    assert uploaded_file["kind"] == "rtl"
    assert uploaded_file["is_deleted"] is False
    # Should be stored via Emergent object storage
    assert uploaded_file.get("storage_path"), \
        f"Expected storage_path (object storage), got: {uploaded_file}"


def test_get_file_content(session, headers, project, uploaded_file):
    r = session.get(
        f"{API}/projects/{project['id']}/files/{uploaded_file['id']}/content",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "module debug_dut" in data["content"]
    assert data["ext"] == "sv"


def test_delete_file_soft(session, headers, project):
    # Upload a second file to delete
    files = {"file": ("todelete.sv", "module x; endmodule\n", "text/plain")}
    r = session.post(f"{API}/projects/{project['id']}/files",
                     headers=headers, files=files, data={"kind": "rtl"})
    assert r.status_code == 200
    fid = r.json()["id"]

    r = session.delete(f"{API}/projects/{project['id']}/files/{fid}",
                       headers=headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # File should not appear in project detail files
    detail = session.get(f"{API}/projects/{project['id']}", headers=headers).json()
    assert fid not in [f["id"] for f in detail["files"]]


# ---------- Coverage parse ----------
def test_coverage_parse(session, headers):
    files = {"file": ("cov.txt", COVERAGE_TEXT, "text/plain")}
    r = session.post(f"{API}/coverage/parse", headers=headers, files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] >= 3, f"Expected >=3 metrics, got {data['count']}: {data}"
    hole_names = " ".join(h["name"].lower() for h in data["holes"])
    assert "branch" in hole_names, f"Branch should be a hole (72%): {data['holes']}"


# ---------- Waveform parse ----------
def test_waveform_parse(session, headers):
    files = {"file": ("mini.vcd", MINIMAL_VCD, "text/plain")}
    r = session.post(f"{API}/waveform/parse", headers=headers, files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["tracks"]) >= 1, f"Expected >=1 track: {data}"
    assert data["tracks"][0]["name"].endswith("clk")


# ---------- SSE Generation (Anthropic + OpenAI) ----------
def _consume_sse(url, headers, body, timeout=120):
    """Return list of parsed event dicts."""
    events = []
    with requests.post(url, headers=headers, json=body, stream=True,
                       timeout=timeout) as r:
        assert r.status_code == 200, f"SSE status {r.status_code}: {r.text[:500]}"
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data: "):
                try:
                    events.append(json.loads(raw[6:]))
                except Exception:
                    pass
                if events and events[-1].get("type") in ("done", "error"):
                    break
    return events


def _run_generation(session, headers, project_id, provider, model):
    body = {
        "project_id": project_id,
        "module": "debug",
        "model_provider": provider,
        "model_name": model,
        "prompt": "Say hello in one short sentence.",
        "file_ids": [],
        "language": "systemverilog",
    }
    events = _consume_sse(f"{API}/generate/stream", headers, body)
    types = [e.get("type") for e in events]
    # Must have at least one delta and a done event
    assert "done" in types, f"Missing done event. Events: {events[:6]}"
    deltas = [e for e in events if e.get("type") == "delta" and e.get("content")]
    assert len(deltas) >= 1, f"Expected >=1 delta with content. Events: {events[:8]}"

    gen_id = next((e["generation_id"] for e in events if e.get("type") == "meta"), None)
    if gen_id is None:
        gen_id = next((e["generation_id"] for e in events if e.get("type") == "done"), None)
    assert gen_id, f"No generation_id in events: {events[:4]}"

    # Verify persistence
    r = session.get(f"{API}/generations/{gen_id}", headers=headers)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "done", f"gen status: {doc.get('status')} err={doc.get('error')}"
    assert doc["output"], "Generation output should be non-empty"
    return doc


def test_generate_stream_anthropic(session, headers, project):
    doc = _run_generation(session, headers, project["id"],
                          "anthropic", "claude-sonnet-4-5-20250929")
    assert doc["provider"] == "anthropic"


def test_generate_stream_openai(session, headers, project):
    doc = _run_generation(session, headers, project["id"],
                          "openai", "gpt-5.2")
    assert doc["provider"] == "openai"


# ---------- Project delete ----------
def test_delete_project_end(session, headers):
    r = session.post(f"{API}/projects", headers=headers, json={
        "name": f"TEST_ToDelete_{uuid.uuid4().hex[:6]}",
        "description": "",
        "design_type": "block",
        "language": "systemverilog",
    })
    pid = r.json()["id"]
    r = session.delete(f"{API}/projects/{pid}", headers=headers)
    assert r.status_code == 200
    r = session.get(f"{API}/projects/{pid}", headers=headers)
    assert r.status_code == 404
