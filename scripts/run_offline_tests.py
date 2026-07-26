#!/usr/bin/env python3
"""Run the offline backend suite (no live Mongo/Ollama/EDA tools required).

Shared by CI and scripts/validate-community.*. Suites that do not exist yet are
reported and skipped rather than failing the run, so adding a planned test file
is never a breaking change for the pipeline.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"

# Fully offline suites.
SUITES = [
    "tests/test_credibility_targets.py",
    "tests/test_eda_industry.py",
    "tests/test_coverage_industry.py",
    "tests/test_fst_cdc.py",
    "tests/test_rag_vector_golden.py",
    "tests/test_rag_and_golden.py",
    "tests/test_rtl_ports_and_feedback.py",
    "tests/test_wiring.py",
]

# Mixed suite: only the checks that need no services. `fresh_clone` is excluded
# because it clones the public remote, so it tests GitHub rather than this tree.
LEGACY_SUITE = "tests/test_iteration_5.py"
LEGACY_FILTER = (
    "(docker_compose or env_example or requirements or readme "
    "or available_providers or stream_chat) and not fresh_clone"
)


def run(args: list[str]) -> int:
    print(f"\n$ pytest {' '.join(args)}", flush=True)
    env = dict(os.environ)
    env.setdefault("MONGO_URL", "mongodb://localhost:27017")
    env.setdefault("DB_NAME", "chipsutra_ci")
    return subprocess.run([sys.executable, "-m", "pytest", *args], cwd=BACKEND, env=env).returncode


def main() -> int:
    present = [s for s in SUITES if (BACKEND / s).exists()]
    missing = [s for s in SUITES if s not in present]
    if missing:
        print("Skipping absent suites: " + ", ".join(missing))
    if not present:
        print("No offline suites found — nothing to run.")
        return 1

    rc = run(["-n", "0", "-q", *present])
    if rc != 0:
        return rc

    if (BACKEND / LEGACY_SUITE).exists():
        rc = run(["-n", "0", "-q", LEGACY_SUITE, "-k", LEGACY_FILTER])
    return rc


if __name__ == "__main__":
    sys.exit(main())
