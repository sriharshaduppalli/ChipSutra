"""KG / generation learning scores from auto-lint + user feedback."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _has_independent_golden(output: str) -> bool:
    if not output:
        return False
    if "expected" in output and "expected = expected +" in output:
        return True
    if "q[$]" in output or ("push_back" in output and "pop_front" in output):
        return True
    if "model_reg" in output and "s_axi_" in output:
        return True
    if "!== ^" in output or "parity !== ^" in output or "=== ^" in output:
        return True
    return False


def auto_score_testbench(output: str, engine: str, lint_ok: Optional[bool], lint_issues: Optional[List[str]]) -> Dict[str, Any]:
    """Heuristic quality score 0..100 for a TB generation."""
    score = 50.0
    reasons: List[str] = []
    eng = (engine or "").lower()
    if eng in ("skeleton", "skeleton_fallback"):
        score = 88.0
        reasons.append("verified_template")
        if eng == "skeleton_fallback":
            score = 82.0
            reasons.append("llm_replaced_by_template")
    elif eng in ("llm", "llm_repaired"):
        # Lint-clean LLM should be able to reach SOLID (>=80), not cap at 75
        score = 70.0
        reasons.append("llm_raw" if eng == "llm" else "llm_repaired")
    if lint_ok is True:
        score = min(100.0, score + 12.0)
        reasons.append("lint_pass")
    elif lint_ok is False:
        score = max(0.0, score - 25.0)
        reasons.append("lint_fail:" + ",".join((lint_issues or [])[:4]))
    if output:
        if "$urandom" in output or "$urandom_range" in output:
            score = min(100.0, score + 4.0)
            reasons.append("has_random")
        if "$dump" in output:
            score = min(100.0, score + 2.0)
        if _has_independent_golden(output):
            score = min(100.0, score + 6.0)
            reasons.append("independent_golden")
        elif "expected" in output and "count + 1" not in output.replace("expected = expected + 1", ""):
            score = min(100.0, score + 2.0)
            reasons.append("counter_golden_weak")
    return {"auto_score": round(score, 1), "auto_reasons": reasons}


def combine_with_feedback(auto_score: float, rating: Optional[int]) -> float:
    """rating: 1 = up, -1 = down, None = none."""
    if rating is None:
        return auto_score
    if rating > 0:
        return round(min(100.0, auto_score + 10.0), 1)
    if rating < 0:
        return round(max(0.0, auto_score - 20.0), 1)
    return auto_score


def aggregate_learning_report(docs: List[dict]) -> Dict[str, Any]:
    """Compute KG learning effectiveness from recent generation docs."""
    if not docs:
        return {
            "kg_learning_score": None,
            "sample_size": 0,
            "trend": "insufficient_data",
            "note": "Generate + rate outputs to unlock the learning score.",
        }

    scores: List[float] = []
    ups = downs = 0
    skeleton_n = llm_n = fallback_n = 0
    lint_pass = lint_fail = 0

    for d in docs:
        learn = d.get("learning") or {}
        s = learn.get("final_score")
        if s is None:
            s = learn.get("auto_score")
        if s is not None:
            scores.append(float(s))
        r = learn.get("user_rating")
        if r == 1:
            ups += 1
        elif r == -1:
            downs += 1
        eng = (d.get("engine") or learn.get("engine") or "").lower()
        if eng == "skeleton":
            skeleton_n += 1
        elif eng == "skeleton_fallback":
            fallback_n += 1
        elif eng in ("llm", "llm_repaired"):
            llm_n += 1
        if learn.get("lint_ok") is True:
            lint_pass += 1
        elif learn.get("lint_ok") is False:
            lint_fail += 1

    n = len(scores)
    avg = sum(scores) / n if n else 0.0
    # Trend: compare first half vs second half of chronological (docs are newest-first)
    chrono = list(reversed(scores))
    mid = max(1, n // 2)
    early = sum(chrono[:mid]) / mid
    late = sum(chrono[mid:]) / max(1, n - mid) if n > mid else early
    if n < 4:
        trend = "insufficient_data"
    elif late - early >= 5:
        trend = "improving"
    elif early - late >= 5:
        trend = "declining"
    else:
        trend = "stable"

    # Feedback quality weight
    rated = ups + downs
    feedback_boost = 0.0
    if rated:
        feedback_boost = 8.0 * ((ups - downs) / rated)

    kg = min(100.0, max(0.0, avg + feedback_boost))
    if kg >= 90:
        grade = "A"
    elif kg >= 80:
        grade = "B"
    elif kg >= 70:
        grade = "C"
    elif kg >= 60:
        grade = "D"
    else:
        grade = "F"

    return {
        "kg_learning_score": round(kg, 1),
        "grade": grade,
        "sample_size": n,
        "avg_auto_score": round(avg, 1) if n else None,
        "trend": trend,
        "user_thumbs_up": ups,
        "user_thumbs_down": downs,
        "engines": {"skeleton": skeleton_n, "llm": llm_n, "skeleton_fallback": fallback_n},
        "lint": {"pass": lint_pass, "fail": lint_fail},
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Score blends auto-lint quality with user +useful/-weak feedback.",
    }
