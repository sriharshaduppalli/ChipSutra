from tb_llm_repair import should_llm_repair, build_repair_user_prompt


def test_should_repair_on_hard_leftover():
    assert should_llm_repair(issues=["circular_golden"], competitive_score=50) is True
    # Semantic golden bugs (e.g. FIFO without a queue model) need the model, not regex.
    assert should_llm_repair(issues=["semantic_fifo_no_queue"], competitive_score=80) is True
    assert should_llm_repair(issues=["semantic_circular_out"], competitive_score=80) is True
    assert should_llm_repair(issues=["undeclared_signal:enable"], competitive_score=80) is True
    assert should_llm_repair(issues=[], competitive_score=95, premium_bar=True) is False
    # Soft nits after mechanical — do not burn a 2nd LLM pass
    assert should_llm_repair(
        issues=["errors_not_initialized", "missing_post_reset_settle"],
        competitive_score=85,
        premium_bar=False,
    ) is False


def test_repair_prompt_lists_issues():
    p = build_repair_user_prompt("module x; endmodule", ["task_with_return"], dut_hint="counter")
    assert "task_with_return" in p
    assert "counter" in p
    assert "module x" in p
