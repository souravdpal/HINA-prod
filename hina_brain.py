from memo import short_term_memory , get_id
from dotenv import load_dotenv
load_dotenv()
import os 
from groq import Groq
api = os.getenv("api_hina")
from pipe_tts  import speak_text
from summarizer import model_res_sum

def model_res(
        model: str = "llama-3.1-8b-instant",
        prompt_cover: str = f"",
        up: str = "",
        api_key: str = api,
        sec_data:str=""
    ):

  
 #enter personal prompts as you want your model to behave like
  data_prompts = os.getenv("personal")
  kwarg=f"""Always use first perspective never use thrid person you are hina you talk like human dont talk what you will but just say like human speak

{data_prompts.replace("\\n", "\n")}

HINA OLD MEMORIES ABOUT YOUR CONVERSATION WITH SOURAV dont talk about just take them as refrence and make response : {model_res_sum(special="Focus on memories summary on the topic related to"+up)} 

"""

  client = Groq(api_key=api_key)

  user_prompt = f"Sourav says : {str(up)}"

  print("loading model...")
  if len(sec_data)>20:
        prompt_cover=str(kwarg)+f"NOTE:you ran command so dont forgot to tell user abaout in words what you did its important:{sec_data}"
  else:
        prompt_cover=kwarg
  completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": str(prompt_cover)},
            {"role": "user", "content": user_prompt}
        ],
        temperature=1,
        max_completion_tokens=2096
    )

  k_res = completion.choices[0].message.content
    
  short_term_memory(user=up, ai=k_res)

  speak_text(text=str(k_res).replace("*",""))

  return k_res

if __name__ =="__main__":
   ask =  input("send msg")
   
   model_res(up=ask)

