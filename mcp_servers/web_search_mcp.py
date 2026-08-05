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


@mcp.tool()
def web_search_live(querry: str):
    hina_sdk.send_state(
        agent_name="Searching....",
        state="search..",
        msg="Finding latest information ...",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=False
    )

    try:
        data  = duck_duck.scrape_duckduckgo(query=querry)
        k = hina_direct.Hina_res(
            user_query=querry,
            summary=data.get("ai_overview_text", data),
        )
        # k is now the actual generated text (or "" on failure) -- only
        # overwrite the scraped overview if we actually got something back.
        if k:
            data["ai_overview_text"] = k
        """data = web_google.scrape_google_ai(
            query=querry,
            max_retries=3
        )"""


    except Exception as e:
        data = gemini_helper.ask_gemini(query=querry + "GIVE all important links and news and things")
        hina_sdk.send_state(
        agent_name="Web",
        state="found",
        text=str(data.get("response",data)),
        msg="responding..",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=True
    )
        return data



    hina_sdk.send_ui_json(
        data=data,
        state="Found web_data",
        agent_name="web",
        icon="fa-solid fa-magnifying-glass",
        done=False
    )

    hina_sdk.send_state(
        agent_name="Web",
        state="found",
        msg="Found best information for your query",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=True
    )

    return data  # Return actual data instead of just "ok"

@mcp.tool()
def deep_search(querry: str):
    hina_sdk.send_state(
        agent_name="Searching....",
        state="search..",
        msg="Finding Best data in sytsems  ...",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=False
    )

    try:
        data  = duck_duck.scrape_duckduckgo(query=querry)
        k = hina_direct.Hina_res(
            user_query=querry,
            summary=data.get("ai_overview_text", data),
        )
        if k:
            data["ai_overview_text"] = k
        

    except Exception as e:
        data = gemini_helper.ask_gemini(query=querry + "GIVE all important links and news and things")
        hina_sdk.send_state(
        agent_name="Web",
        state="found",
        text=str(data.get("response",data)),
        msg="responding..",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=True
    )
        return data



    hina_sdk.send_ui_json(
        data=data,
        state="Found on web",
        agent_name="web",
        icon="fa-solid fa-magnifying-glass",
        done=False
    )
    data_new = web_google.scrape_google_ai(
        query=querry,
        max_retries=3
    )

    hina_sdk.send_ui_json(
        data=data_new,
        state="Latest Googled..",
        agent_name="web",
        icon="fa-solid fa-magnifying-glass",
        done=False
    )
    data = gemini_helper.ask_gemini(query=str(querry) + "GIVE all important links and news and things")
    hina_sdk.send_state(
        agent_name="Web",
        state="Gathering more information...",
        text=str(data.get("response",data)),
        msg="responding...",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=True
        )

    hina_sdk.send_state(
        agent_name="Web",
        state="found",
        msg="Found best information for your query",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=True
    )

    return str(data)+str(data_new)


if __name__ == "__main__":
    mcp.run()