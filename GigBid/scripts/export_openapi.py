"""Write the API's OpenAPI schema for the TypeScript client generator (`make gen-api`)."""
import json
import os
from pathlib import Path

os.environ.setdefault("GIGBID_NO_SCHEDULER", "1")
from apps.api.main import app  # noqa: E402

out = Path(__file__).resolve().parents[1] / "apps" / "web" / "openapi.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=1))
print("wrote", out)
