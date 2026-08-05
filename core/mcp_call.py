import asyncio
import json
import os
import sys
import traceback
from fastmcp import Client
from hina_sdk import send_state
from model_call import AICaller, Format, Mode

ai = AICaller()

# core/mcp_call.py -> project root -> mcp_servers/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_SERVERS_DIR = os.path.join(PROJECT_ROOT, "mcp_servers")


def main():
    if len(sys.argv) < 3:
        print(
            "[mcp_call.py] missing args. Usage: mcp_call.py <mcp_server> <query>"
        )
        return None

    mcp_server = sys.argv[1]
    query = sys.argv[2]
    return [mcp_server, query]


async def agent_manager(mpc_name, mpc_data):
    # Point the client at the actual server script, not a dotted module path.
    # fastmcp spawns it as a subprocess over stdio transport.
    script_path = os.path.join(MCP_SERVERS_DIR, f"{mpc_name}.py")
    if not os.path.isfile(script_path):
        print(f"[mcp_call.py] no such MCP server script: {script_path}")
        return

    mcp_client = Client(script_path)

    async with mcp_client as client:
        send_state(
            agent_name="Refining",
            state="thinking",
            msg="connecting to the agents",
            voice=False,
            done=False,
        )

        # Await the available tools from the MCP server
        tools = await client.list_tools()

        # Execute the AI structured call
        ai_res = ai.call(
            prompt="""You are an advanced MCP gateway that determines which tool to use.
Return a valid JSON response identifying the single most appropriate tool for the user query.

Format:
{
    "tools": "tool_name"
}
""",
            query=f"Available tools: {tools}\nUser query: {mpc_data}",
            format=Format.JSON,
            json_schema_hint={"tools": "tool_name"},
        )

        if ai_res.ok:
            try:
                # Handle both dict data or raw string data that needs parsing
                data = (
                    json.loads(ai_res.data)
                    if isinstance(ai_res.data, str)
                    else ai_res.data
                )
                tool_name = data.get("tools")
                print(tool_name)

                if not tool_name:
                    send_state(
                        agent_name="Refining",
                        state="sys_guard",
                        msg="no tool selected",
                        voice=False,
                        done=True,
                    )
                    return

                valid_tool_names = {t.name for t in tools}
                if tool_name not in valid_tool_names:
                    send_state(
                        agent_name="Refining",
                        state="sys_guard",
                        msg=f"model picked unknown tool: {tool_name}",
                        voice=False,
                        done=True,
                    )
                    return

                # Find the picked tool's schema so we know what argument name
                # to send the query under (e.g. play_music expects "que").
                picked = next(t for t in tools if t.name == tool_name)
                props = (picked.inputSchema or {}).get("properties", {})
                arg_name = next(iter(props), "query")  # fall back to "query"

                send_state(
                    agent_name="Refining",
                    state="sys_action",
                    msg=f"calling tool: {tool_name}",
                    voice=False,
                    done=False,
                )

                # Actually invoke the selected tool with the user's query.
                result = await client.call_tool(tool_name, {arg_name: mpc_data})
                print(result)

            except Exception as e:
                print(f"Error parsing AI response: {e}")
                traceback.print_exc()
                send_state(
                    agent_name="Refining",
                    state="sys_guard",
                    msg="tool call failed",
                    voice=False,
                    done=True,
                )
        else:
            print("AI Call failed to execute successfully.")
            send_state(
                agent_name="Refining",
                state="sys_guard",
                msg="ai call failed",
                voice=False,
                done=True,
            )


if __name__ == "__main__":
    args = main()
    if args:
        mpc_name = args[0]
        mpc_data = args[1]
        # Execute the async main loop loop safely
        asyncio.run(agent_manager(mpc_name, mpc_data))