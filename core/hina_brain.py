import sys
import os
from hina_sdk import send_state
from model_call import AICaller, Format, Mode
from sql_db import query
from summ import get_summary_old
import re 
from ollama_call import call_ollama

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



def Hina_res(query: str, summary: str = "", long_term_memory: str = "", persona_path: str = "/home/sourav/hina_prod2/core/prompts/model_persona.txt") -> bool:
    """
    Core AI execution function. Can be imported as a module or called via sys args.
    """
    summary = str(get_summary_old(q="Give appropriate memories regarding user que : "+query))
    if not query.strip():
        send_state(
            agent_name="HINA",
            state="SYS_GUARD",
            msg="Empty query dropped",
            text="No input provided.",
            done=True
        )
        return False

    ai = AICaller()
    full_prompt = build_context(persona_path, summary, long_term_memory)
    print(full_prompt)

    res = ai.call(
        prompt=full_prompt,
        mode=Mode.HUMAN,
        format=Format.TEXT,
        query=query
    )
   

    if res.ok:
        send_state(
            agent_name="HINA",
            state="HINA..",
            msg="hina responding",
            text=str(re.sub(r'<think>.*?</think>', '', res.text, flags=re.DOTALL)),
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
    # Handles execution when spawned as a child process (e.g., via Node.js or bash)
    if len(sys.argv) > 1:
        input_query = sys.argv[1]
        
        # When spawned this way, summary and memory would typically be fetched 
        # from a DB, Redis, or state file. Passing empty strings as defaults here.
        Hina_res(query=input_query)
    else:
        # Failsafe if the process is triggered without arguments
        sys.exit(1)