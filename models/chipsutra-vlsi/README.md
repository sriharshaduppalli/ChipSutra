# ChipSutra-VLSI Ollama models (synced)

Canonical source: **[ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM)**

Docker Compose uses `Modelfile.3b` on first startup to create **`chipsutra-vlsi:3b`** from `qwen2.5-coder:3b`.

To change DV behavior, edit modelfiles in the LLM repo, copy here, and rebuild:

```bash
ollama create chipsutra-vlsi:3b -f models/chipsutra-vlsi/Modelfile.3b
```

Set `OLLAMA_MODEL=chipsutra-vlsi:3b` in `backend/.env`.
