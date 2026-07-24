"""Iteration 3 tests: health tools, workspaces + activity + notifications,
Google session rate-limit, verilator mode='run' with VCD capture, formal (SBY),
formal_hints AI module, GitHub Actions CI download + webhook + events.

Uses OWNER=engineer@test.com and INVITEE=admin@chipsutra.ai.
"""
import os
import json
import time
import uuid
import concurrent.futures
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

OWNER_EMAIL = "engineer@test.com"
OWNER_PASSWORD = "Test@1234"
INVITEE_EMAIL = "admin@chipsutra.ai"
INVITEE_PASSWORD = "Admin@ChipSutra2026"

COUNTER_SV = (
    "module ctr(input clk, input rst, output reg [7:0] q); "
    "always @(posedge clk or posedge rst) if (rst) q<=0; else q<=q+1; endmodule\n"
)
COUNTER_TB = (
    'module ctr_tb; reg clk=0; reg rst=1; wire [7:0] q; '
    'ctr dut(.clk(clk),.rst(rst),.q(q)); '
    'always #5 clk=~clk; '
    'initial begin $dumpfile("dump.vcd"); $dumpvars(0,ctr_tb); '
    '#12 rst=0; #200 $finish; end '
    'endmodule\n'
)
RTL_WITH_ASSERT = (
    "module a1(input clk, input rst, output reg q);\n"
    "always @(posedge clk) if (rst) q<=0; else q<=~q;\n"
    "`ifdef FORMAL\n"
    "always @(posedge clk) assert(q === 1'b0 || q === 1'b1);\n"
    "`endif\n"
    "endmodule\n"
)


# ---------- Fixtures ----------
def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def owner():
    d = _login(OWNER_EMAIL, OWNER_PASSWORD)
    return {"token": d["access_token"], "user": d["user"],
            "headers": {"Authorization": f"Bearer {d['access_token']}"}}


@pytest.fixture(scope="module")
def invitee():
    d = _login(INVITEE_EMAIL, INVITEE_PASSWORD)
    return {"token": d["access_token"], "user": d["user"],
            "headers": {"Authorization": f"Bearer {d['access_token']}"}}


