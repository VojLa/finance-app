"""Generate a deterministic API inventory from the Python OpenAPI document."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from common import REPOSITORY_ROOT, check_argument, render_document, write_or_check

OUTPUT = REPOSITORY_ROOT / "!docs" / "map" / "generated" / "API-INVENTORY.md"
BACKEND_ROOT = REPOSITORY_ROOT / "backend" / "python"
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")


def export_openapi() -> dict[str, object]:
    with tempfile.TemporaryDirectory(
        prefix="finance-app-docs-openapi-"
    ) as temporary_directory:
        output = Path(temporary_directory) / "openapi.json"
        command = [
            "uv",
            "run",
            "python",
            "-m",
            "scripts.export_openapi",
            "--output",
            str(output),
        ]
        subprocess.run(command, cwd=BACKEND_ROOT, check=True)
        return json.loads(output.read_text(encoding="utf-8"))


def inventory_lines(schema: dict[str, object]) -> list[str]:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        raise RuntimeError("OpenAPI document does not contain a paths object.")

    lines = ["| Method | Path | Operation ID | Summary |", "| --- | --- | --- | --- |"]
    count = 0
    for path, path_item in sorted(paths.items()):
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId", "—")
            summary = operation.get("summary", "—")
            lines.append(
                f"| {method.upper()} | `{path}` | `{operation_id}` | {summary} |"
            )
            count += 1
    lines.insert(0, f"**Operations:** {count}")
    return lines


def main() -> None:
    check = check_argument(__doc__ or "Generate API inventory.")
    schema = export_openapi()
    lines = inventory_lines(schema)
    write_or_check(
        OUTPUT,
        render_document("generate_api_inventory", "API Inventory", "\n\n".join(lines)),
        check=check,
    )


if __name__ == "__main__":
    main()
