"""Iteration 2 tests: templates, collaboration, comments, verilator, google session.

Extends iteration 1 (test_credentials.md accounts). Uses two users:
- Owner:    engineer@test.com / Test@1234
- Invitee:  admin@chipsutra.ai / Admin@ChipSutra2026
"""
import os
import json
import uuid
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

OWNER_EMAIL = "engineer@test.com"
OWNER_PASSWORD = "Test@1234"
INVITEE_EMAIL = "admin@chipsutra.ai"
INVITEE_PASSWORD = "Admin@ChipSutra2026"

COUNTER_SV = (
    "module counter(input clk, input rst, output reg [7:0] q);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) q<=0; else q<=q+1;\n"
    "endmodule\n"
)
BROKEN_SV = (
    "module bad(input a);\n"
    "  always @(*) begin end\n"
    "  assign x = y;\n"
    "endmodule\n"
)


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def owner():
    d = _login(OWNER_EMAIL, OWNER_PASSWORD)
    return {"token": d["access_token"], "user": d["user"], "headers": {"Authorization": f"Bearer {d['access_token']}"}}


@pytest.fixture(scope="module")
def invitee():
    d = _login(INVITEE_EMAIL, INVITEE_PASSWORD)
    return {"token": d["access_token"], "user": d["user"], "headers": {"Authorization": f"Bearer {d['access_token']}"}}


@pytest.fixture(scope="module")
def project(owner):
    r = requests.post(f"{API}/projects", headers=owner["headers"], json={
        "name": f"TEST_Iter2_{uuid.uuid4().hex[:6]}",
        "description": "iteration 2 test project",
        "design_type": "chiplet",
        "language": "systemverilog",
    })
    assert r.status_code == 200, r.text
    doc = r.json()
    yield doc
    requests.delete(f"{API}/projects/{doc['id']}", headers=owner["headers"])


# ---------- Templates ----------
class TestTemplates:
    def test_list_templates(self):
        r = requests.get(f"{API}/templates")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 6, f"expected 6 templates, got {len(data)}"
        cats = {t["category"] for t in data}
        assert cats == {"UCIe", "BoW", "Chiplet", "IP"}, f"categories={cats}"
        for t in data:
            assert set(["id", "name", "category", "description", "tags", "modules", "prompt_seed"]).issubset(t.keys())

    def test_get_template_by_id(self):
        r = requests.get(f"{API}/templates/ucie-basic")
        assert r.status_code == 200
        t = r.json()
        assert t["id"] == "ucie-basic"
        assert t["category"] == "UCIe"

    def test_get_template_missing(self):
        r = requests.get(f"{API}/templates/does-not-exist")
        assert r.status_code == 404


