import os
import sys
import json
import asyncio
import traceback
from fastmcp import Client
from model_call import AICaller, Format, Mode

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_THIS_DIR)
MCP_SERVERS_DIR = os.path.join(PROJECT_ROOT, "mcp_servers")
INDEX_PATH = os.path.join(PROJECT_ROOT, "mcp_index.json")
TOOLS_CACHE_PATH = os.path.join(PROJECT_ROOT, "mcp_tools_cache.json")
USER_CONTEXT_PATH = os.path.join(PROJECT_ROOT, "user_context.json")

ai = AICaller()


def _load_json(path, default):
    if not os.path.isfile(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


async def _fetch_tools_for_server(mcp_name):
    script_path = os.path.join(MCP_SERVERS_DIR, f"{mcp_name}.py")
    if not os.path.isfile(script_path):
        return []
    try:
        client = Client(script_path)
        async with client as c:
            tools = await c.list_tools()
            return [
                {
                    "name": t.name,
                    "description": (t.description or "").strip()[:600],
                    "input_schema": t.inputSchema or {},
                }
                for t in tools
            ]
    except Exception as e:
        print(f"[mcp_router] failed to list tools for {mcp_name}: {e}")
        return []


async def build_tools_cache():
    """
    Spawns every server ONCE, lists its tools, writes them to disk.
    Run this manually (`python mcp_router.py --refresh`) whenever you
    add/change a server. Query time never spawns more than the one
    server it actually needs.
    """
    index = _load_json(INDEX_PATH, {"servers": []})
    cache = {}
    for s in index.get("servers", []):
        cache[s["mcp_name"]] = await _fetch_tools_for_server(s["mcp_name"])
    with open(TOOLS_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"[mcp_router] cached tools for {len(cache)} server(s) -> {TOOLS_CACHE_PATH}")
    return cache


def _load_tools_cache():
    cache = _load_json(TOOLS_CACHE_PATH, None)
    if cache is None:
        # First run, cache doesn't exist yet -- build it once.
        cache = asyncio.run(build_tools_cache())
    return cache


def route_and_call(query: str):
    """
    ONE AI call total. Decides:
      - whether any tool is needed at all (returns None if not -- caller
        falls through to normal chat)
      - which server + which tool
      - what arguments, cleaned and schema-matched, filling gaps from
        user_context.json where it genuinely applies
    Then spawns ONLY the picked server and invokes it.
    """
    index = _load_json(INDEX_PATH, {"servers": []})
    tools_cache = _load_tools_cache()
    user_ctx = _load_json(USER_CONTEXT_PATH, {})

    catalogue = []
    for s in index.get("servers", []):
        name = s["mcp_name"]
        for t in tools_cache.get(name, []):
            catalogue.append({
                "server": name,
                "tool": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
                "server_disambiguation": s.get("disambiguation"),
            })

    system_prompt = """You are HINA's MCP gateway. You get a catalogue of
{server, tool, description, input_schema, server_disambiguation} entries
across ALL available MCP servers, plus a raw (possibly messy/fuzzy) user
query. Decide in one shot:

1. Whether the query genuinely needs a tool right now. Casual chat, asking
   you to write/explain code directly, or anything answerable from general
   knowledge without a live action -> {"server": "NONE"}.
2. Otherwise pick exactly one {server, tool} pair and build "arguments"
   matching that tool's input_schema.

Rules:
- Read "server_disambiguation" carefully when two servers could plausibly
  both match (e.g. "play a youtube video" is playback, not a lookup) --
  it exists specifically to break ties like that.
- Clean spelling/filler out of extracted values. Never dump the entire raw
  query into one argument unless that field is genuinely meant to hold free
  text (a search query, a comment body, a chat message).
- If a required field is missing but a matching value exists in
  "known_user_defaults" (fuzzy match by meaning -- e.g. "username" ~
  "github_username"), use it. Never invent a value that isn't in the query
  or the defaults.
- Omit a field from "arguments" rather than guessing if nothing covers it.

Return ONLY:
{"server": "name_or_NONE", "tool": "tool_name", "arguments": {...}}
"""

    ai_res = ai.call(
        prompt=system_prompt,
        query=json.dumps({
            "available_tools": catalogue,
            "known_user_defaults": user_ctx,
            "user_query": query,
        }),
        format=Format.JSON,
        mode=Mode.COMMAND,
        temperature=0,
        json_schema_hint={
            "server": "exact server name from the catalogue, or NONE",
            "tool": "exact tool name belonging to the picked server",
            "arguments": "object matching the picked tool's input_schema",
        },
    )

    if not ai_res.ok:
        print("[mcp_router] AI call failed.")
        return None

    try:
        data = json.loads(ai_res.data) if isinstance(ai_res.data, str) else ai_res.data
    except Exception:
        return None

    server = data.get("server")
    if not server or server == "NONE":
        return None

    valid_servers = {s["mcp_name"] for s in index.get("servers", [])}
    if server not in valid_servers:
        print(f"[mcp_router] model picked unknown server: {server}")
        return None

    tool_name = data.get("tool")
    server_tools = {t["name"] for t in tools_cache.get(server, [])}
    if not tool_name or tool_name not in server_tools:
        print(f"[mcp_router] model picked unknown tool: {tool_name}")
        return None

    schema_props = next(
        (t["input_schema"].get("properties", {})
         for t in tools_cache.get(server, []) if t["name"] == tool_name),
        {},
    )
    arguments = {k: v for k, v in (data.get("arguments") or {}).items() if k in schema_props}

    return asyncio.run(_invoke(server, tool_name, arguments))


async def _invoke(server, tool_name, arguments):
    script_path = os.path.join(MCP_SERVERS_DIR, f"{server}.py")
    if not os.path.isfile(script_path):
        print(f"[mcp_router] no such server script: {script_path}")
        return None
    client = Client(script_path)
    async with client as c:
        try:
            return await c.call_tool(tool_name, arguments)
        except Exception as e:
            print(f"[mcp_router] tool call failed: {e}")
            traceback.print_exc()
            return None


if __name__ == "__main__":
    # Same contract whether spawned by hina_brain.py's subprocess path,
    # or directly by node: argv[1] = query. Prints one JSON line to
    # stdout so any parent process can just JSON.parse(stdout).
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: mcp_router.py <query>  |  mcp_router.py --refresh"}))
        sys.exit(1)

    if sys.argv[1] == "--refresh":
        asyncio.run(build_tools_cache())
        sys.exit(0)

    query = sys.argv[1]
    result = route_and_call(query)
    print(json.dumps({"result": str(result) if result is not None else None, "handled": result is not None}))