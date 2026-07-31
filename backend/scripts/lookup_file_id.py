"""One-off: look up a file id / counter RTL docs in Atlas."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import certifi

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


async def main() -> int:
    fid = sys.argv[1] if len(sys.argv) > 1 else "03d93122-cef4-4a41-bcca-6d737699793f"
    url = os.environ.get("MONGO_URL", "").strip().strip('"').strip("'")
    dbn = os.environ.get("DB_NAME", "chipsutra_db")
    client = AsyncIOMotorClient(url, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=20000)
    db = client[dbn]
    by_id = await db.files.find_one(
        {"id": fid},
        {"_id": 0, "id": 1, "project_id": 1, "original_filename": 1, "is_deleted": 1, "inline_content": 1, "storage_path": 1},
    )
    print("by_id:", by_id)
    cur = (
        db.files.find(
            {"original_filename": {"$regex": "counter", "$options": "i"}},
            {"_id": 0, "id": 1, "project_id": 1, "original_filename": 1, "is_deleted": 1, "inline_content": 1},
        )
        .sort("created_at", -1)
        .limit(10)
    )
    async for d in cur:
        inline = d.get("inline_content") or ""
        print(
            "counter:",
            d.get("id"),
            d.get("project_id"),
            d.get("original_filename"),
            "deleted=",
            d.get("is_deleted"),
            "inline_len=",
            len(inline),
        )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
