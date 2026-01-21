"""Papernote MCP Server for Claude.ai Web."""
import os
import yaml
from mcp.server.fastmcp import FastMCP
from tools.papernote_tools import register_tools

# Load configuration
config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Get server configuration
server_config = config.get("server", {})
port = server_config.get("port", 8000)

# Create MCP server with host/port settings
mcp = FastMCP(
    "PapernoteMCP",
    host="127.0.0.1",
    port=port
)

# Register Papernote tools
register_tools(mcp, config)

if __name__ == "__main__":
    # Run with SSE transport for Claude.ai web
    mcp.run(transport="sse")
