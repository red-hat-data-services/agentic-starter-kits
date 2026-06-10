import json
from os import getenv
from typing import Literal

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, create_model

load_dotenv()


def dataframe_to_json_schema(
    df: pd.DataFrame,
    class_name: str = "GeneratedModel",
    exclude_columns: list[str] | None = None,
    max_enum_size: int = 50,
    required_columns: list[str] | None = None,
) -> dict:
    """
    Retrieve a JSON Schema (dict) from a pandas DataFrame.

    - Numeric columns → "integer" (if all ints) or "number"
    - Object/category columns → "string" with "enum" of unique values (if count <= max_enum_size)
    """
    exclude_columns = exclude_columns or []
    properties: dict = {}
    required: list[str] = required_columns or []
    for col in df.columns:
        if col in exclude_columns:
            continue

        if required_columns is None:
            required.append(col)
        dtype = df[col].dtype
        series = df[col].dropna()

        if pd.api.types.is_numeric_dtype(dtype):
            if (
                pd.api.types.is_integer_dtype(dtype)
                and (series == series.astype(int)).all()
            ):
                properties[col] = {"type": "integer", "title": col}
            else:
                properties[col] = {"type": "number", "title": col}
        else:
            uniques = series.astype(str).unique().tolist()
            if 0 < len(uniques) <= max_enum_size:
                properties[col] = {
                    "type": "string",
                    "enum": sorted(uniques),
                    "title": col,
                }
            else:
                properties[col] = {"type": "string", "title": col}

    return {
        "type": "object",
        "title": class_name,
        "properties": properties,
        "required": required,
    }


def dataframe_to_pydantic_model(
    df: pd.DataFrame,
    class_name: str = "GeneratedModel",
    exclude_columns: list[str] | None = None,
) -> type[BaseModel]:
    """
    Retrieve schema from a pandas DataFrame and create a Pydantic model from it.

    1. Builds a JSON Schema from column names and dtypes (enums from unique values).
    2. Creates and returns a Pydantic model class matching that schema.
    """
    schema = dataframe_to_json_schema(
        df, class_name=class_name, exclude_columns=exclude_columns
    )
    return json_schema_to_pydantic_model(schema, class_name=class_name)


def json_schema_to_pydantic_model(
    schema: dict | str,
    class_name: str | None = None,
) -> type[BaseModel]:
    """
    Create a Pydantic model from a JSON Schema (dict or path to .json file).

    Supports: type (string, integer, number), enum → Literal, required.
    """
    if isinstance(schema, str):
        with open(schema, encoding="utf-8") as f:
            schema = json.load(f)

    props = schema.get("properties", schema)
    required = set(schema.get("required", []))
    class_name = class_name or schema.get("title", "GeneratedModel")
    field_definitions = {}

    for name, prop in props.items():
        if not isinstance(prop, dict):
            raise ValueError(f"Unsupported schema for field {name!r}: {prop!r}")
        if any(key in prop for key in ("$ref", "anyOf", "oneOf", "allOf")):
            raise ValueError(
                f"Unsupported JSON Schema construct in field {name!r}: {prop!r}"
            )
        typ = prop.get("type", "string")
        enum_vals = prop.get("enum")

        if enum_vals is not None:
            if not enum_vals:
                raise ValueError(f"Empty enum is not supported for field {name!r}")
            py_type = Literal.__getitem__(tuple(enum_vals))
        else:
            match typ:
                case "integer":
                    py_type = int
                case "number":
                    py_type = float
                case "boolean":
                    py_type = bool
                case "string":
                    py_type = str
                case _:
                    raise ValueError(
                        f"Unsupported JSON Schema type {typ!r} for field {name!r}"
                    )

        field_definitions[name] = (
            (py_type, ...) if name in required else (py_type | None, None)
        )

    return create_model(class_name, **field_definitions)


def get_chat_from_env():
    """
    ChatOpenAI from BASE_URL, MODEL_ID, and optional API_KEY (OpenAI-compatible API:
    Llama Stack, Ollama, OpenAI, …). Configure everything in `.env` — no separate code path
    for Ollama; use e.g. BASE_URL=http://localhost:11434/v1, MODEL_ID=llama3.2, API_KEY=ollama.
    """
    from langchain_openai import ChatOpenAI

    base_url = getenv("BASE_URL")
    model_id = getenv("MODEL_ID")
    api_key = getenv("API_KEY")
    if base_url is not None:
        base_url = base_url.strip().rstrip("/")
    if model_id is not None:
        model_id = model_id.strip()
    if api_key is not None:
        api_key = api_key.strip()
    if not base_url or not model_id:
        raise ValueError("BASE_URL and MODEL_ID must be set (e.g. in .env). ")
    url = base_url
    if not url.endswith("/v1"):
        url = url + "/v1"
    return ChatOpenAI(
        base_url=url,
        model=model_id,
        api_key=api_key or "not-needed",
        temperature=0.1,
    )


def get_chat_llama_stack():
    from langchain_llama_stack import ChatLlamaStack

    llama_base_url = getenv("LLAMA_STACK_CLIENT_BASE_URL")
    llama_api_key = getenv("LLAMA_STACK_CLIENT_API_KEY")
    model_id = getenv("MODEL_ID")
    if llama_base_url is not None:
        llama_base_url = llama_base_url.strip().rstrip("/")
    if model_id is not None:
        model_id = model_id.strip()
    if llama_api_key is not None:
        llama_api_key = llama_api_key.strip()
    if not llama_base_url or not model_id:
        raise ValueError("LLAMA_STACK_CLIENT_BASE_URL and MODEL_ID must be set")

    url = llama_base_url
    if not url.endswith("/v1"):
        url = url + "/v1"

    return ChatLlamaStack(
        base_url=url,
        api_key=llama_api_key,
        model=model_id,
        temperature=0.1,
    )
