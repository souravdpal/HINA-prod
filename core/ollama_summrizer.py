import ollama
from typing import Generator, Dict, List

class OllamaClient:
    def __init__(self, default_model: str = "qwen2.5:0.5b"):
        self.default_model = default_model

    def _build_messages(self, system_prompt: str, user_query: str) -> List[Dict[str, str]]:
        """Helper to structure the standard message payload."""
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]

    def stream_response(self, system_prompt: str, user_query: str, model: str = None) -> Generator[str, None, None]:
        """
        Streams the response token-by-token. 
        Yields each token as it arrives. Useful for real-time UI/Terminal display.
        """
        target_model = model or self.default_model
        messages = self._build_messages(system_prompt, user_query)
        
        try:
            stream = ollama.chat(model=target_model, messages=messages, stream=True)
            for chunk in stream:
                yield chunk['message']['content']
        except Exception as e:
            yield f"\n[Ollama Error]: {str(e)}"

    def get_full_response(self, system_prompt: str, user_query: str, model: str = None) -> str:
        """
        Blocks until the full response is generated and returns it as a string.
        """
        target_model = model or self.default_model
        messages = self._build_messages(system_prompt, user_query)
        
        try:
            response = ollama.chat(model=target_model, messages=messages, stream=False)
            return response['message']['content']
        except Exception as e:
            return f"[Ollama Error]: {str(e)}"