# ---------- 1. Health returns toolchain booleans ----------
class TestHealthTools:
    def test_health_has_toolchain_bools(self):
        r = requests.get(f"{API}/health", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "healthy"
        for k in ("verilator", "yosys", "sby"):
            assert k in d, f"missing key {k}"
            assert isinstance(d[k], bool), f"{k} is not bool: {type(d[k])}"
            assert d[k] is True, f"expected {k}=True, got {d[k]}"


# ---------- 2. Workspaces ----------
class TestWorkspaces:
    @pytest.fixture(scope="class")
    def workspace(self, owner):
        name = f"TEST_WS_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/workspaces", headers=owner["headers"],
                          json={"name": name, "description": "iter3"})
        assert r.status_code == 200, r.text
        w = r.json()
        yield w
        # No delete endpoint for workspaces — leave in-place; teardown is soft

    def test_create_workspace(self, workspace):
        assert workspace["id"]
        assert workspace["seat_limit"] == 5
        assert workspace["owner_id"]

    def test_list_workspaces_shows_owner(self, owner, workspace):
        r = requests.get(f"{API}/workspaces", headers=owner["headers"])
        assert r.status_code == 200
        match = next((w for w in r.json() if w["id"] == workspace["id"]), None)
        assert match is not None
        assert match["is_owner"] is True
        assert "project_count" in match

    def test_get_workspace_detail(self, owner, workspace):
        r = requests.get(f"{API}/workspaces/{workspace['id']}", headers=owner["headers"])
        assert r.status_code == 200
        d = r.json()
        assert d["current_role"] == "owner"

    def test_add_member_not_a_user_returns_404(self, owner, workspace):
        r = requests.post(f"{API}/workspaces/{workspace['id']}/members",
                          headers=owner["headers"],
                          json={"email": f"ghost+{uuid.uuid4().hex[:6]}@nowhere.io", "role": "member"})
        assert r.status_code == 404, r.text

    def test_add_member_success(self, owner, invitee, workspace):
        r = requests.post(f"{API}/workspaces/{workspace['id']}/members",
                          headers=owner["headers"],
                          json={"email": INVITEE_EMAIL, "role": "member"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "member"
        assert r.json()["user_id"] == invitee["user"]["id"]

    def test_add_member_duplicate_returns_400(self, owner, workspace):
        r = requests.post(f"{API}/workspaces/{workspace['id']}/members",
                          headers=owner["headers"],
                          json={"email": INVITEE_EMAIL, "role": "member"})
        assert r.status_code == 400

    def test_seat_limit_exceeded(self, owner, workspace):
        # Fill remaining seats with fresh users
        added = 0
        emails_created = []
        # workspace already has 1 member; seat_limit=5. We can add 4 more.
        # Add 4 fresh users, then a 5th should 400.
        for i in range(4):
            e = f"seat+{uuid.uuid4().hex[:8]}@chipsutra.io"
            reg = requests.post(f"{API}/auth/register",
                                json={"email": e, "password": "Test@1234", "name": "Seat Filler"})
            assert reg.status_code == 200, reg.text
            emails_created.append(e)
            r = requests.post(f"{API}/workspaces/{workspace['id']}/members",
                              headers=owner["headers"], json={"email": e, "role": "member"})
            if r.status_code == 200:
                added += 1
            else:
                # We may have hit seat cap already if a previous test polluted membership; accept early 400
                assert r.status_code == 400, r.text
                break
        # Now trying to add one more must be 400
        e = f"seat+{uuid.uuid4().hex[:8]}@chipsutra.io"
        requests.post(f"{API}/auth/register",
                      json={"email": e, "password": "Test@1234", "name": "Seat Overflow"})
        r = requests.post(f"{API}/workspaces/{workspace['id']}/members",
                          headers=owner["headers"], json={"email": e, "role": "member"})
        assert r.status_code == 400, f"expected 400 on seat overflow, got {r.status_code} {r.text}"

    def test_remove_member(self, owner, invitee, workspace):
        r = requests.delete(f"{API}/workspaces/{workspace['id']}/members/{invitee['user']['id']}",
                            headers=owner["headers"])
        assert r.status_code == 200

    def test_activity_log(self, owner, workspace):
        r = requests.get(f"{API}/workspaces/{workspace['id']}/activity", headers=owner["headers"])
        assert r.status_code == 200
        acts = r.json()
        actions = {a["action"] for a in acts}
        # Expect at least workspace_created + member_added (from earlier test)
        assert "workspace_created" in actions, f"actions={actions}"
        assert "member_added" in actions, f"actions={actions}"
        # member_removed also present after previous test
        assert "member_removed" in actions

    def test_workspace_project_and_activity(self, owner, workspace):
        # Create a project in workspace
        pname = f"TEST_WSProj_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/projects", headers=owner["headers"], json={
            "name": pname, "description": "in-ws",
            "design_type": "block", "language": "systemverilog",
            "workspace_id": workspace["id"],
        })
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        assert r.json()["workspace_id"] == workspace["id"]
        # Listing workspace projects
        r = requests.get(f"{API}/workspaces/{workspace['id']}/projects", headers=owner["headers"])
        assert r.status_code == 200
        assert any(p["id"] == pid for p in r.json())
        # Activity should include project_created
        r = requests.get(f"{API}/workspaces/{workspace['id']}/activity", headers=owner["headers"])
        acts = r.json()
        assert any(a["action"] == "project_created" and a["target_id"] == pid for a in acts), \
            f"no project_created activity: {[a['action'] for a in acts]}"
        # cleanup
        requests.delete(f"{API}/projects/{pid}", headers=owner["headers"])


# ---------- 3. Notifications ----------
class TestNotifications:
    """Reuses adding an invitee to trigger workspace_invite + project_invite."""
    @pytest.fixture(scope="class")
    def scratch_ws_and_project(self, owner, invitee):
        # Fresh workspace so we can invite invitee (may have been removed above)
        wname = f"TEST_NS_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/workspaces", headers=owner["headers"],
                          json={"name": wname})
        assert r.status_code == 200
        wid = r.json()["id"]
        # invite invitee to workspace
        r = requests.post(f"{API}/workspaces/{wid}/members", headers=owner["headers"],
                          json={"email": INVITEE_EMAIL, "role": "member"})
        assert r.status_code in (200, 400)  # 400 means already-a-member (fine)
        # Create project and invite invitee to it
        pn = f"TEST_NP_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/projects", headers=owner["headers"], json={
            "name": pn, "design_type": "block", "language": "systemverilog"})
        pid = r.json()["id"]
        r = requests.post(f"{API}/projects/{pid}/collaborators", headers=owner["headers"],
                          json={"email": INVITEE_EMAIL, "role": "editor"})
        assert r.status_code in (200, 400)
        yield {"wid": wid, "pid": pid}
        requests.delete(f"{API}/projects/{pid}", headers=owner["headers"])

    def test_invitee_sees_notifications(self, invitee, scratch_ws_and_project):
        r = requests.get(f"{API}/notifications", headers=invitee["headers"])
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "unread" in d
        kinds = {n["kind"] for n in d["items"]}
        assert "workspace_invite" in kinds, f"kinds={kinds}"
        assert "project_invite" in kinds, f"kinds={kinds}"
        assert d["unread"] >= 2

    def test_mark_one_notification_read(self, invitee):
        r = requests.get(f"{API}/notifications", headers=invitee["headers"])
        items = r.json()["items"]
        unread_items = [n for n in items if not n["read"]]
        if not unread_items:
            pytest.skip("no unread notifications to mark")
        nid = unread_items[0]["id"]
        before_unread = r.json()["unread"]
        r2 = requests.post(f"{API}/notifications/{nid}/read", headers=invitee["headers"])
        assert r2.status_code == 200
        r3 = requests.get(f"{API}/notifications", headers=invitee["headers"])
        assert r3.json()["unread"] == before_unread - 1

    def test_mark_all_read(self, invitee):
        r = requests.post(f"{API}/notifications/read-all", headers=invitee["headers"])
        assert r.status_code == 200
        r2 = requests.get(f"{API}/notifications", headers=invitee["headers"])
        assert r2.json()["unread"] == 0