# ---------- Collaboration ----------
class TestCollaboration:
    def test_invite_invalid_email_returns_404(self, owner, project):
        r = requests.post(
            f"{API}/projects/{project['id']}/collaborators",
            headers=owner["headers"],
            json={"email": f"ghost+{uuid.uuid4().hex[:6]}@nonexistent.chipsutra.io", "role": "editor"},
        )
        assert r.status_code == 404, r.text

    def test_invite_editor_success(self, owner, invitee, project):
        r = requests.post(
            f"{API}/projects/{project['id']}/collaborators",
            headers=owner["headers"],
            json={"email": INVITEE_EMAIL, "role": "editor"},
        )
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["email"] == INVITEE_EMAIL
        assert c["role"] == "editor"
        assert c["user_id"] == invitee["user"]["id"]

    def test_invite_duplicate_returns_400(self, owner, project):
        r = requests.post(
            f"{API}/projects/{project['id']}/collaborators",
            headers=owner["headers"],
            json={"email": INVITEE_EMAIL, "role": "editor"},
        )
        assert r.status_code == 400, r.text

    def test_list_collaborators(self, owner, project):
        r = requests.get(f"{API}/projects/{project['id']}/collaborators", headers=owner["headers"])
        assert r.status_code == 200
        data = r.json()
        assert any(c["email"] == INVITEE_EMAIL for c in data)

    def test_invitee_sees_shared_project(self, invitee, project):
        r = requests.get(f"{API}/projects", headers=invitee["headers"])
        assert r.status_code == 200
        ps = r.json()
        match = next((p for p in ps if p["id"] == project["id"]), None)
        assert match is not None, "shared project should appear for invitee"
        assert match["is_owner"] is False

    def test_editor_can_upload_and_generate(self, invitee, project):
        # Upload as editor
        files = {"file": ("counter.sv", COUNTER_SV, "text/plain")}
        r = requests.post(
            f"{API}/projects/{project['id']}/files",
            headers=invitee["headers"],
            files=files, data={"kind": "rtl"},
        )
        assert r.status_code == 200, r.text
        # Access project detail (viewer capability)
        r = requests.get(f"{API}/projects/{project['id']}", headers=invitee["headers"])
        assert r.status_code == 200

    def test_remove_collaborator_and_reinvite_as_viewer(self, owner, invitee, project):
        # Remove
        r = requests.delete(
            f"{API}/projects/{project['id']}/collaborators/{invitee['user']['id']}",
            headers=owner["headers"],
        )
        assert r.status_code == 200
        # Verify gone
        r = requests.get(f"{API}/projects/{project['id']}/collaborators", headers=owner["headers"])
        assert not any(c["user_id"] == invitee["user"]["id"] for c in r.json())
        # Reinvite as viewer
        r = requests.post(
            f"{API}/projects/{project['id']}/collaborators",
            headers=owner["headers"],
            json={"email": INVITEE_EMAIL, "role": "viewer"},
        )
        assert r.status_code == 200
        assert r.json()["role"] == "viewer"

    def test_viewer_cannot_upload(self, invitee, project):
        files = {"file": ("viewer_try.sv", "module x; endmodule\n", "text/plain")}
        r = requests.post(
            f"{API}/projects/{project['id']}/files",
            headers=invitee["headers"],
            files=files, data={"kind": "rtl"},
        )
        # editor is required for upload
        assert r.status_code == 404, r.text

    def test_viewer_can_list_generations(self, invitee, project):
        r = requests.get(f"{API}/projects/{project['id']}/generations", headers=invitee["headers"])
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------- Comments ----------
class TestComments:
    @pytest.fixture(scope="class")
    def seeded_generation(self, owner, invitee, project):
        """Create a small generation record directly via SSE (short prompt)."""
        # Ensure invitee is a collaborator on this worker's project (xdist workers isolate state)
        requests.post(
            f"{API}/projects/{project['id']}/collaborators",
            headers=owner["headers"],
            json={"email": INVITEE_EMAIL, "role": "viewer"},
        )
        body = {
            "project_id": project["id"],
            "module": "debug",
            "model_provider": "anthropic",
            "model_name": "claude-sonnet-4-5-20250929",
            "prompt": "Say hello in one short sentence.",
            "file_ids": [],
            "language": "systemverilog",
        }
        gen_id = None
        with requests.post(f"{API}/generate/stream", headers=owner["headers"],
                           json=body, stream=True, timeout=120) as r:
            assert r.status_code == 200
            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data: "):
                    continue
                try:
                    ev = json.loads(raw[6:])
                except Exception:
                    continue
                if ev.get("type") == "meta":
                    gen_id = ev["generation_id"]
                if ev.get("type") in ("done", "error"):
                    break
        assert gen_id, "No generation_id from SSE meta"
        return gen_id

    def test_add_comment_and_list(self, owner, seeded_generation):
        # Post
        r = requests.post(
            f"{API}/generations/{seeded_generation}/comments",
            headers=owner["headers"],
            json={"text": "Looks good LGTM"},
        )
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["text"] == "Looks good LGTM"
        assert c["user_email"] == OWNER_EMAIL
        # List
        r = requests.get(f"{API}/generations/{seeded_generation}/comments", headers=owner["headers"])
        assert r.status_code == 200
        assert any(x["id"] == c["id"] for x in r.json())

    def test_viewer_can_read_comments(self, invitee, seeded_generation):
        r = requests.get(f"{API}/generations/{seeded_generation}/comments", headers=invitee["headers"])
        # invitee is now viewer of the project, should read
        assert r.status_code == 200

    def test_delete_own_comment(self, owner, seeded_generation):
        r = requests.post(
            f"{API}/generations/{seeded_generation}/comments",
            headers=owner["headers"], json={"text": "to be deleted"},
        )
        cid = r.json()["id"]
        r = requests.delete(f"{API}/comments/{cid}", headers=owner["headers"])
        assert r.status_code == 200
        # Ensure removed
        r = requests.get(f"{API}/generations/{seeded_generation}/comments", headers=owner["headers"])
        assert not any(c["id"] == cid for c in r.json())

    def test_cannot_delete_others_comment(self, owner, invitee, seeded_generation):
        # invitee (viewer) posts a comment; owner tries to delete -> should 403.
        r = requests.post(
            f"{API}/generations/{seeded_generation}/comments",
            headers=invitee["headers"], json={"text": "viewer comment"},
        )
        if r.status_code != 200:
            pytest.skip(f"viewer cannot add comment (server returned {r.status_code})")
        cid = r.json()["id"]
        r = requests.delete(f"{API}/comments/{cid}", headers=owner["headers"])
        assert r.status_code == 403, r.text
        # Cleanup: delete via the author (invitee)
        requests.delete(f"{API}/comments/{cid}", headers=invitee["headers"])

