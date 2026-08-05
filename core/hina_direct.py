import sys
import os
import logging
from summ import get_summary_old
from model_call import AICaller, Format, Mode
from hina_sdk import send_state  # forward to the real bridge, not just local logs

logging.basicConfig(level=logging.INFO, format="[HINA] %(levelname)s: %(message)s")
logger = logging.getLogger("hina_brain")


def _emit(agent_name: str, state: str, msg: str, text: str = "", done: bool = False, **extra):
    """
    Logs locally AND pushes to the websocket/UI bridge via hina_sdk.send_state.
    Previously this only logged locally, which meant HINA's final response
    (and the 'done' signal) never reached the frontend -- UI would hang on
    whatever the last real send_state() call was (e.g. "reading image...").
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

    # Only pass through kwargs that send_state actually accepts.
    send_state(
        agent_name=agent_name,
        state=state,
        msg=msg,
        text=text,
        done=done,
        icon=extra.get("icon", "fa-robot"),
        color=extra.get("color", "slate"),
        voice=extra.get("voice", False),
    )


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


def Hina_res(
    user_query: str,
    summary: str = "",
    long_term_memory: str = "",
    persona_path: str = "/home/sourav/hina_prod2/core/prompts/model_persona.txt",
    done: bool = True,  # caller controls whether this call is allowed to close the UI turn.
                        # Pass done=False when something else (e.g. a search-card push)
                        # still needs to go out on this same turn after Hina_res returns.
) -> str:
    """
    Core AI execution function. Can be imported as a module or called via sys args.
    """
    summary = get_summary_old(q=user_query)
    if not user_query.strip():
        _emit(
            agent_name="HINA",
            state="SYS_GUARD",
            msg="Empty query dropped",
            text="No input provided.",
            done=done,
        )
        return ""

    ai = AICaller()
    full_prompt = build_context(persona_path, summary, long_term_memory)

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
            text=res.text,
            icon="fa-solid fa-child-dress",
            color="Pink",
            voice=True,
            done=done,
        )
        return res.text

    else:
        _emit(
            agent_name="HINA",
            state="HINA_ERR",
            msg="hina error",
            text=str(res.error),
            voice=True,
            done=done,
        )
        return ""