#!/usr/bin/env python3
"""Write the API's OpenAPI schema to a file, without starting a server or touching any database.

    python scripts/export_openapi.py ../openapi.json

The frontend's generated types (lib/api-client/schema.d.ts) are built from this file with `npm run gen:api`, and CI
fails when the committed types no longer match the backend.
"""

import json
import os
import sys
from pathlib import Path

# Importing the app only builds the routes; nothing connects to PostgreSQL, Qdrant or a model at import time.
# Placeholder settings keep this working on a clean machine and in CI.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET", "openapi-export-only")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pw@localhost:5432/export")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    target.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {target} ({len(app.openapi()['paths'])} paths)")


if __name__ == "__main__":
    main()
