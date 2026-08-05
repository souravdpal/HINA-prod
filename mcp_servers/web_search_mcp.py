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
from mcp_helper import gemini_helper
from mcp_helper import search_engine  # unified duckduckgo+google module
from core import hina_direct
from core import voice_stat
from core import hin_voice_engine

mcp = FastMCP("Web_search mcp")


def _speak_if_enabled(text):
    if text and voice_stat.is_voice_on():
        hin_voice_engine.run_hina_voice(text=text)


def _extract_gemini_text(gemini_data):
    """gemini_helper.ask_gemini() doesn't raise on failure -- it returns a
    dict like {'status': 'error', 'reason': '...'}. Left unchecked, that
    dict gets str()'d straight into the answer the user sees. This pulls
    out real text only, and returns None for anything that looks like an
    error payload."""
    if not isinstance(gemini_data, dict):
        text = str(gemini_data) if gemini_data else None
        return text
    if gemini_data.get("status") == "error":
        return None
    response = gemini_data.get("response")
    if response:
        return str(response)
    # No "response" key and no error status -- unknown shape, don't guess.
    return None


def _gemini_fallback(query):
    """Used only when the browser-based engines fail completely."""
    gemini_data = gemini_helper.ask_gemini(query=query + " GIVE all important links and news and things")
    text = _extract_gemini_text(gemini_data)
    if not text:
        text = "Sorry, I couldn't reach any search sources right now -- please try again in a moment."
    _speak_if_enabled(text)
    hina_sdk.send_state(
        agent_name="Web",
        state="found",
        text=text,
        msg="responding..",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=True,
    )
    return {"status": "error", "query": query, "ai_overview_text": text} if not isinstance(gemini_data, dict) or gemini_data.get("status") == "error" else gemini_data


@mcp.tool()
def web_search_live(querry: str):
    """Fast web search: DuckDuckGo first, Google fills gaps, deep-crawl
    backfill only kicks in if both are thin. Returns overview text, images,
    and organic sources."""
    hina_sdk.send_state(
        agent_name="Searching....",
        state="search..",
        msg="Finding latest information ...",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=False,
    )

    try:
        # Keep this snappy: smaller organic pull and far fewer fallback
        # page-crawls than deep_search, so Google only gets hit when DDG
        # is genuinely thin (see unified_search's own thin-check) and we
        # don't wait around peeking at extra pages unless truly needed.
        data = search_engine.unified_search(
            query=querry,
            mode="fast",
            image_limit=7,
            min_images=3,
            min_sources=5,
            organic_limit=15,
            max_fallback_sites=2,
        )

        if data.get("status") != "success":
            raise RuntimeError(data.get("reason") or "unified_search returned no data")

        # Ask Hina to turn the raw overview into a spoken/direct answer.
        # IMPORTANT: only replace ai_overview_text with the generated reply
        # if we actually got one back -- never blank out real scraped data.
        spoken = hina_direct.Hina_res(
            user_query=querry,
            summary=data.get("ai_overview_text") or "",
            done=False,
        )
        if spoken:
            data["ai_overview_text"] = spoken
            _speak_if_enabled(spoken)

    except Exception as e:
        return _gemini_fallback(querry)
    new_Data =data
    new_Data["ai_overview_text"]=""
    hina_sdk.send_ui_json(
        data=new_Data,
        state="Found web_data",
        agent_name="web",
        icon="fa-solid fa-magnifying-glass",
        done=False,
    )
    hina_sdk.send_state(
        agent_name="Web",
        state="found",
        msg="Found best information for your query",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=True,
    )
    return data

@mcp.tool()
def deep_search(querry: str):
    """Thorough search: DuckDuckGo + Google merged, aggressive direct-page
    deep-crawl for images/overview/link backfill, plus a Gemini pass for
    extra context -- all merged into ONE final AI response (the query is
    only ever answered once, never sent twice as two separate replies).
    Use when the user wants comprehensive coverage, not just a quick
    answer."""
    hina_sdk.send_state(
        agent_name="Searching....",
        state="search..",
        msg="Finding best data across sources ...",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=False,
    )

    try:
        # Push "deep" mode harder than the defaults: more organic results,
        # more images, and more actual page crawls so this is meaningfully
        # more thorough than the fast search rather than just a relabeled
        # version of it.
        data = search_engine.unified_search(
            query=querry,
            mode="deep",
            image_limit=12,
            min_images=6,
            min_sources=8,
            organic_limit=30,
            max_fallback_sites=8,
        )

        if data.get("status") != "success":
            raise RuntimeError(data.get("reason") or "unified_search returned no data")

    except Exception:
        return _gemini_fallback(querry)

    hina_sdk.send_state(
        agent_name="Web",
        state="Gathering more information...",
        msg="Cross-checking with more sources ...",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=False,
    )

    # Extra context pass -- gathered, but NOT sent to the user as its own
    # separate reply/voice line. It's merged with the scraped overview
    # below and fed into a single Hina_res call so the model only answers
    # the query once instead of twice.
    scraped_overview = data.get("ai_overview_text") or ""
    gemini_text = ""
    try:
        gemini_data = gemini_helper.ask_gemini(
            query=str(querry) + " GIVE all important links and news and things"
        )
        # ask_gemini fails "quietly" -- it returns {'status': 'error', ...}
        # instead of raising, so a plain str(gemini_data) would dump that
        # raw dict straight into what the user reads. Extract real text
        # only, or drop the supplement entirely.
        gemini_text = _extract_gemini_text(gemini_data) or ""
    except Exception:
        gemini_text = ""  # supplement is optional -- scraped data alone is enough

    combined_summary = "\n\n".join(p for p in (scraped_overview, gemini_text) if p)

    spoken = hina_direct.Hina_res(
        user_query=querry,
        summary=combined_summary,
        done=False,
    )
    final_text = spoken or combined_summary
    if final_text:
        data["ai_overview_text"] = final_text
        _speak_if_enabled(final_text)

    new_data = dict(data)
    new_data["ai_overview_text"] = ""
    hina_sdk.send_ui_json(
        data=new_data,
        state="Found on web",
        agent_name="web",
        icon="fa-solid fa-magnifying-glass",
        done=False,
    )

    hina_sdk.send_state(
        agent_name="Web",
        state="found",
        text=final_text,
        msg="Found best information for your query",
        voice=False,
        icon="fa-solid fa-magnifying-glass",
        done=True,
    )

    data["gemini_supplement"] = gemini_text
    return data


if __name__ == "__main__":
    mcp.run()