import asyncio
import json
import os
import sys
import traceback
from fastmcp import Client
from hina_sdk import send_state
from model_call import AICaller, Format, Mode
import subprocess

ai = AICaller()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_SERVERS_DIR = os.path.join(PROJECT_ROOT, "mcp_servers")
USER_CONTEXT_PATH = os.path.join(PROJECT_ROOT, "user_context.json")


def load_user_context():
    if not os.path.isfile(USER_CONTEXT_PATH):
        return {}
    try:
        with open(USER_CONTEXT_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    if len(sys.argv) < 3:
        print("[mcp_call.py] missing args. Usage: mcp_call.py <mcp_server> <query>")
        return None
    return [sys.argv[1], sys.argv[2]]


def _schema_snapshot(tools):
    snap = []
    for t in tools:
        snap.append({
            "name": t.name,
            "description": (t.description or "").strip()[:600],
            "input_schema": t.inputSchema or {},
        })
    return snap


async def agent_manager(mpc_name, mpc_data):
    script_path = os.path.join(MCP_SERVERS_DIR, f"{mpc_name}.py")
    if not os.path.isfile(script_path):
        print(f"[mcp_call.py] no such MCP server script: {script_path}")
        return

    mcp_client = Client(script_path)
    user_ctx = load_user_context()

    async with mcp_client as client:
        send_state(
            agent_name="Refining", state="thinking",
            msg="connecting to the agents", voice=False, done=False,
        )

        tools = await client.list_tools()
        tool_snapshot = _schema_snapshot(tools)
        valid_tool_names = {t.name for t in tools}

        system_prompt = """You are an MCP gateway. Given a list of tools (each with
its JSON input_schema) and a raw, possibly messy/fuzzy user query, do TWO things
in one shot:

1. Pick the single best tool for the query.
2. Build the "arguments" object EXACTLY matching that tool's input_schema --
   correct property names, correct types, only real schema properties.

Rules:
- Clean up spelling/filler from the query when extracting values (e.g. "vedio"
  -> ignore, it's noise; "space_verse repo" -> repo argument value, not the
  whole sentence). Never pass the full raw sentence as an argument value
  unless the schema field is genuinely meant to hold free text (e.g. a search
  query, a comment body, a chat message).
- If a required field is missing from the query AND a matching value exists in
  "known_user_defaults" (fuzzy match by meaning, e.g. github_username ~ owner
  ~ username), use that default. Never invent a value that isn't in the query
  or in known_user_defaults.
- If a required field is truly missing and has no default, leave it out of
  "arguments" rather than guessing -- the caller will report it as invalid.
- Respect enum-like fields (e.g. an "action" argument described as one of a
  fixed set) -- only use one of the allowed values.

Return ONLY this JSON shape, nothing else:
{"tool": "tool_name", "arguments": {"<param>": <value>, ...}}
"""

        ai_res = ai.call(
            prompt=system_prompt,
            query=json.dumps({
                "available_tools": tool_snapshot,
                "known_user_defaults": user_ctx,
                "user_query": mpc_data,
            }),
            format=Format.JSON,
            json_schema_hint={
                "tool": f"must be EXACTLY one of: {sorted(valid_tool_names)}",
                "arguments": "object matching the picked tool's input_schema properties",
            },
        )

        if not ai_res.ok:
            print("AI Call failed to execute successfully.")
            send_state(agent_name="Refining", state="sys_guard",
                       msg="ai call failed", voice=False, done=True)
            return

        try:
            data = json.loads(ai_res.data) if isinstance(ai_res.data, str) else ai_res.data
            tool_name = data.get("tool")
            arguments = data.get("arguments") or {}

            if not tool_name or tool_name not in valid_tool_names:
                send_state(agent_name="Refining", state="sys_guard",
                           msg=f"model picked unknown tool: {tool_name}",
                           voice=False, done=True)
                return

            picked = next(t for t in tools if t.name == tool_name)
            props = (picked.inputSchema or {}).get("properties", {})
            arguments = {k: v for k, v in arguments.items() if k in props}

            send_state(agent_name="Refining", state="sys_action",
                       msg=f"calling tool: {tool_name}", voice=False, done=False)

            result = await client.call_tool(tool_name, arguments)
            print(result)

        except Exception as e:
            print(f"Error parsing AI response: {e}")
            traceback.print_exc()
            send_state(agent_name="Refining", state="sys_guard",
                       msg="tool call failed", voice=False, done=True)


if __name__ == "__main__":
    args = main()
    if args:
        asyncio.run(agent_manager(args[0], args[1]))