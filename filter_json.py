import json
import re

def clean_llm_json(text: str):
    """
    Attempts to repair common LLM JSON mistakes.
    Returns a valid Python dict or raises an error.
    """

    # 1. Remove markdown code fences if present
    text = re.sub(r"```.*?\n", "", text)
    text = text.replace("```", "")

    # 2. Extract the first JSON-looking block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found")

    text = match.group(0)

    # 3. Fix escaped quotes around keys
    text = text.replace('\\"', '"')

    # 4. Ensure step commands are quoted
    text = re.sub(r'(:\s*)([a-zA-Z].*?)(,|\n|\})', r'\1"\2"\3', text)

    # 5. Remove trailing commas
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    # 6. Try parsing
    return json.loads(text)

