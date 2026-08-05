import os
import re
import sys

# Add project root (parent of mcp_servers/) to sys.path so that
# `core` and `mcp_helper` are importable when this file is run
# directly as a subprocess by fastmcp's Client.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP
from core import hina_sdk
from mcp_helper import yt_helper

# ------------------------------------------------------------------
# Why this no longer plays audio anywhere near an <audio src="...">:
#
# vedio_helper.MiniPlayer (mpv on the backend machine) is gone on
# purpose — playing audio out of the SAME machine that runs the
# backend meant it came out of that machine's speakers, right next to
# that same machine's /live mic. That's the feedback-loop problem the
# voice pipeline had, one layer up.
#
# The first fix attempt tried handing the raw thing yt_helper resolves
# straight to a browser <audio src="...">. That doesn't work: mpv was
# given that value with --ytdl=yes, meaning mpv's own bundled
# youtube-dl was doing the real resolution to an audio stream
# internally — what yt_helper actually returns is very likely just a
# normal youtube.com/watch?v=... page URL. A browser <audio> tag can't
# play a YouTube webpage at all; it just sits there silent forever,
# which matches exactly what you saw.
#
# The right tool for "play a YouTube video's audio in a browser,
# controllable with real play/pause/stop" is YouTube's own IFrame
# Player API (https://www.youtube.com/iframe_api) — it takes a video
# ID, handles HTTPS/codecs/tokens itself, and exposes a real JS
# control surface (playVideo/pauseVideo/stopVideo). So instead of a
# stream URL, this now extracts the video ID and sends THAT to the
# frontend; app.js/live.js instantiate one shared YT.Player widget
# and drive it directly, no raw <audio>/<video> element involved at
# all. It's deliberately styled as a small floating widget, not the
# full YouTube video MCP surface — same API, different presentation.
# ------------------------------------------------------------------

_VIDEO_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})"
)


def extract_video_id(value: str) -> str:
    """
    Pulls an 11-char YouTube video ID out of whatever yt_helper handed
    back — a full watch URL, a youtu.be short link, an embed URL, or
    (if yt_helper is ever changed to return one directly) a bare ID.
    Raises ValueError with the original value in the message if none
    of those shapes match, so the failure is legible instead of
    silently sending an unplayable widget.
    """
    if not value:
        raise ValueError("empty value from yt_helper")
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    m = _VIDEO_ID_RE.search(value)
    if m:
        return m.group(1)
    raise ValueError(f"could not extract a YouTube video ID from: {value!r}")


mcp = FastMCP("music tools")


@mcp.tool()
def play_music(que: str) -> str:
    hina_sdk.send_state(
        agent_name="Music mcp",
        state="thinking",
        msg="connected to mcp server..",
        icon="fa-solid fa-music",
        done=False
    )
    try:
        data = yt_helper.play_vedio(query=que)
        title, raw_target = data[0], str(data[1])
        video_id = extract_video_id(raw_target)

        hina_sdk.send_state(
            agent_name="Music player",
            state="sys_action",
            msg=f"playing music..{title}",
            icon="fa-solid fa-music",
            done=False
        )

        hina_sdk.send_ui_json(
            {"video_id": video_id, "title": title},
            ui_type="music_player",
            agent_name="Music player",
            state="sys_confirmed",
            msg=f"Playing: {title}",
            icon="fa-solid fa-music",
            done=True
        )
        return f"Started playing: {title}"

    except ValueError as e:
        # extract_video_id failed — surface exactly what yt_helper gave
        # us instead of a generic failure, since this is the case most
        # likely to need a look at yt_helper.py's return shape.
        hina_sdk.send_state(
            agent_name="Logs",
            state="sys_logs",
            msg="could not resolve a playable video ID",
            text=str(e),
            done=True
        )
        return f"Failed to start playback: {str(e)}"

    except RuntimeError as e:
        hina_sdk.send_state(
            agent_name="Logs",
            state="sys_logs",
            msg="playback resolution failed",
            text=str(e),
            done=True
        )
        return f"Failed to start playback: {str(e)}"

    except Exception as e:
        hina_sdk.send_state(
            agent_name="Logs",
            state="sys_logs",
            msg="Error in system",
            text=f"Error starting playback: {str(e)}",
            done=True
        )
        return f"Failed to start playback: {str(e)}"


def _send_music_control(action: str, msg: str) -> None:
    hina_sdk.send_ui_json(
        {"action": action},
        ui_type="music_control",
        agent_name="Music player",
        state="sys_confirmed",
        msg=msg,
        icon="fa-solid fa-music",
        done=True
    )


@mcp.tool()
def stop_music(q: str = "") -> str:
    # The YT.Player widget instance lives entirely in the frontend now
    # — there's nothing running server-side to kill, so this can't
    # accurately report whether anything was really playing. It always
    # confirms the stop instruction was sent.
    _send_music_control("stop", "Stopped playback")
    return "Stopped playback"


@mcp.tool()
def pause_music():
    _send_music_control("pause", "playback paused")
    return "ok"


@mcp.tool()
def resume_music():
    _send_music_control("resume", "resumed music")
    return "ok"


if __name__ == "__main__":
    mcp.run()