# ---------- 4. Google session rate limit ----------
class TestGoogleRateLimit:
    def test_invalid_still_401_first(self):
        r = requests.post(f"{API}/auth/google/session",
                          json={"session_id": "not-a-real-session"})
        assert r.status_code == 401, r.text

    def test_rate_limit_triggers_429(self):
        # Fire 25 sequential requests via a keep-alive session so they stick to
        # the same backend pod. Rate limit is 20 per IP per 5min so ≥1 must 429.
        s = requests.Session()
        codes = []
        for i in range(25):
            try:
                r = s.post(f"{API}/auth/google/session",
                           json={"session_id": f"rl-{uuid.uuid4().hex[:6]}"},
                           timeout=20)
                codes.append(r.status_code)
            except Exception:
                codes.append(-1)
        assert 429 in codes, (
            f"expected at least one 429 among 25 requests; got {codes}. "
            "Rate limiter may not be seeing the same client IP (kubernetes ingress "
            "may not forward X-Forwarded-For into request.client.host).")


# ---------- 5. Verilator: lint mode still works + mode='run' with VCD ----------
class TestSimulation:
    @pytest.fixture(scope="class")
    def sim_project(self, owner):
        r = requests.post(f"{API}/projects", headers=owner["headers"], json={
            "name": f"TEST_Sim3_{uuid.uuid4().hex[:6]}",
            "description": "iter3 sim", "design_type": "block", "language": "systemverilog"})
        p = r.json()
        yield p
        requests.delete(f"{API}/projects/{p['id']}", headers=owner["headers"])

    def _upload(self, owner, pid, name, content):
        files = {"file": (name, content, "text/plain")}
        r = requests.post(f"{API}/projects/{pid}/files", headers=owner["headers"],
                          files=files, data={"kind": "rtl"})
        assert r.status_code == 200
        return r.json()

    def _stream_sim(self, owner, body, timeout=180):
        events = []
        with requests.post(f"{API}/simulate/stream", headers=owner["headers"],
                           json=body, stream=True, timeout=timeout) as r:
            assert r.status_code == 200, r.text
            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data: "):
                    continue
                try:
                    ev = json.loads(raw[6:])
                except Exception:
                    continue
                events.append(ev)
                if ev.get("type") == "done":
                    break
        return events

    def test_simulate_lint_mode(self, owner, sim_project):
        f = self._upload(owner, sim_project["id"], "counter.sv", COUNTER_SV)
        events = self._stream_sim(owner, {
            "project_id": sim_project["id"],
            "rtl_file_ids": [f["id"]],
            "mode": "lint",
        })
        done = next(e for e in events if e["type"] == "done")
        assert done.get("status") == "done", f"lint should pass, got {done}"

    def test_simulate_run_mode_produces_vcd(self, owner, sim_project):
        rtl = self._upload(owner, sim_project["id"], "counter.sv", COUNTER_SV)
        tb = self._upload(owner, sim_project["id"], "counter_tb.sv", COUNTER_TB)
        events = self._stream_sim(owner, {
            "project_id": sim_project["id"],
            "rtl_file_ids": [rtl["id"], tb["id"]],
            "top_module": "ctr_tb",
            "mode": "run",
            "sim_time_ns": 300,
        })
        logs = [e["line"] for e in events if e.get("type") == "log"]
        joined = "\n".join(logs)
        done = next(e for e in events if e["type"] == "done")
        assert done.get("status") == "done", f"run should succeed. status={done.get('status')}\nlogs=\n{joined}"
        vcd_id = done.get("vcd_file_id")
        assert vcd_id, f"expected vcd_file_id in done, got {done}. logs:\n{joined}"
        # verify compile+run signals in log
        assert any("source:" in l for l in logs), f"no source line: {logs[:5]}"
        assert any("top module: ctr_tb" in l for l in logs), f"no top module: {logs[:5]}"
        assert any(l.startswith("$ ") and "verilator" in l for l in logs), f"no verilator cmd: {logs[:15]}"
        assert any("obj_dir/Vctr_tb" in l for l in logs), f"no exe run: {logs}"
        # Verify VCD file is now on the project
        r = requests.get(f"{API}/projects/{sim_project['id']}", headers=owner["headers"])
        assert r.status_code == 200
        vcd_files = [f for f in r.json()["files"] if f["id"] == vcd_id]
        assert vcd_files, f"vcd file {vcd_id} not attached to project"
        assert vcd_files[0]["ext"] == "vcd"


