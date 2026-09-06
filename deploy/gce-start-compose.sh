#!/bin/bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p = Path("/opt/chipsutra/backend/.env")
t = p.read_text()
adds = []
for k, v in [
    ("CHIPSUTRA_PUBLIC_MODE", "true"),
    ("CHIPSUTRA_REFUSE_MOCK_SIM", "true"),
    ("CHIPSUTRA_BUS_SIM_GATE", "auto"),
]:
    if f"{k}=" not in t:
        adds.append(f"{k}={v}")
if adds:
    p.write_text(t.rstrip() + "\n" + "\n".join(adds) + "\n")
    print("appended", adds)
else:
    print("public flags already present")
PY
docker --version
cd /opt/chipsutra
nohup sudo docker compose -f docker-compose.prod.yml --env-file deploy/.env.prod up -d --build \
  >/tmp/chipsutra-compose.log 2>&1 &
echo "COMPOSE_STARTED pid $!"
sleep 3
tail -n 20 /tmp/chipsutra-compose.log || true
