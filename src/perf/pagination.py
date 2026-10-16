"""Pagination guard: every GET query parameter that sets a page size must declare a maximum."""

from __future__ import annotations

from typing import Any

PAGE_SIZE_NAMES = ("limit", "page_size", "per_page", "size")


def _maximum(schema: dict[str, Any]) -> float | None:
    if "maximum" in schema:
        return float(schema["maximum"])
    if "exclusiveMaximum" in schema:
        return float(schema["exclusiveMaximum"]) - 1
    for alt in schema.get("anyOf", []) + schema.get("oneOf", []):  # Optional[int] renders as anyOf [int, null]
        found = _maximum(alt)
        if found is not None:
            return found
    return None


def find_unbounded_limits(openapi: dict[str, Any], max_limit: int = 5000) -> list[str]:
    """``METHOD /path ?name`` for each page-size query parameter with no maximum, or one above ``max_limit``."""
    bad: list[str] = []
    for path, item in sorted(openapi.get("paths", {}).items()):
        for method, op in sorted(item.items()):
            if method.lower() != "get" or not isinstance(op, dict):
                continue
            for param in op.get("parameters", []):
                if param.get("in") == "query" and param.get("name") in PAGE_SIZE_NAMES:
                    top = _maximum(param.get("schema", {}))
                    if top is None or top > max_limit:
                        bad.append(f"GET {path} ?{param['name']}")
    return bad
