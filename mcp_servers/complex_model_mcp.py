import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import model_call
from mcp.server.fastmcp import FastMCP
from core import hina_sdk
from core import voice_stat
from core import hin_voice_engine

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
    ai = model_call.AICaller()
    k=ai.call(
        prompt="You are advace model used for heavy complex task use your full brain and solve question given",
        query=q,
        mode=model_call.Mode.COMPLEX,
        format=model_call.Format.TEXT
    )
    if(voice_stat.is_voice_on()==True):
            hin_voice_engine.run_hina_voice(text=k.text)
    hina_sdk.send_state(
        agent_name="Hina-pro",
        state="Response...",
        msg="Got it...!",
        color="creative",
        text=str(k.text),
        voice=False,
        done=True
    )
    return k


if __name__=="__main__":
    mcp.run()