# ---------- 6. Formal (SBY) — graceful version-mismatch ----------
class TestFormal:
    @pytest.fixture(scope="class")
    def formal_project(self, owner):
        r = requests.post(f"{API}/projects", headers=owner["headers"], json={
            "name": f"TEST_Formal_{uuid.uuid4().hex[:6]}",
            "description": "iter3 formal", "design_type": "block", "language": "systemverilog"})
        p = r.json()
        yield p
        requests.delete(f"{API}/projects/{p['id']}", headers=owner["headers"])

    def test_formal_missing_files_returns_400(self, owner, formal_project):
        r = requests.post(f"{API}/formal/stream", headers=owner["headers"],
                          json={"project_id": formal_project["id"], "rtl_file_ids": []})
        assert r.status_code == 400, r.text

    def test_formal_stream_graceful_error(self, owner, formal_project):
        # upload SVA-containing RTL
        files = {"file": ("a1.sv", RTL_WITH_ASSERT, "text/plain")}
        r = requests.post(f"{API}/projects/{formal_project['id']}/files",
                          headers=owner["headers"], files=files, data={"kind": "rtl"})
        assert r.status_code == 200
        fid = r.json()["id"]

        events = []
        with requests.post(f"{API}/formal/stream", headers=owner["headers"],
                           json={"project_id": formal_project["id"],
                                 "rtl_file_ids": [fid], "top_module": "a1",
                                 "mode": "bmc", "depth": 5},
                           stream=True, timeout=180) as r:
            assert r.status_code == 200, r.text
            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data: "):
                    continue
                try:
                    events.append(json.loads(raw[6:]))
                except Exception:
                    pass
                if events and events[-1].get("type") == "done":
                    break

        meta = next(e for e in events if e["type"] == "meta")
        assert meta["engine"] == "sby", f"engine={meta['engine']}"
        logs = [e["line"] for e in events if e.get("type") == "log"]
        joined = "\n".join(logs)
        done = next(e for e in events if e["type"] == "done")
        # The environment ships Yosys 0.23; expected error status + helpful hint
        assert done.get("status") == "error", f"expected status=error due to yosys mismatch; got: {done}\nlogs:\n{joined}"
        # Look for helpful mismatch hint
        assert "Yosys" in joined and "0.35" in joined, \
            f"expected 'Yosys ≥ 0.35' hint in logs. joined=\n{joined}"


