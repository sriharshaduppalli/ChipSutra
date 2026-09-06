"""Ollama runtime options — optional num_thread / num_gpu."""
from llm_provider import ollama_runtime_options


def test_ollama_options_default_omits_thread(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_THREAD", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_GPU", raising=False)
    opts = ollama_runtime_options(num_predict=700)
    assert opts["num_predict"] == 700
    assert "num_thread" not in opts
    assert "num_gpu" not in opts


def test_ollama_options_thread_and_cpu_only(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_THREAD", "8")
    monkeypatch.setenv("OLLAMA_NUM_GPU", "0")
    opts = ollama_runtime_options(num_predict=1100, extra={"temperature": 0.08})
    assert opts["num_thread"] == 8
    assert opts["num_gpu"] == 0
    assert opts["num_predict"] == 1100
    assert opts["temperature"] == 0.08


def test_ollama_options_ignores_junk_thread(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_THREAD", "all")
    opts = ollama_runtime_options()
    assert "num_thread" not in opts
