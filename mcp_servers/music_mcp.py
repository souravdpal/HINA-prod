import os
import sys

# Add project root (parent of mcp_servers/) to sys.path so that
# `core` and `mcp_helper` are importable when this file is run
# directly as a subprocess by fastmcp's Client.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP
from core import hina_sdk
import subprocess as sub
from mcp_helper import yt_helper
from mcp_helper import vedio_helper

mcp = FastMCP("music tools")

@mcp.tool()
def play_music(que: str) -> str:
    hina_sdk.send_state(
            agent_name="Music mcp",
            state="thinking",
            msg="connected to mcp server..",
            voice=False,
            icon="fa-solid fa-music",
            done=False

        )
    try:
        data = yt_helper.play_vedio(query=que)
        hina_sdk.send_state(
            agent_name="Music player",
            state="sys_action",
            msg=f"playing music..{data}",
            voice=False,
            icon="fa-solid fa-music",
            done=False  # NOT the final push — was `True` before, which
                        # closed the session early and caused every
                        # later push (including the real confirmation)
                        # to be dropped as "no active session".
        )
        player = vedio_helper.MiniPlayer()
        player.play(str(data[1]), video=False)
        hina_sdk.send_state(
            agent_name="Music player",
            state="sys_confirmed",
            msg="playback confirmed",
            text=f"Playing: {data[0]}",
            voice=False,
            icon="fa-solid fa-music",
            done=True 
        )
        return f"Started playing: {data[0]}"

    except RuntimeError as e:
        # RuntimeError from MiniPlayer.play() already carries the real
        # mpv failure reason (missing binary, crash on startup, dead
        # stream URL, etc.) — surface it verbatim instead of masking it.
        hina_sdk.send_state(
            agent_name="Logs",
            state="sys_logs",
            msg="mpv playback failed",
            text=str(e),
            done=True
        )
        return f"Failed to start playback: {str(e)}"

    except Exception as e:
        hina_sdk.send_state(
            agent_name="Logs",
            state="sys_logs",
            msg="Error in system",
            text=f"Error starting mpv: {str(e)}",
            done=True
        )
        return f"Failed to start playback: {str(e)}"


@mcp.tool()
def stop_music(q: str = "") -> str:
    try:
        stopper = vedio_helper.MiniPlayer()
        stopped = stopper.stop()
        if stopped:
            hina_sdk.send_state(
                agent_name="Music player",
                state="sys_confirmed",
                msg="playback stopped",
                text="Stopped playback",
                voice=False,
                icon="fa-solid fa-music",
                done=True
            )
            return "Stopped playback"
        else:
            hina_sdk.send_state(
                agent_name="Music player",
                state="sys_guard",
                msg="nothing was playing",
                voice=False,
                icon="fa-solid fa-music",
                done=True
            )
            return "Nothing was playing"
    except Exception as e:
        hina_sdk.send_state(
            agent_name="Logs",
            state="sys_logs",
            msg="Error stopping playback",
            text=str(e),
            done=True
        )
        return f"Failed to stop playback: {str(e)}"
    

@mcp.tool()
def pause_music():
    pause = vedio_helper.MiniPlayer()
    pause.pause()
    hina_sdk.send_state(
                agent_name="Music player",
                state="sys_confirmed",
                msg="playback paused",
                #text="Stopped playback",
                voice=False,
                icon="fa-solid fa-music",
                done=True
            )
    return "ok"

@mcp.tool()
def resume_music():
    resume_music = vedio_helper.MiniPlayer()
    resume_music.resume()
    hina_sdk.send_state(
                agent_name="Music player",
                state="sys_confirmed",
                msg="resumed music",
                #text="playback",
                voice=False,
                icon="fa-solid fa-music",
                done=True
            )
    
    return "ok"


if __name__ == "__main__":
    mcp.run()