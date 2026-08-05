import sys
import os
from hina_sdk import send_state
from model_call import AICaller, Format, Mode
from summ import get_summary_old 
from hin_voice_engine import run_hina_voice
from voice_stat import is_voice_on
from mcp_router import route_and_call



def build_context(persona_path: str, summary: str, long_term_memory: str) -> str:

    persona = ""
    if os.path.exists(persona_path):
        with open(persona_path, "r") as f:
            persona = f.read()
    else:
        persona = "System fallback: Persona file missing."

    context_parts = [persona]

    if long_term_memory:
        context_parts.append(f"\n[LONG-TERM MEMORY]\n{long_term_memory}")
    if summary:
        context_parts.append(f"\n[RECENT CONVERSATION SUMMARY]\n{summary}")

    return "\n".join(context_parts)



def Hina_res(query: str, summary: str = "", long_term_memory: str = "", persona_path: str = "/home/sourav/hina_prod2/core/prompts/model_persona.txt") -> bool:
    """
    Core AI execution function. Can be imported as a module or called via sys args.
    """
    if not query.strip():
        send_state(
            agent_name="HINA",
            state="SYS_GUARD",
            msg="Empty query dropped",
            text="No input provided.",
            done=True
        )
        return False

    # ONE call decides tool-need + server + tool + args, and dispatches
    # if it found a match. None means "no tool needed, handle as normal chat".
    mcp_result = route_and_call(query)
    print(mcp_result)
    if mcp_result is not None:
        send_state(
            agent_name="HINA",
            state="HINA..",
            msg="tool result ready",
            text=str(mcp_result),
            icon="fa-solid fa-child-dress",
            color="Pink",
            voice=True,
            done=True
        )
        return True

    summary = str(get_summary_old(q=query))

    ai = AICaller()
    full_prompt = build_context(persona_path, summary, long_term_memory)

    res = ai.call(
        prompt=full_prompt,
        mode=Mode.HUMAN,
        format=Format.TEXT,
        query=query
    )


    if res.ok:
        send_state(
            agent_name="HINA speaking...",
            state="HINA..",
            msg="hina responding..",
            icon="fa-solid fa-child-dress",
            color="Pink",
            voice=True,
            done=False
        )
        if(is_voice_on()==True):
            run_hina_voice(text=res.text)
        send_state(
            agent_name="HINA",
            state="HINA..",
            msg="hina responding",
            text=res.text,
            icon="fa-solid fa-child-dress",
            color="Pink",
            voice=True,
            done=True
        )
        return True
    else:
        send_state(
            agent_name="HINA",
            state="HINA_ERR",
            msg="hina error",
            text=str(res.error),
            voice=True,
            done=True
        )
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_query = sys.argv[1]
        Hina_res(query=input_query)
    else:
        sys.exit(1)