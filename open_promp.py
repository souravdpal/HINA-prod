from groq import Groq
from dotenv import load_dotenv
import os
load_dotenv()


def raw_maker(data: str, 
                       contex_prompt: str,
                       api_key: str = None,
                       model: str = "allam-2-7b",
                       max_tokens: int = 512) -> str:
   

    if api_key is None:
        api_key = os.getenv("crwaler")  # ensure your API key is in .env

    client = Groq(api_key=api_key)

    # Prepare a clean system prompt
    system_prompt = (
        f"{contex_prompt}"
    )
 

    user_prompt = f"""
{contex_prompt}
    
    """

    # Create completion using chat model
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content":user_prompt},
            {"role": "user", "content": data}
        ],
        temperature=0.7,         # less randomness for factual summary
        max_completion_tokens=max_tokens,
        top_p=1,
        stream=False
    )

    return completion.choices[0].message.content



