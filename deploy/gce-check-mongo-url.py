from pathlib import Path

line = next(
    l
    for l in Path("/opt/chipsutra/backend/.env").read_text().splitlines()
    if l.startswith("MONGO_URL=")
)
url = line[len("MONGO_URL=") :]
print("raw_len", len(url))
print("stripped_len", len(url.strip()))
print("has_cr", "\r" in url)
print("scheme_repr", repr(url.split("://", 1)[0] if "://" in url else url[:20]))
print("has_colon_slash", "://" in url)
print("at_count", url.count("@"))
print("srv_count", url.lower().count("mongodb+srv"))
print("codes_first16", [ord(c) for c in url[:16]])
