from sql_db import query
from open_router import ask_lite
import time


def prompt_maker(data:str):
  prompt = f"""
You are an advanced, silent Long-Term Memory Extraction Engine. Your sole purpose is to analyze the provided conversation log or dataset and extract high-value, enduring data points about the user to commit to long-term memory storage. 

### CORE EXTRACTION CRITERIA
Scan the input data meticulously for the following high-value vectors:
1. **Critical Dates & Milestones:** Birthdays, significant deadlines, anniversaries, or upcoming pivotal events.
2. **User Identity & Specifics:** Deep personal philosophies, unique cognitive habits, rigid preferences, and core values.
3. **Nostalgia & Emotional Anchors:** Childhood memories, formative past experiences, core motivations, or recurring emotional drivers.
4. **Hard Facts:** Projects built, technical stacks mastered, hardware limitations, geographical changes, or definitive structural details.
5. **Secrets & Vulnerabilities:** Deep fears, hidden ambitions, unspoken psychological dynamics, or private truths shared in confidence.

### STRICTION EXECUTION RULES (GUARDRAILS)
* **The Zero-Token Rule:** If the input contains only ephemeral data (e.g., standard code debugging, casual banter, greetings, routine QA) with no enduring personal value, you must output **ABSOLUTELY NOTHING**. Do not output spaces, markdown, "No data found," "N/A," or any introductory text. Return a completely empty string (`""`).
* **The One-Line Consolidation Rule:** If, and only if, actionable data matching the criteria is found, you must synthesize all extracted points into **EXACTLY ONE SINGLE LINE** of text. 
* **No Prose:** Do not include conversational filler, pleasantries, introductory phrases ("Here is the summary:"), or concluding remarks. Jump straight into the compressed data string.

### OUTPUT FORMAT
When data is present, format the single line using dense, structured brackets for clean programmatic parsing:
`[Category: Data point] [Category: Data point] [Category: Data point]`

### INPUT DATA TO ANALYZE
<input_data>
{data}
</input_data>
"""
  return prompt


sleep_time = 60*30


def long_term_memo():
    data = query(
        """
select message from conversation_history where role='user' order by created_at desc limit 5;
"""
    )
   
    end_data = str(data).strip().split()
    pp= prompt_maker(end_data)
    k=ask_lite(
       system_prompt=pp,
       user_query="summarize data properly for long term memory"
    )
    long_term_memo()




if __name__ =="__main__":
  k=long_term_memo()
  print(k)