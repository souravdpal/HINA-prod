import os
import sys
import subprocess as sub
from sql_db import query
from model_call import AICaller , Format , Mode
import re 
from ollama_call import call_ollama

ai = AICaller()
def get_short_term():
    short_memo= query(
        """ select  summary   from short_term_memory;
        """
    )
    #print(short_memo)
    return short_memo[0].get("summary",None)


def old_chat():
    short_old_c= query(
        """  SELECT message  FROM  conversation_history  ORDER BY created_at DESC  LIMIT 6;

        """
    )
    return short_old_c[0].get("message",None)



def get_summary_old(q:str):
    q="Sourav who talks to hina says  : " + q
    full_prompt=f"""
summarzie the data from thrid perpective  The history you get is of HINA You have to  Make summary properly no waste of tokens pointer short and rich with information :
\n \n {old_chat()}
"""
    res = ai.call(
        prompt=full_prompt,
        mode=Mode.SUMMARIZER,
        format=Format.TEXT,
        query=q
    )
    """res = call_ollama(
        model="qwen3.5:0.8b",
        prompt=full_prompt,
        query=q,
        memory="",
    )"""
    gt_dat = res.text
    print(gt_dat)
    return re.sub(r'<think>.*?</think>', '', gt_dat, flags=re.DOTALL)



if __name__=="__main__":
    print(get_short_term())