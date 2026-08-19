"""Compact OpenAPI self-description helpers for MCP harness metatools."""

from __future__ import annotations

from typing import Any


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def list_endpoints(
    *,
    tag: str = "",
    path_prefix: str = "",
    limit: int = 120,
) -> dict[str, Any]:
    """Return a compact endpoint catalog from the FastAPI OpenAPI schema."""
    spec = _openapi_spec()
    tag_filter = tag.strip().lower()
    prefix = path_prefix.strip()
    rows: list[dict[str, Any]] = []
    for path, methods in sorted((spec.get("paths") or {}).items()):
        if prefix and not path.startswith(prefix):
            continue
        if not isinstance(methods, dict):
            continue
        for method, operation in sorted(methods.items()):
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            tags = [str(item) for item in operation.get("tags") or []]
            if tag_filter and tag_filter not in {item.lower() for item in tags}:
                continue
            rows.append({
                "method": method.upper(),
                "path": path,
                "operation_id": operation.get("operationId", ""),
                "summary": _compact_text(operation.get("summary") or operation.get("description") or "", 160),
                "tags": tags,
                "has_request_body": "requestBody" in operation,
                "parameters": [param.get("name") for param in operation.get("parameters") or [] if isinstance(param, dict)],
                "responses": sorted((operation.get("responses") or {}).keys()),
            })
            if len(rows) >= max(1, min(int(limit or 120), 300)):
                return {"ok": True, "total": len(rows), "truncated": True, "endpoints": rows}
    return {"ok": True, "total": len(rows), "truncated": False, "endpoints": rows}


def describe_endpoint(*, method: str, path: str) -> dict[str, Any]:
    """Return compact schemas and examples for one endpoint."""
    spec = _openapi_spec()
    normalized_method = method.strip().lower()
    paths = spec.get("paths") or {}
    methods = paths.get(path)
    if not isinstance(methods, dict) or normalized_method not in methods:
        return {
            "ok": False,
            "error": f"Endpoint not found: {method.upper()} {path}",
            "available_methods": sorted(k.upper() for k in (methods or {}).keys() if k.lower() in HTTP_METHODS),
        }

    operation = methods[normalized_method]
    request_schema = _request_schema(operation)
    response_schemas = _response_schemas(operation)
    return {
        "ok": True,
        "method": normalized_method.upper(),
        "path": path,
        "operation_id": operation.get("operationId", ""),
        "summary": _compact_text(operation.get("summary") or "", 240),
        "description": _compact_text(operation.get("description") or "", 600),
        "tags": operation.get("tags") or [],
        "parameters": _parameters(operation, spec),
        "request_body_schema": _compact_schema(request_schema),
        "request_example": _example_for_schema(request_schema, spec),
        "responses": response_schemas,
        "response_examples": {
            status: _example_for_schema(item.get("schema"), spec)
            for status, item in response_schemas.items()
            if item.get("schema")
        },
    }


def _openapi_spec() -> dict[str, Any]:
    from app.main import app

    return app.openapi()


def _request_schema(operation: dict[str, Any]) -> dict[str, Any]:
    body = operation.get("requestBody") or {}
    content = body.get("content") or {}
    media = content.get("application/json") or next(iter(content.values()), {})
    schema = media.get("schema") if isinstance(media, dict) else None
    return schema if isinstance(schema, dict) else {}


def _response_schemas(operation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    responses: dict[str, dict[str, Any]] = {}
    for status, response in (operation.get("responses") or {}).items():
        if not isinstance(response, dict):
            continue
        content = response.get("content") or {}
        media = content.get("application/json") or next(iter(content.values()), {})
        schema = media.get("schema") if isinstance(media, dict) else None
        responses[str(status)] = {
            "description": _compact_text(response.get("description") or "", 240),
            "schema": _compact_schema(schema if isinstance(schema, dict) else {}),
        }
    return responses


def _parameters(operation: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for param in operation.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        schema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
        rows.append({
            "name": param.get("name", ""),
            "in": param.get("in", ""),
            "required": bool(param.get("required", False)),
            "description": _compact_text(param.get("description") or "", 200),
            "schema": _compact_schema(schema),
            "example": _example_for_schema(schema, spec),
        })
    return rows


def _compact_schema(schema: Any, *, depth: int = 0) -> Any:
    if not isinstance(schema, dict):
        return {}
    if depth > 5:
        if "$ref" in schema:
            return {"$ref": schema["$ref"]}
        return {"type": schema.get("type", "object")}

    result: dict[str, Any] = {}
    for key in (
        "$ref",
        "type",
        "format",
        "title",
        "description",
        "enum",
        "default",
        "required",
        "additionalProperties",
        "nullable",
    ):
        if key in schema:
            value = schema[key]
            result[key] = _compact_text(value, 180) if key == "description" else value

    if "items" in schema:
        result["items"] = _compact_schema(schema["items"], depth=depth + 1)
    if "properties" in schema and isinstance(schema["properties"], dict):
        props: dict[str, Any] = {}
        for index, (name, value) in enumerate(schema["properties"].items()):
            if index >= 12:
                props["..."] = {"description": "additional properties omitted from compact schema"}
                break
            props[name] = _compact_schema(value, depth=depth + 1)
        result["properties"] = props
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(schema.get(key), list):
            result[key] = [_compact_schema(item, depth=depth + 1) for item in schema[key][:4]]
    return result


def _example_for_schema(schema: Any, spec: dict[str, Any], *, depth: int = 0) -> Any:
    if not isinstance(schema, dict) or depth > 5:
        return None
    schema = _resolve_schema(schema, spec, depth=depth)
    if not isinstance(schema, dict):
        return None
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        for item in schema["anyOf"]:
            example = _example_for_schema(item, spec, depth=depth + 1)
            if example is not None:
                return example
    if "oneOf" in schema and isinstance(schema["oneOf"], list) and schema["oneOf"]:
        return _example_for_schema(schema["oneOf"][0], spec, depth=depth + 1)
    schema_type = schema.get("type")
    if schema_type == "array":
        return [_example_for_schema(schema.get("items") or {}, spec, depth=depth + 1)]
    if schema_type == "object" or isinstance(schema.get("properties"), dict):
        required = set(schema.get("required") or [])
        example: dict[str, Any] = {}
        for index, (name, prop) in enumerate((schema.get("properties") or {}).items()):
            if index >= 5:
                break
            if name in required or len(example) < 3:
                example[name] = _example_for_schema(prop, spec, depth=depth + 1)
        return example
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True
    if schema_type == "string":
        fmt = schema.get("format")
        if fmt == "date-time":
            return "2026-07-12T00:00:00Z"
        if fmt == "date":
            return "2026-07-12"
        return "string"
    return None


def _resolve_schema(schema: dict[str, Any], spec: dict[str, Any], *, depth: int = 0) -> Any:
    ref = schema.get("$ref")
    if not ref or not isinstance(ref, str) or depth > 5:
        return schema
    if not ref.startswith("#/"):
        return schema
    current: Any = spec
    for part in ref[2:].split("/"):
        if not isinstance(current, dict):
            return schema
        current = current.get(part)
    return current if isinstance(current, dict) else schema


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
