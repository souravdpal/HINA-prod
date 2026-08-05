import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
core_dir = os.path.join(parent_dir, "core")
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)


from core import hina_sdk
from mcp.server.fastmcp import FastMCP
from mcp_helper import web_google
from mcp_helper import gemini_helper
from mcp_helper import duck_duck
from core import hina_direct
mcp = FastMCP("Web_search mcp")