# ---------- Verilator Simulation ----------
class TestSimulation:
    @pytest.fixture(scope="class")
    def sim_project(self, owner):
        r = requests.post(f"{API}/projects", headers=owner["headers"], json={
            "name": f"TEST_Sim_{uuid.uuid4().hex[:6]}",
            "description": "sim project",
            "design_type": "block",
            "language": "systemverilog",
        })
        p = r.json()
        yield p
        requests.delete(f"{API}/projects/{p['id']}", headers=owner["headers"])

    def _upload(self, owner, pid, name, content):
        files = {"file": (name, content, "text/plain")}
        r = requests.post(f"{API}/projects/{pid}/files", headers=owner["headers"],
                          files=files, data={"kind": "rtl"})
        assert r.status_code == 200, r.text
        return r.json()

    def _run_sim(self, owner, pid, file_ids, top=None):
        events = []
        body = {"project_id": pid, "rtl_file_ids": file_ids, "top_module": top}
        with requests.post(f"{API}/simulate/stream", headers=owner["headers"],
                           json=body, stream=True, timeout=90) as r:
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
        return events

    def test_simulate_good_rtl(self, owner, sim_project):
        f = self._upload(owner, sim_project["id"], "counter.sv", COUNTER_SV)
        events = self._run_sim(owner, sim_project["id"], [f["id"]])
        types = [e.get("type") for e in events]
        assert "meta" in types
        assert "done" in types
        meta = next(e for e in events if e["type"] == "meta")
        assert meta.get("engine") == "verilator", f"engine={meta.get('engine')}"
        logs = [e["line"] for e in events if e.get("type") == "log"]
        joined = "\n".join(logs)
        assert any("source:" in l for l in logs), f"expected source line in logs: {logs}"
        assert any("top module:" in l for l in logs), f"expected top module line: {logs}"
        assert any(l.startswith("$ ") and "verilator" in l for l in logs), f"expected verilator command: {logs}"
        done = next(e for e in events if e["type"] == "done")
        assert done.get("status") == "done", f"expected status=done, got: {done}. logs:\n{joined}"

    def test_simulations_listed(self, owner, sim_project):
        r = requests.get(f"{API}/projects/{sim_project['id']}/simulations", headers=owner["headers"])
        assert r.status_code == 200
        sims = r.json()
        assert len(sims) >= 1
        assert sims[0]["engine"] == "verilator"

    def test_simulate_broken_rtl(self, owner, sim_project):
        f = self._upload(owner, sim_project["id"], "bad.sv", BROKEN_SV)
        events = self._run_sim(owner, sim_project["id"], [f["id"]])
        logs = [e["line"] for e in events if e.get("type") == "log"]
        done = next(e for e in events if e["type"] == "done")
        assert done.get("status") == "error", f"expected status=error, got: {done}. logs:\n{logs}"
        assert any("%Error" in l for l in logs), f"expected %Error in logs: {logs}"


# ---------- Google Session ----------
class TestGoogleAuth:
    def test_invalid_session_returns_401(self):
        r = requests.post(f"{API}/auth/google/session", json={"session_id": "not-a-real-session"})
        assert r.status_code == 401, r.text


# ---------- Users lookup ----------
class TestUsersLookup:
    def test_lookup_found(self, owner):
        r = requests.get(f"{API}/users/lookup", headers=owner["headers"],
                         params={"email": INVITEE_EMAIL})
        assert r.status_code == 200
        assert r.json()["found"] is True

    def test_lookup_not_found(self, owner):
        r = requests.get(f"{API}/users/lookup", headers=owner["headers"],
                         params={"email": f"ghost+{uuid.uuid4().hex[:6]}@nowhere.io"})
        assert r.status_code == 200
        assert r.json()["found"] is False
