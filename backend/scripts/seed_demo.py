#!/usr/bin/env python3
"""Create a demo account and load the sample documents into it, through the public API.

Use it to give a recruiter (or yourself) something to try straight away: an account that is already signed up and a
knowledge base that already answers questions. Nothing here touches the database directly, so it works against
a local backend or a deployed one.

    python scripts/seed_demo.py --base-url http://localhost:8000
    python scripts/seed_demo.py --base-url https://production-rag-agent.onrender.com --email demo@example.com

The password is read from DEMO_PASSWORD (or --password); choose one you are happy to publish in the README, and use
an address you do not use anywhere else. The account is an ordinary user: it cannot see anyone else's data. Uploading
uses the Gemini embedding quota (about 8 small documents). Re-running is safe: documents already uploaded are
recognised by their hash and skipped.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

CORPUS = Path(__file__).resolve().parent.parent / "eval" / "corpus"


def sign_in(client: httpx.Client, email: str, password: str) -> str:
    body = {"email": email, "password": password}
    res = client.post("/auth/signup", json=body)
    if res.status_code == 409:   # already exists: sign in instead
        res = client.post("/auth/login", json=body)
    if res.status_code not in (200, 201):
        sys.exit(f"Could not sign in as {email}: {res.status_code} {res.text[:200]}")
    return res.json()["token"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", default="demo@example.com")
    parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD"))
    parser.add_argument("--corpus", type=Path, default=CORPUS, help="folder of documents to upload")
    args = parser.parse_args()
    if not args.password:
        sys.exit("Set DEMO_PASSWORD or pass --password.")

    files = sorted(args.corpus.glob("*.md"))
    if not files:
        sys.exit(f"No .md files found in {args.corpus}")

    # A free-tier backend can take about a minute to wake up, so the timeout is generous
    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        client.headers["Authorization"] = f"Bearer {sign_in(client, args.email, args.password)}"
        print(f"Signed in as {args.email}. Uploading {len(files)} documents ...")

        payload = [("files", (f.name, f.read_bytes(), "text/markdown")) for f in files]
        res = client.post("/upload", files=payload)
        if res.status_code != 200:
            sys.exit(f"Upload failed: {res.status_code} {res.text[:300]}")
        for item in res.json()["documents"]:
            print(f"  {item.get('filename', '?'):<42} {item.get('status', '')}")

        print("Waiting for indexing to finish ...")
        deadline = time.time() + 300
        while time.time() < deadline:
            docs = client.get("/documents").json()["documents"]
            pending = [d for d in docs if d["status"] not in {"completed", "failed", "already_exists"}]
            if not pending:
                break
            time.sleep(3)
        print(f"Done. Sign in with {args.email} and the password you chose.")


if __name__ == "__main__":
    main()
