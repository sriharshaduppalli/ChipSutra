"""Diagnose MongoDB Atlas connectivity without printing credentials."""
from __future__ import annotations

import os
import re
import socket
import ssl
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

import certifi  # noqa: E402
from pymongo import MongoClient  # noqa: E402


def _redact(url: str) -> str:
    return re.sub(r":([^:@/]+)@", ":***@", url)


def main() -> int:
    url = os.environ.get("MONGO_URL", "").strip().strip('"').strip("'")
    if not url:
        print("MONGO_URL missing in backend/.env")
        return 1

    print("MONGO_URL (redacted):", _redact(url))
    print("Python:", sys.version.split()[0], "| OpenSSL:", ssl.OPENSSL_VERSION)

    m = re.search(r"mongodb\+srv://[^@]+@([^.]+)\.([^.]+)\.mongodb\.net", url, re.I)
    shard_host: str | None = None
    if m:
        cluster_host = f"{m.group(1)}.{m.group(2)}.mongodb.net"
        try:
            import dns.resolver  # type: ignore

            answers = dns.resolver.resolve(f"_mongodb._tcp.{cluster_host}", "SRV")
            shard_host = str(sorted(answers, key=lambda r: r.target)[0].target).rstrip(".")
        except Exception as e:
            print("SRV lookup failed:", e)
    if shard_host:
        print("Testing raw TLS to", shard_host)
        ctx = ssl.create_default_context(cafile=certifi.where())
        try:
            with socket.create_connection((shard_host, 27017), timeout=15) as sock:
                with ctx.wrap_socket(sock, server_hostname=shard_host) as ss:
                    print("  raw TLS OK:", ss.version(), ss.cipher()[0])
        except Exception as e:
            print("  raw TLS FAIL:", type(e).__name__, e)
            print("  -> Usually Atlas Network Access (IP whitelist) or VPN/SSL inspection.")
    for label, extra in [
        ("certifi", {"tlsCAFile": certifi.where()}),
        ("insecure_certs", {"tlsAllowInvalidCertificates": True}),
    ]:
        try:
            client = MongoClient(url, serverSelectionTimeoutMS=20000, **extra)
            client.admin.command("ping")
            print(f"pymongo [{label}]: OK")
            client.close()
            return 0
        except Exception as e:
            print(f"pymongo [{label}]: {type(e).__name__}: {str(e)[:200]}")

    print("\nNext steps (online Atlas — required for multi-user ChipSutra):")
    print("  1. Atlas -> Network Access -> Allow Access from Anywhere (0.0.0.0/0)")
    print("     End users hit the API only; only the API connects to Atlas.")
    print("  2. Wait until the entry is Active (1–2 min), then re-run this script")
    print("  3. Disable VPN; check antivirus HTTPS scanning")
    print("  4. Helper: powershell scripts/open_atlas_network_access.ps1")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
