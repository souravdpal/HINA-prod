import sys
import os
import logging
from summ import get_summary_old
from model_call import AICaller, Format, Mode
from sql_db import query
import re
logging.basicConfig(level=logging.INFO, format="[HINA] %(levelname)s: %(message)s")
logger = logging.getLogger("hina_brain")


def _emit(agent_name: str, state: str, msg: str, text: str = "", done: bool = False, **extra):
    """
    Local drop-in replacement for hina_sdk.send_state.
    Just logs to stdout/stderr instead of pushing to a websocket/UI layer.
    Swap this out later for whatever transport you want (print, logging, a queue, etc).
    """
    payload = {
        "agent_name": agent_name,
        "state": state,
        "msg": msg,
        "text": text,
        "done": done,
        **extra,
    }
    logger.info(payload)


def build_context(persona_path: str, summary: str, long_term_memory: str) -> str:

    persona = ""
    if os.path.exists(persona_path):
        with open(persona_path, "r") as f:
            persona = f.read()
    else:
        persona = "System fallback: Persona file missing."

    context_parts = [persona]

    # Inject state to mimic human recall
    if long_term_memory:
        context_parts.append(f"\n[LONG-TERM MEMORY]\n{long_term_memory}")
    if summary:
        context_parts.append(f"\n[RECENT CONVERSATION SUMMARY]\n{summary}")

    return "\n".join(context_parts)


def Hina_res(user_query: str, summary: str = "", long_term_memory: str = "", persona_path: str = "/home/sourav/hina_prod2/core/prompts/model_persona.txt") -> bool:
    """
    Core AI execution function. Can be imported as a module or called via sys args.
    No longer depends on hina_sdk -- status updates are just logged locally.
    """
    summary=get_summary_old(q=user_query)
    if not user_query.strip():
        _emit(
            agent_name="HINA",
            state="SYS_GUARD",
            msg="Empty query dropped",
            text="No input provided.",
            done=False
        )
        return ""

    ai = AICaller()
    full_prompt = build_context(persona_path, summary, long_term_memory)
    print(full_prompt)

    res = ai.call(
        prompt=full_prompt,
        mode=Mode.HUMAN,
        format=Format.TEXT,
        query=user_query
    )

    if res.ok:
        _emit(
            agent_name="HINA",
            state="HINA..",
            msg="hina responding",
            text=str(re.sub(r'<think>.*?</think>', '', res.text, flags=re.DOTALL)),
            icon="fa-solid fa-child-dress",
            color="Pink",
            voice=True,
            done=False
        )
        # Return the actual text, not just a bool -- callers (e.g. web_search_mcp.py)
        # need the real content, not a success flag.
        return str(str(re.sub(r'<think>.*?</think>', '', res.text, flags=re.DOTALL)))
    else:
        _emit(
            agent_name="HINA",
            state="HINA_ERR",
            msg="hina error",
            text=str(res.error),
            voice=True,
            done=False
        )
        return ""


