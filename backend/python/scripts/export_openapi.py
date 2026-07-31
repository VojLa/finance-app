"""Export the FastAPI OpenAPI document without starting application lifespan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config.settings import Settings
from app.main import create_app


def export_openapi(output: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=None,
        log_level="ERROR",
        log_json=False,
        docs_enabled=True,
        internal_auth_secret=None,
        _env_file=None,
    )
    schema = create_app(settings).openapi()
    rendered = json.dumps(
        schema,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{rendered}\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    export_openapi(arguments.output.resolve())


if __name__ == "__main__":
    main()
