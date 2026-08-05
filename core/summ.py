import re
from sql_db import query
from model_call import AICaller, Format, Mode
from ollama_summrizer import OllamaClient

ai = AICaller()

def get_old_chat_context(limit: int = 5) -> str:
    """Pulls the last N agent messages and last N user messages, merges, sorts chronologically."""
    sql = """
        (SELECT message, role, created_at
         FROM conversation_history
         WHERE role = 'agent'
         ORDER BY created_at DESC
         LIMIT %s)
        UNION ALL
        (SELECT message, role, created_at
         FROM conversation_history
         WHERE role = 'user'
         ORDER BY created_at DESC
         LIMIT %s)
        ORDER BY created_at ASC
    """
    rows = query(sql, (limit, limit))
    return "\n".join(f"{r['role'].upper()}: {r['message']}" for r in rows)

def get_summary_old(q: str):
    # Pass the context and the current query clearly
    chat_history = get_old_chat_context()
    
    # Use a Persona-based prompt to force the model to synthesize context, not summarize structure
    full_prompt = f"""
You are Hina's internal memory processing unit. Your task is to analyze the following recent conversation history and synthesize a concise, rich contextual brief that helps Hina understand the current flow of the interaction.

DO NOT use bullet points like 'Initiator' or 'Request'. 
DO synthesize the core topics, user intent, and emotional context into a natural, brief paragraph.

RECENT HISTORY:
{chat_history}

CURRENT QUERY:
{q}

SYNTHESIS:
"""
    
    res = ai.call(
        prompt=full_prompt,
        mode=Mode.SUMMARIZER,
        format=Format.TEXT,
        query=q
    )
    
    # Clean the output
    raw_output = res.text
    cleaned_output = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL).strip()
    
    print(f"--- Memory Synthesis ---\n{raw_output}")
    return raw_output




