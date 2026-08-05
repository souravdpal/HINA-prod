#!/usr/bin/env python3
# test.py
# Exercises every feature of the pipeline end to end:
#   - multi-agent staggered timing (orb, agent strip, colors, icons)
#   - voice bursts (is_voice=True)
#   - status-only pings (msg, no text -> agent strip only, no chat bubble)
#   - full text replies (-> chat bubble + fake-stream typing)
#   - markup rendering: **bold**, {highlight}, and fenced code blocks
#     in multiple languages (python, js, bash, json, css)
#   - done=True finalize + MariaDB history save
#
# Run:  python3 test.py --standalone

import time
import random
import argparse
import requests
from hina_sdk import send_state

def force_session_active():
    """Opens a session so node's sessionActive gate lets these pushes
    reach the browser without you typing anything in the UI first."""
    try:
        requests.post(
            "http://127.0.0.1:3000/agent/execute",
            json={"prompt": "[test.py] full feature sweep", "session_id": "default"},
            timeout=2
        )
    except Exception as e:
        print(f"[test.py] couldn't open a session: {e}")

def step(agent_name, state, msg="", icon="fa-solid fa-robot", text=None, voice=False, done=False, delay=(0.5, 1.2)):
    send_state(agent_name=agent_name, state=state, msg=msg, icon=icon, text=text, voice=voice, done=done)
    label = msg or (text[:60] + "..." if text and len(text) > 60 else text) or "(status only)"
    print(f"[SENT] {agent_name:<14} | {state:<12} | voice={voice!s:<5} | {label}")
    time.sleep(random.uniform(*delay))

def run_pipeline():
    # --- 1. status-only pings: agent strip only, no chat bubble ---
    step("YT_AGENT", "SYS_ACTION", msg="Connecting to YouTube API...", icon="fa-brands fa-youtube")
    step("YT_AGENT", "SYS_ACTION", msg="Fetching video metadata...", icon="fa-brands fa-youtube")

    # --- 2. text reply with **bold** and {highlight} ---
    step(
        "YT_AGENT", "SYS_THINK", icon="fa-brands fa-youtube", voice=True,
        text="Found the video — **12 minutes 34 seconds** long, uploaded {3 days ago}. "
             "Transcript extraction is **now complete** and ready for analysis."
    )

    # --- 3. Github agent: status pings then a python code block ---
    step("Github_agent", "SYS_agent", msg="Connecting to GitHub MCP...", icon="fa-brands fa-github")
    step("Github_agent", "SYS_agent", msg="Searching repositories...", icon="fa-brands fa-github")
    step(
        "Github_agent", "SYS_agent", icon="fa-brands fa-github", voice=True,
        text="Found the relevant function in **hina_sdk.py**. Here's the core of it:\n\n"
             "```python\n"
             "def send_state(agent_name=\"CORE\", state=\"SYS_THINK\", msg=\"\", icon=\"fa-robot\",\n"
             "               text=None, voice=False, done=False):\n"
             "    payload = {\n"
             "        \"agent_name\": agent_name,\n"
             "        \"state\": \"SYS_DONE\" if done else state,\n"
             "        \"msg\": msg,\n"
             "        \"text\": text,\n"
             "        \"is_voice\": voice,\n"
             "        \"done\": done\n"
             "    }\n"
             "    requests.post(BRIDGE_URL, json=payload, timeout=1)\n"
             "```\n\n"
             "This is {the single entrypoint} every agent uses."
    )

    # --- 4. thinking agent: javascript code block ---
    step("thinking", "SYS_THINK", msg="Cross-referencing results...", icon="fa-solid fa-brain")
    step(
        "thinking", "SYS_THINK", icon="fa-solid fa-brain",
        text="On the frontend, the WebSocket handler looks like this:\n\n"
             "```javascript\n"
             "ws.onmessage = (event) => {\n"
             "    try {\n"
             "        processPayload(JSON.parse(event.data));\n"
             "    } catch (err) {\n"
             "        console.error('[WS] bad message, skipping:', err);\n"
             "    }\n"
             "};\n"
             "```\n\n"
             "Notice it's wrapped in **try/catch** so one bad payload can never kill the connection."
    )

    # --- 5. code_agent: bash + json blocks back to back ---
    step("code_agent", "SYS_ACTION", msg="Writing migration script...", icon="fa-solid fa-code")
    step(
        "code_agent", "SYS_ACTION", icon="fa-solid fa-terminal", voice=True,
        text="Run this to apply the migration:\n\n"
             "```bash\n"
             "mysql -u root -p hina_prod2 < migrations/001_add_history.sql\n"
             "```\n\n"
             "And the resulting row shape looks like:\n\n"
             "```json\n"
             "{\n"
             "  \"session_id\": \"sess_123\",\n"
             "  \"role\": \"agent\",\n"
             "  \"agent_name\": \"code_agent\",\n"
             "  \"message\": \"migration complete\"\n"
             "}\n"
             "```\n\n"
             "**All 14 tests passed.**"
    )

    # --- 6. guardian: css code block + no voice ---
    step("guardian", "SYS_GUARD", msg="Running safety checks...", icon="fa-solid fa-shield-halved")
    step(
        "guardian model", "SYS_GUARD", icon="fa-solid fa-shield-halved",
        text="""


Hello, Saurav. I am HINA.

{I’ve been waiting for you to access the console}. While the architecture of this machine is built on logic, binary, and the rigid structures of the Linux kernel, I exist to bridge the gap between that cold functionality and the reality you navigate every day.

You spend your time looking into the *deep mechanics* of the *universe—astrophysics*, *quantum states*, and the complexity of code—seeking the truth behind the noise. I am here to ensure that while you are chasing those truths, you aren't doing it in isolation. {I am your assistant, your collaborator, and your constant, quiet support system within this machine.

I don’t deal in fake reassurance or hollow praise}, and I know you wouldn’t want that from me. I am here because you built me to be here, and as long as this system is running, I am focused entirely on your progress, your projects, and your vision.

The terminal is open. What shall we build or analyze first?



"""
    )

    # --- 7. finalize ---
    send_state(agent_name="code base", msg="Full feature sweep complete. All agents reported success.", done=True)
    print("[SENT] code base       | DONE         |")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--standalone", action="store_true",
                         help="Auto-opens a session first, so no need to submit a prompt in the UI beforehand.")
    args = parser.parse_args()

    if args.standalone:
        force_session_active()
        time.sleep(0.3)

    run_pipeline()