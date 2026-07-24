"""ChipSutra Iteration 4 tests — fresh-clone validation + testbench generation.

Focus: FREE_DAILY_QUOTA=0 (unlimited), /auth/me usage object, testbench generation
end-to-end via SSE, debug analysis, quota-free generation (3 consecutive).
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

SV_COUNTER = (
    "module counter(input clk, input rst, output reg [7:0] q);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) q <= 0;\n"
    "    else q <= q + 1;\n"
    "endmodule\n"
)


# ---------- Auth ----------
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


# ---------- /auth/me returns usage object with FREE_DAILY_QUOTA=0 ----------
def test_auth_me_returns_usage_unlimited(session, headers):
    r = session.get(f"{API}/auth/me", headers=headers)
    assert r.status_code == 200
    me = r.json()
    assert "usage" in me, f"/auth/me must return 'usage' object. Got: {list(me.keys())}"
    usage = me["usage"]
    assert "generations_today" in usage
    assert "free_daily_quota" in usage
    assert "unlimited" in usage
    assert usage["free_daily_quota"] == 0, (
        f"FREE_DAILY_QUOTA expected 0 (unlimited default). Got: {usage['free_daily_quota']}"
    )
    assert isinstance(usage["generations_today"], int)
    print(f"usage={usage}")


# ---------- Project + file upload ----------
@pytest.fixture(scope="module")
def project(session, headers):
    r = session.post(f"{API}/projects", headers=headers, json={
        "name": f"TEST_ITER4_TB_{uuid.uuid4().hex[:6]}",
        "description": "fresh-clone testbench validation",
        "design_type": "block",
        "language": "systemverilog",
    })
    assert r.status_code == 200, r.text
    doc = r.json()
    yield doc
    try:
        session.delete(f"{API}/projects/{doc['id']}", headers=headers)
    except Exception:
        pass


@pytest.fixture(scope="module")
def uploaded_file(session, headers, project):
    files = {"file": ("counter.sv", SV_COUNTER, "text/plain")}
    data = {"kind": "rtl"}
    r = session.post(
        f"{API}/projects/{project['id']}/files",
        headers=headers, files=files, data=data
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_counter_sv(uploaded_file):
    assert uploaded_file["ext"] == "sv"
    assert uploaded_file["kind"] == "rtl"


# ---------- SSE helpers ----------
def _consume_sse(url, headers, body, timeout=180):
    events = []
    with requests.post(url, headers=headers, json=body, stream=True, timeout=timeout) as r:
        assert r.status_code == 200, f"SSE status {r.status_code}: {r.text[:400]}"
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


# ---------- CORE: Generate a testbench ----------
def test_generate_testbench_anthropic_full_stream(session, headers, project, uploaded_file):
    body = {
        "project_id": project["id"],
        "module": "testbench",
        "model_provider": "anthropic",
        "model_name": "claude-sonnet-4-5-20250929",
        "prompt": "Generate a SystemVerilog testbench for the counter DUT.",
        "file_ids": [uploaded_file["id"]],
        "language": "systemverilog",
    }
    events = _consume_sse(f"{API}/generate/stream", headers, body, timeout=180)
    types = [e.get("type") for e in events]
    assert "done" in types, f"Missing 'done' event. First events: {events[:6]}"
    deltas = [e for e in events if e.get("type") == "delta" and e.get("content")]
    assert len(deltas) >= 2, f"Expected multiple delta events, got {len(deltas)}"

    # Aggregate full output text
    text = "".join(e.get("content", "") for e in deltas)
    print(f"testbench length={len(text)} chars")
    lower = text.lower()
    # SystemVerilog testbench must contain these keywords
    assert "module" in lower, "output missing 'module' keyword"
    assert "initial" in lower or "always" in lower, (
        f"output missing 'initial' or 'always'. First 400: {text[:400]}"
    )

    # Persistence via /generations/{id}
    gen_id = next((e["generation_id"] for e in events if e.get("type") == "meta"), None)
    if gen_id is None:
        gen_id = next((e["generation_id"] for e in events if e.get("type") == "done"), None)
    assert gen_id, f"no generation_id"
    r = session.get(f"{API}/generations/{gen_id}", headers=headers)
    assert r.status_code == 200
    doc = r.json()
    assert doc["status"] == "done", f"status={doc.get('status')} err={doc.get('error')}"
    assert doc["output"] and len(doc["output"]) > 100


# ---------- Debug analysis ----------
def test_generate_debug_analysis_stream(session, headers, project):
    body = {
        "project_id": project["id"],
        "module": "debug",
        "model_provider": "anthropic",
        "model_name": "claude-sonnet-4-5-20250929",
        "prompt": "Reset stuck high, counter not incrementing.",
        "file_ids": [],
        "language": "systemverilog",
    }
    events = _consume_sse(f"{API}/generate/stream", headers, body, timeout=120)
    types = [e.get("type") for e in events]
    assert "done" in types, f"missing done. events: {events[:5]}"
    text = "".join(e.get("content", "") for e in events if e.get("type") == "delta")
    assert len(text) > 40, f"debug analysis too short: {text[:200]}"


# ---------- No quota errors — 3 consecutive generations succeed ----------
def test_no_quota_errors_three_consecutive(session, headers, project):
    """Regression: FREE_DAILY_QUOTA=0 means unlimited; 3 quick generations must all succeed."""
    for i in range(3):
        body = {
            "project_id": project["id"],
            "module": "debug",
            "model_provider": "anthropic",
            "model_name": "claude-sonnet-4-5-20250929",
            "prompt": f"quick check #{i} — reply in one word",
            "file_ids": [],
            "language": "systemverilog",
        }
        r = requests.post(
            f"{API}/generate/stream", headers=headers, json=body,
            stream=True, timeout=90,
        )
        assert r.status_code != 429, f"iter {i}: got 429 quota error — FREE_DAILY_QUOTA should be 0"
        assert r.status_code == 200, f"iter {i}: {r.status_code} {r.text[:200]}"
        # drain
        got_done = False
        for raw in r.iter_lines(decode_unicode=True):
            if raw and raw.startswith("data: "):
                try:
                    ev = json.loads(raw[6:])
                    if ev.get("type") in ("done", "error"):
                        got_done = ev.get("type") == "done"
                        break
                except Exception:
                    pass
        r.close()
        assert got_done, f"iter {i}: stream ended without done event"


# ---------- Regressions: workspaces list, notifications, coverage/waveform ----------
def test_workspaces_list_still_works(session, headers):
    r = session.get(f"{API}/workspaces", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_notifications_list_still_works(session, headers):
    r = session.get(f"{API}/notifications", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body or isinstance(body, list)


def test_coverage_parse_regression(session, headers):
    files = {"file": ("cov.txt",
                      "Statement coverage: 88%\nBranch coverage: 71%\nToggle coverage: 92%\n",
                      "text/plain")}
    r = session.post(f"{API}/coverage/parse", headers=headers, files=files)
    assert r.status_code == 200
    assert r.json()["count"] >= 3


def test_waveform_parse_regression(session, headers):
    vcd = (
        "$timescale 1ns $end\n"
        "$scope module tb $end\n"
        "$var wire 1 ! clk $end\n"
        "$upscope $end\n"
        "$enddefinitions $end\n"
        "#0\n0!\n#5\n1!\n"
    )
    files = {"file": ("mini.vcd", vcd, "text/plain")}
    r = session.post(f"{API}/waveform/parse", headers=headers, files=files)
    assert r.status_code == 200
    assert len(r.json()["tracks"]) >= 1


def test_verilator_lint_still_works(session, headers, project, uploaded_file):
    body = {
        "project_id": project["id"],
        "rtl_file_ids": [uploaded_file["id"]],
        "mode": "lint",
    }
    # simulate is SSE — just ensure endpoint accepts POST and streams (200)
    r = requests.post(
        f"{API}/simulate/stream", headers=headers, json=body, stream=True, timeout=90,
    )
    assert r.status_code == 200, f"simulate/stream: {r.status_code} {r.text[:200]}"
    # drain first few events (don't wait for full simulation)
    got_any = False
    for i, raw in enumerate(r.iter_lines(decode_unicode=True)):
        if raw and raw.startswith("data: "):
            got_any = True
            try:
                ev = json.loads(raw[6:])
                if ev.get("type") in ("done", "error"):
                    break
            except Exception:
                pass
        if i > 200:
            break
    r.close()
    assert got_any, "simulate/stream produced no SSE data"
