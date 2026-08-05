import os
import sys

# Add project root (parent of mcp_servers/) to sys.path so that
# `core` and `mcp_helper` are importable when this file is run
# directly as a subprocess by fastmcp's Client.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import open_router
from mcp.server.fastmcp import FastMCP
from core import hina_sdk

mcp = FastMCP("complex tools")


@mcp.tool()
def complex_model(q:str):
    k="""
You are advance model which does the most complex tasks! Your name is Hina
"""
    hina_sdk.send_state(
        agent_name="Hina-pro",
        state="Response...",
        msg="Mapping....",
        color="creative",
        voice=False,
        done=False

    )
    k= open_router.get_reliable_response(user_query=q,system_prompt=k)
    hina_sdk.send_state(
        agent_name="Hina-pro",
        state="Response...",
        msg="Got it...!",
        color="creative",
        text=str(k),
        voice=False,
        done=True
    )
    return k


if __name__=="__main__":
    mcp.run()