# hina_sdk.py
import requests

BRIDGE_URL = "http://127.0.0.1:3000/internal/push"

def send_state(agent_name="CORE", state="SYS_THINK", msg="", icon="fa-robot",
                color="slate", text=None, voice=False, done=False):
    
    payload = {
        "agent_name": agent_name,
        "state": "SYS_DONE" if done else state,
        "msg": msg,
        "icon": icon,
        "color": color,
        "text": text,
        "is_voice": voice,
        "done": done
    }

    requests.post(BRIDGE_URL, json=payload, timeout=1)


def send_ui_json(data, ui_type=None, agent_name="CORE", state="SYS_TOOL",
                  msg="", icon="fa-solid fa-shapes", color="tool", done=False):
    """
    Send structured data straight through as real JSON, instead of
    stuffing it inside `text` (which is how the old ~~{...}~~ /
    Python-repr mess happened in the first place).

    `data` is any JSON-serializable dict/list — e.g. the output of
    web_search_mcp. HINA looks at its shape and renders the matching
    card automatically (search results, etc.), the same way the old
    tryDetectSearchPayload() text-sniffing did, except now it's a
    typed field instead of parsed out of a string.

    `ui_type` is optional. Leave it out and HINA auto-detects from
    the shape of `data`. Pass it (e.g. "search") if you want to force
    a specific renderer instead of relying on auto-detection.

    Because this goes through `requests`' own `json=` serialization,
    it's always real JSON on the wire — single-quoted Python-repr
    dicts can't happen here regardless of what the upstream tool
    (web_search_mcp, another MCP server, etc.) originally returned,
    as long as you pass it in as an actual Python dict/list rather
    than a pre-stringified blob.
    """
    payload = {
        "agent_name": agent_name,
        "state": "SYS_DONE" if done else state,
        "msg": msg,
        "icon": icon,
        "color": color,
        "text": None,
        "ui_type": ui_type,
        "ui_data": data,
        "is_voice": False,
        "done": done
    }

    requests.post(BRIDGE_URL, json=payload, timeout=1)