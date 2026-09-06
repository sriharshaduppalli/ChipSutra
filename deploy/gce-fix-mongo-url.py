"""Repair a doubled/broken MONGO_URL without printing the password."""
from pathlib import Path
import re

p = Path("/opt/chipsutra/backend/.env")
lines = p.read_text().splitlines()
out = []
fixed = False
for line in lines:
    if not line.startswith("MONGO_URL="):
        out.append(line)
        continue
    url = line[len("MONGO_URL=") :].strip()
    matches = re.findall(
        r"chipsutra_db_user:([^@]+)@cluster0\.9cw3ej4\.mongodb\.net",
        url,
    )
    if not matches:
        raise SystemExit("cannot find chipsutra_db_user:@cluster0 in MONGO_URL")
    pw = matches[-1]
    if "mongodb" in pw or "://" in pw or " " in pw:
        raise SystemExit("extracted password still looks like a full URL")
    new = (
        "mongodb+srv://chipsutra_db_user:"
        + pw
        + "@cluster0.9cw3ej4.mongodb.net/chipsutra_prod"
        + "?retryWrites=true&w=majority&appName=Cluster0"
    )
    out.append("MONGO_URL=" + new)
    fixed = True
    print("repaired scheme=mongodb+srv host=cluster0.9cw3ej4.mongodb.net")
if not fixed:
    raise SystemExit("no MONGO_URL line")
p.write_text("\n".join(out) + "\n")
