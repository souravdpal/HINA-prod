from groq import Groq
import os
from dotenv import load_dotenv
import json
import subprocess as sub
import time
from filter_json import clean_llm_json

load_dotenv()

# Improved Prompt: Explicitly shows the model that values MUST be wrapped in "quotes"
system_prompt="""
You are a Linux command generator. You output ONLY valid JSON.
The JSON must follow this exact structure:

{
  "go": 2,
  "step1": "command_here",
  "step2": "command_here"
}

Rules:
1. "go" must be an integer.
2. Every step must be a string inside double quotes.
3. If a command contains double quotes, escape them (e.g., \"text\").
4. No conversational text. No markdown blocks. Just the JSON object.
"""

api_code = os.getenv("codehina")
supass = f"{os.getenv('supass')}"

def code_maker(user_prompt: str):
    client = Groq(api_key=api_code)
    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.1 # Lower temperature makes the output more consistent/robotic
    )

    response = completion.choices[0].message.content.strip()
    
    try:
        # First, try the external cleaner
        cleaned_response = clean_llm_json(response)
        
        # If it's already a dict (from clean_llm_json), return it
        if isinstance(cleaned_response, dict):
            return cleaned_response
            
        # Otherwise, parse it as JSON
        return json.loads(cleaned_response)
    except Exception as e:
        raise ValueError(f"JSON Parse Error: {e}")

def code_engine(q):
    attempts = 0
    max_retries = 5
    json_file = None

    while attempts < max_retries:
        try:
            print(f"Attempting to generate code (Attempt {attempts + 1})...")
            json_file = code_maker(q)
            # Basic validation that 'go' exists
            if "go" in json_file:
                break
        except Exception as e:
            print(f"Error: {e}. Retrying in 1s...")
            attempts += 1
            time.sleep(1) 
    
    if not json_file:
        print("Failed to get valid JSON. Try rephrasing your request.")
        return

    idx = int(json_file.get("go", 0))
    pass_wd = str(supass).encode() 
    
    for i in range(1, idx + 1):
        name_st = f"step{i}"
        command = json_file.get(name_st)
        if not command: continue
            
        print(f"\n[Step {i}] Executing: {command}")
        
        try:
            # shell=True allows things like '>', '|', and '&&'
            proc = sub.Popen(
                command, 
                shell=True, 
                stdin=sub.PIPE, 
                stdout=sub.PIPE, 
                stderr=sub.PIPE
            )
            
            stdout, stderr = proc.communicate(input=pass_wd)
            from hina_brain import model_res
            if stdout:
                print(f"Output:\n{stdout.decode()}")
                model_res(up=q,sec_data=stdout.decode())
            if stderr:
                # Note: some commands put status info in stderr, not just errors
                print(f"Log/Error:\n{stderr.decode()}")
                model_res(up=q,sec_data=stderr.decode())
        except Exception as e:
            print(f"Runtime Error: {e}")

if __name__ == "__main__":
    code_engine(q="check my pc sensors and save in txt file and open")
