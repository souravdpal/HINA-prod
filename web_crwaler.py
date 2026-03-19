# web_summary.py

from groq import Groq
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

def summarize_web_data(web_data: str, 
                       user_query: str,
                       api_key: str = None,
                       model: str = "allam-2-7b",
                       max_tokens: int = 512) -> str:
    """
    Summarizes web data concisely to match a user query using allam-2-7b.

    Parameters:
        web_data (str): Raw data from web or sources.
        user_query (str): The user's query that the summary should match.
        api_key (str): Groq API key (loaded from .env if None).
        model (str): Groq model to use for summarization.
        max_tokens (int): Maximum number of tokens for the summary.

    Returns:
        str: Concise, pointer-style summary.
    """

    if api_key is None:
        api_key = os.getenv("crwaler")  # ensure your API key is in .env

    client = Groq(api_key=api_key)

    # Prepare a clean system prompt
    system_prompt = (
        "You are a concise and advanced summarizer. "
        "Return the summary in short pointer/bullet style, matching the user's query. "
        "Do not add extra commentary."
    )

    # Limit web_data length to avoid 413 errors
    web_data = web_data[:4000]  # truncate if very large

    user_prompt = f"""
User query: {user_query}

Web data:
{web_data}

Summarize above data concisely in bullet points relevant to the query.
"""

    # Create completion using chat model
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,         # less randomness for factual summary
        max_completion_tokens=max_tokens,
        top_p=1,
        stream=False
    )

    return completion.choices[0].message.content


if __name__ == "__main__":
    example_data = """
Iran and US tensions rose in March 2026 due to diplomatic conflicts.
Economic sanctions were discussed.
Several political leaders made public statements.
International organizations urged dialogue.
"""
    query = "What happened between Iran and US in March 2026?"

    summary = summarize_web_data(example_data, query)
    print(summary)