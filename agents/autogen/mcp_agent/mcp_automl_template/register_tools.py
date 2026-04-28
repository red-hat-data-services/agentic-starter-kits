"""
Register MCP tools from a YAML config. Each tool: name, description, schema_path;
optionally deployment_url_env and deployment_token_env for HTTP deployment.
"""

# Assisted-by: Cursor

import inspect
import json
from os import getenv
from pathlib import Path
from typing import Any

import httpx
import yaml
from utils import json_schema_to_pydantic_model


def _resolve_schema_path(schema_path: str, config_dir: Path) -> Path:
    """Resolve schema_path relative to the config file's directory."""
    p = Path(schema_path)
    if not p.is_absolute():
        p = config_dir / p
    return p.resolve()


def _coerce_null_in_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Convert string 'null' to None so the model accepts omitted values."""
    return {
        k: None if (isinstance(v, str) and v.strip().lower() == "null") else v
        for k, v in kwargs.items()
    }


def _make_tool_handler_flat(
    model_class: type,
    required_field_names: set[str],
    deployment_url_env: str | None = None,
    deployment_token_env: str | None = None,
) -> Any:
    """
    Build a callable with flat keyword arguments (one per schema field).
    Required vs optional follows the JSON schema "required" array.
    """
    fields = model_class.model_fields
    # Required params: annotation as-is. Optional: annotation | None, default None.
    flat_annotations: dict[str, Any] = {}
    params_list: list[inspect.Parameter] = []
    for name in fields:
        info = fields[name]
        if name in required_field_names:
            flat_annotations[name] = info.annotation
            params_list.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=inspect.Parameter.empty,
                    annotation=info.annotation,
                )
            )
        else:
            flat_annotations[name] = info.annotation | None
            params_list.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=info.annotation | None,
                )
            )
    sig = inspect.Signature(parameters=params_list)

    def handler(**kwargs: Any) -> dict | str:
        cleaned = _coerce_null_in_kwargs(kwargs)
        # All model fields: use provided value or None when not required / not provided
        valid = {name: cleaned.get(name) for name in fields}
        instance = model_class(**valid)
        if deployment_url_env and deployment_token_env:
            url = getenv(deployment_url_env)
            token = getenv(deployment_token_env)
            if url and token:
                payload = instance.model_dump()
                # KServe-compatible format: each value wrapped in a list
                data = {"instances": [{key: [val] for key, val in payload.items()}]}
                try:
                    res = httpx.post(
                        url,
                        json=data,
                        verify=True,
                        follow_redirects=True,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=30.0,
                    )
                    res.raise_for_status()
                    out = res.json()
                except httpx.RequestError as e:
                    return f"Deployment request failed: {e}"
                except httpx.HTTPStatusError as e:
                    return f"Deployment returned HTTP {e.response.status_code}: {e.response.text[:500]}"
                if "predictions" in out and out["predictions"]:
                    return str(out["predictions"][0])
                return str(out)
        return instance.model_dump()

    handler.__annotations__ = flat_annotations
    handler.__signature__ = sig
    return handler


def register_tools_from_config(mcp_server: Any, config_path: str | Path) -> None:
    """Load tools from a YAML config and register them on the given FastMCP server."""
    config_path = Path(config_path).resolve()
    config_dir = config_path.parent

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    tools = config.get("tools", [])
    if not tools:
        return

    for tool_cfg in tools:
        name = tool_cfg.get("name")
        description = tool_cfg.get("description", "").strip()
        schema_path = tool_cfg.get("schema_path")
        if not name or not schema_path:
            continue

        resolved = _resolve_schema_path(schema_path, config_dir)
        if not resolved.exists():
            raise FileNotFoundError(f"Schema file not found: {resolved}")

        # Load schema; required/optional from schema "required" array
        with open(resolved, encoding="utf-8") as f:
            schema = json.load(f)
        required_field_names = set(schema.get("required", []))

        model_class = json_schema_to_pydantic_model(
            schema,
            class_name=name.replace("-", "_").title() + "Input",
        )
        handler = _make_tool_handler_flat(
            model_class,
            required_field_names=required_field_names,
            deployment_url_env=tool_cfg.get("deployment_url_env"),
            deployment_token_env=tool_cfg.get("deployment_token_env"),
        )
        handler.__name__ = name
        handler.__doc__ = description

        mcp_server.tool(name=name, description=description)(handler)
