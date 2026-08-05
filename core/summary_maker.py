from sql_db import query
import time

def prompt_maker():
    # The prompt explicitly forbids action-logging and focuses only on Saurav's personal data.
    return """
You are an advanced, silent Long-Term Memory Extraction Engine. Your sole purpose is to analyze the provided conversation log and extract high-value, enduring data points ABOUT THE USER (Saurav) to commit to long-term memory.

### STRICT NEGATIVE CONSTRAINTS (CRITICAL)
* DO NOT summarize the conversation structure.
* DO NOT output action logs (e.g., "Initiator: Sourav", "Request:", "Function:").
* DO NOT describe what the user or the system is doing.
* DO NOT output metadata. 
Focus EXCLUSIVELY on extracting enduring facts, preferences, emotions, and technical details.

### CORE EXTRACTION CRITERIA
Scan the input data meticulously for:
1. Critical Dates & Milestones: Birthdays, deadlines.
2. User Identity: Philosophies, habits, core values.
3. Nostalgia & Emotional Anchors: Fears, motivations, childhood memories.
4. Hard Facts: Projects, tech stacks, hardware, geographical locations.

### THE ZERO-TOKEN RULE
If the input contains only ephemeral data (casual banter, regular queries, coding errors, system checks) with no deep personal value, output EXACTLY an empty string (""). Do not say "No data found".

### OUTPUT FORMAT
If enduring facts exist, output them in a SINGLE LINE using dense brackets:
[Category: Fact] [Category: Fact]
"""

def extract_memory(clean_data: str) -> str:
    sys_prompt = prompt_maker()
    
    # We pass the data inside the user_query, enforcing the system constraints
    # instead of explicitly asking it to "summarize"
    user_prompt = f"Extract long-term memory facts from the following logs based STRICTLY on your system instructions:\n\n<input_data>\n{clean_data}\n</input_data>"
    
    response = ask_lite(
        system_prompt=sys_prompt,
        user_query=user_prompt
    )
    return response.strip()

def long_term_memo_worker():
    print("Fetching recent user messages...")
    
    # Fetch data. Ensure your SQL query returns readable strings.
    raw_data = query(
        "SELECT message FROM conversation_history WHERE role='user' ORDER BY created_at DESC LIMIT 5;"
    )
    
    if not raw_data:
        print("No data retrieved from DB.")
        return None
        
    # Clean the data carefully. DO NOT use .split().
    # Assuming query() returns a list of tuples like [('hello',), ('world',)]
    clean_messages = []
    for row in raw_data:
        if isinstance(row, tuple) or isinstance(row, list):
            clean_messages.append(str(row[0]).strip())
        else:
            clean_messages.append(str(row).strip())
            
    # Join messages with a clear separator so the model reads them as a continuous log
    joined_data = "\n---\n".join(clean_messages)
    
    print("Extracting memories...")
    new_memory = extract_memory(joined_data)
    
    if new_memory:
        print(f"\n+++ NEW MEMORY EXTRACTED +++\n{new_memory}\n")
        # TODO: Insert code here to save `new_memory` back to your vector DB or SQL table
    else:
        print("\n--- No enduring memory found in recent logs (Zero-Token triggered) ---\n")
        
    return new_memory

if __name__ == "__main__":
    sleep_time = 60 * 30  # 30 minutes
    
    print("Starting Long-Term Memory Daemon...")
    # Use a standard while loop instead of infinite recursion to prevent stack overflows
    while True:
        try:
            long_term_memo_worker()
        except Exception as e:
            print(f"Error during memory extraction: {e}")
            
        print(f"Sleeping for {sleep_time // 60} minutes...\n")
        time.sleep(sleep_time)