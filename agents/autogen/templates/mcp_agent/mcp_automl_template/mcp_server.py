from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from register_tools import register_tools_from_config
from starlette.requests import Request
from starlette.responses import JSONResponse

load_dotenv()

# Host from env so FastMCP doesn't auto-enable localhost-only DNS rebinding (which rejects Route host).
_host = getenv("HOST", "0.0.0.0")
# Disable DNS rebinding check so any Host (e.g. OpenShift Route) is accepted.
disable_dns_rebinding = (
    getenv("DISABLE_DNS_REBINDING_PROTECTION", "false").lower() == "true"
)
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=not disable_dns_rebinding
)
# Create an MCP server
mcp = FastMCP(
    "MCP AutoML Server",
    log_level="DEBUG",
    host=_host,
    transport_security=_transport_security,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Health check for Kubernetes liveness/readiness probes."""
    return JSONResponse({"status": "healthy"})


# Simple example tools
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


@mcp.tool()
def sub(a: int, b: int) -> int:
    """Subtract two numbers"""
    return a - b


# Register tools from YAML config (name, description, schema_path → Pydantic model + MCP tool)
config_path = Path(__file__).parent / "tools_config.yaml"
register_tools_from_config(mcp, config_path)


if __name__ == "__main__":
    import uvicorn

    app = None
    for attr in ("sse_app", "get_sse_app"):
        fn = getattr(mcp, attr, None)
        if callable(fn):
            app = fn()
            break
    if app is None:
        raise RuntimeError(
            "FastMCP instance has no SSE app callable (sse_app or get_sse_app)"
        )
    port = int(getenv("PORT", 8080))
    forwarded_allow_ips = getenv("UVICORN_FORWARDED_ALLOW_IPS", "*")
    uvicorn.run(app, host=_host, port=port, forwarded_allow_ips=forwarded_allow_ips)