# ---------- 7. AI 'formal_hints' module ----------
class TestFormalHintsAI:
    @pytest.fixture(scope="class")
    def ai_project(self, owner):
        r = requests.post(f"{API}/projects", headers=owner["headers"], json={
            "name": f"TEST_FH_{uuid.uuid4().hex[:6]}",
            "description": "iter3 fh", "design_type": "block", "language": "systemverilog"})
        p = r.json()
        yield p
        requests.delete(f"{API}/projects/{p['id']}", headers=owner["headers"])

    def _stream_gen(self, owner, body, timeout=180):
        events = []
        with requests.post(f"{API}/generate/stream", headers=owner["headers"],
                           json=body, stream=True, timeout=timeout) as r:
            assert r.status_code == 200, r.text
            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data: "):
                    continue
                try:
                    events.append(json.loads(raw[6:]))
                except Exception:
                    pass
                if events and events[-1].get("type") in ("done", "error"):
                    break
        return events

    def test_formal_hints_generates_sva(self, owner, ai_project):
        events = self._stream_gen(owner, {
            "project_id": ai_project["id"],
            "module": "formal_hints",
            "model_provider": "anthropic",
            "model_name": "claude-sonnet-4-5-20250929",
            "prompt": "Given a 2-bit counter with reset, draft formal properties.",
            "file_ids": [],
            "language": "systemverilog",
        })
        types = [e.get("type") for e in events]
        assert "done" in types, f"no done event. events={events[:6]}"
        deltas = [e for e in events if e.get("type") == "delta" and e.get("content")]
        assert len(deltas) >= 1
        full = "".join(e.get("content", "") for e in deltas)
        # Should contain SVA-flavored keywords
        low = full.lower()
        assert any(k in low for k in ("assert property", "assume property", "cover property", "assert(")), \
            f"expected SVA-style content in output. first 400:\n{full[:400]}"

    def test_debug_module_still_works(self, owner, ai_project):
        events = self._stream_gen(owner, {
            "project_id": ai_project["id"],
            "module": "debug",
            "model_provider": "anthropic",
            "model_name": "claude-sonnet-4-5-20250929",
            "prompt": "Say hello in one short sentence.",
            "file_ids": [],
            "language": "systemverilog",
        })
        types = [e.get("type") for e in events]
        assert "done" in types


# ---------- 8. CI / GitHub Actions ----------
class TestCI:
    def test_github_workflow_yaml_download(self):
        r = requests.get(f"{API}/ci/github-workflow")
        assert r.status_code == 200
        cd = r.headers.get("content-disposition", "")
        assert "chipsutra.yml" in cd, f"content-disposition={cd}"
        # yaml sanity
        assert "verilator" in r.text.lower()
        assert "chipsutra" in r.text.lower()
        assert r.text.startswith("name:")

    def test_webhook_requires_auth(self):
        r = requests.post(f"{API}/ci/webhook",
                         json={"repo": "acme/foo", "pr": "1", "sha": "abc123"})
        assert r.status_code == 401

    def test_webhook_creates_queued_event_and_lists(self, owner):
        payload = {"repo": f"TEST/{uuid.uuid4().hex[:6]}", "pr": "42",
                   "sha": "deadbeef1234", "event": "pull_request"}
        r = requests.post(f"{API}/ci/webhook", headers=owner["headers"], json=payload)
        assert r.status_code == 200, r.text
        ev_id = r.json()["event_id"]
        # List
        r = requests.get(f"{API}/ci/events", headers=owner["headers"])
        assert r.status_code == 200
        events = r.json()
        match = next((e for e in events if e["id"] == ev_id), None)
        assert match is not None
        assert match["status"] == "queued"
        assert match["repo"] == payload["repo"]
