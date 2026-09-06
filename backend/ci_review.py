"""PR diff review worker — lint changed HDL, classify logs, optional GitHub comment.

Does not clone arbitrary repos. The caller supplies a unified diff (CI workflow)
or ChipSutra reviews the pasted diff. Never executes the diff as a script.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from debug_classify import classify_log

_HDL_NAME = re.compile(r"^[ab]/(.+\.(?:v|sv|vh|svh))$", re.I)
_FILE_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$", re.M)


def list_changed_hdl(diff: str) -> List[str]:
    names: List[str] = []
    for m in _FILE_HEADER.finditer(diff or ""):
        name = (m.group(2) or "").replace("\\", "/")
        low = name.lower()
        if low.endswith((".v", ".sv", ".vh", ".svh")) and name not in names:
            names.append(name)
    return names[:24]


def reconstruct_added(diff: str) -> List[Tuple[str, str]]:
    """Best-effort new-file body from '+' lines (incomplete for context diffs)."""
    files: List[Tuple[str, str]] = []
    current = None
    buf: List[str] = []
    for line in (diff or "").splitlines():
        if line.startswith("diff --git "):
            if current and buf:
                files.append((current, "\n".join(buf) + "\n"))
            current = None
            buf = []
            m = _FILE_HEADER.search(line)
            if m:
                name = m.group(2)
                if name.lower().endswith((".v", ".sv", ".vh", ".svh")):
                    current = name
            continue
        if current is None:
            continue
        if line.startswith("+++ "):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            buf.append(line[1:])
        elif line.startswith("\\"):
            continue
    if current and buf:
        files.append((current, "\n".join(buf) + "\n"))
    return files[:16]


def _static_findings(diff: str) -> List[Dict[str, str]]:
    extras: List[Dict[str, str]] = []
    blob = diff or ""
    if re.search(r"function\s+bit\s+check\s*\(\s*\)\s*;\s*return\s+1\s*;", blob, re.I):
        extras.append(
            {
                "severity": "error",
                "title": "No-op scoreboard",
                "hint": "Do not emit check() that always returns 1 — use a real golden.",
            }
        )
    if re.search(r"beats\s*\+\+", blob):
        extras.append(
            {
                "severity": "warning",
                "title": "beats++ smoke",
                "hint": "Replace beat counters with DUT output checks.",
            }
        )
    if re.search(r"\b(uvm_|`uvm_)", blob) and re.search(r"verilator", blob, re.I):
        extras.append(
            {
                "severity": "warning",
                "title": "UVM + Verilator",
                "hint": "ChipSutra does not claim Verilator UVM sign-off. Prefer Pure SV for this CI.",
            }
        )
    return extras


def _hdl_lint_findings(reconstructed: List[Tuple[str, str]]) -> List[Dict[str, str]]:
    extras: List[Dict[str, str]] = []
    try:
        from sva_lint import lint_sva
        from fcov_lint import lint_fcov
    except Exception:
        return extras
    for name, body in reconstructed:
        if re.search(r"\b(?:assert|cover|assume)\s+property\b|\bproperty\s+\w+\s*;", body, re.I):
            ok, issues = lint_sva(body)
            for iss in issues[:6]:
                extras.append(
                    {
                        "severity": "error" if not ok else "warning",
                        "title": f"SVA {iss}",
                        "hint": f"{name}: ChipSutra SVA lint ({iss})",
                    }
                )
        if re.search(r"\bcovergroup\b", body, re.I):
            ok, issues = lint_fcov(body)
            for iss in issues[:6]:
                extras.append(
                    {
                        "severity": "error" if not ok else "warning",
                        "title": f"FCOV {iss}",
                        "hint": f"{name}: ChipSutra covergroup lint ({iss})",
                    }
                )
        if re.search(r"\bmodule\b", body, re.I) and not re.search(r"\bclass\s+\w+", body, re.I):
            try:
                from fpga_lint import lint_fpga
                ok, issues = lint_fpga(body)
                for iss in issues[:4]:
                    extras.append(
                        {
                            "severity": "warning",
                            "title": f"FPGA {iss}",
                            "hint": f"{name}: ChipSutra FPGA lint ({iss})",
                        }
                    )
            except Exception:
                pass
    return extras


def review_diff(diff: str = "", *, run_verilator: bool = True) -> Dict[str, Any]:
    """Review a unified diff of HDL. Safe on laptops without GitHub."""
    text = diff or ""
    files = list_changed_hdl(text)
    classified = classify_log(text) if text.strip() else {"empty": True, "findings": []}
    findings = list(classified.get("findings") or [])
    findings.extend(_static_findings(text))
    reconstructed = reconstruct_added(text)
    findings.extend(_hdl_lint_findings(reconstructed))
    lint: List[Dict[str, Any]] = []
    if run_verilator:
        try:
            from dv_verify import verilator_bin
        except Exception:
            verilator_bin = lambda: None  # type: ignore
        vbin = verilator_bin()
        if vbin:
            for name, body in reconstructed:
                if "module" not in body.lower() or "endmodule" not in body.lower():
                    continue
                lint.append(_lint_one(vbin, name, body))
    errors = [f for f in findings if (f.get("severity") or "") == "error"]
    lint_fail = [x for x in lint if not x.get("ok")]
    ok = not errors and not lint_fail
    comment = _format_comment(files, findings, lint, ok)
    return {
        "ok": ok,
        "files": files,
        "findings": findings[:12],
        "lint": lint,
        "comment": comment,
        "engine": "chipsutra-ci-review",
    }


def _lint_one(vbin: str, name: str, body: str) -> Dict[str, Any]:
    import subprocess

    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(name).name) or "dut.sv"
    with tempfile.TemporaryDirectory(prefix="chipsutra_ci_") as tmp:
        path = Path(tmp) / safe
        path.write_text(body, encoding="utf-8")
        try:
            proc = subprocess.run(
                [vbin, "--lint-only", "-Wall", "-Wno-fatal", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmp,
            )
        except Exception as e:
            return {"file": name, "ok": False, "log": str(e)[:400]}
        log = ((proc.stderr or "") + "\n" + (proc.stdout or ""))[-2000:]
        return {"file": name, "ok": proc.returncode == 0, "log": log}


def _format_comment(
    files: List[str],
    findings: List[dict],
    lint: List[dict],
    ok: bool,
) -> str:
    lines = [
        "### ChipSutra CI review",
        "Community lint/classify on the PR diff — **not** vendor sign-off.",
        "",
        f"HDL files: {', '.join(files) if files else '(none detected)'}",
        f"Result: {'PASS' if ok else 'NEEDS ATTENTION'}",
    ]
    for f in findings[:8]:
        lines.append(f"- **{f.get('title') or 'finding'}** ({f.get('severity') or 'info'}): {f.get('hint') or f.get('detail') or ''}")
    for item in lint[:6]:
        mark = "ok" if item.get("ok") else "fail"
        lines.append(f"- verilator `{item.get('file')}`: {mark}")
    return "\n".join(lines)


def maybe_post_github_comment(
    *,
    repo: str,
    pr: str,
    body: str,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Post a PR comment when GITHUB_TOKEN is set. No-op otherwise."""
    tok = token or (os.environ.get("GITHUB_TOKEN") or os.environ.get("CHIPSUTRA_GITHUB_TOKEN") or "")
    if not tok or not repo or not pr:
        return {"posted": False, "reason": "missing token/repo/pr"}
    import json
    import urllib.error
    import urllib.request

    url = f"https://api.github.com/repos/{repo}/issues/{pr}/comments"
    req = urllib.request.Request(
        url,
        data=json.dumps({"body": body}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ChipSutra-CI",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"posted": True, "status": resp.status}
    except urllib.error.HTTPError as e:
        return {"posted": False, "reason": f"http {e.code}"}
    except Exception as e:
        return {"posted": False, "reason": str(e)[:200]}
