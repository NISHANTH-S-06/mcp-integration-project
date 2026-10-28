import os
import sys

# Add project root directory to the python path to ensure imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.mcp_server import mcp

if __name__ == "__main__":
    # Expose tools through standard stdio transport for Cursor/Windsurf/Claude Desktop
    mcp.run(transport="stdio")
