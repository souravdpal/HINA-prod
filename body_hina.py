from stt_module import listen
from music_system import play_music_logic
from raw_web import web_return
from prompt_code import code_engine
from groq import Groq
import os 
from filter_json import clean_llm_json
import json
from pipe_tts import speak_text
import difflib
from cam_get import response_image
from webagent import Youtubeplay , whatsapp_send , what_Format_maker

prompt_c="""
you are a guarding model bewteen user and system you have to return a strict json file to tell what model should appropriate for user querr

the models which you can use for user querry are :


web => to find real time information about world and news and things which will be up to date

chat => if user  querry is about hina normal casual not match with other user want to talk then use chat model for hina

code => if user want do any stuff realted to code , system , files  this will manage use code 

cam => if user want make system to acces real world camera and pics stuff

msg => if user want to text somone on whatsapp and want to message

yt=> if user want to play any kind of music and any type of vedio

format : 

{
"model" : "modelname"
}


example1 : hina play music lana del rey

{
"model" : "yt"
}

example2 : who is current pm of nepal

{
"model" : "web"
}

example3 : how are you hina 
{
"model" : "chat"
}

example4: how do i look?
{
"model" :"cam"
}
IMPORTANT :  user message somone and text somone just use msg model
NOTE : maintain strict json format  dont use any other tokens just json format
"""


def guard(q: str = "", 
          api_key: str = None, 
          model: str = "allam-2-7b", 
          max_tokens: int = 512) -> str:
    
    # 1. Setup API Key and Client
    api_key = api_key or os.getenv("crwaler")
    if not api_key:
        logging.error("API Key missing.")
        return "error"
    
    client = Groq(api_key=api_key)
    
    try:
        # 2. API Call with JSON Mode enabled
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt_c},
                {"role": "user", "content": q}
            ],
            response_format={"type": "json_object"}, # Forces JSON output
            temperature=0.2, # Lower temperature = more consistent JSON
            max_completion_tokens=max_tokens,
        )

        rt = completion.choices[0].message.content.strip()
        
        # 3. Defensive Parsing
        data = json.loads(rt)
        return str(data.get("model", "chat"))

    except json.JSONDecodeError:
        print(f"Failed to parse JSON from response: {rt}")
        return "chat" # Default fallback category
    except Exception as e:
        print(f"General Guard Error: {e}")
        return "error"




def wakey_wakey():
    trigger_word = "hina"

    while True:
        ck = str(listen()).strip().lower()
        print(ck + "is ck test")
        words = ck.split()

        # check if any word starts similar to "hina"
        trigger = any(difflib.get_close_matches(word, [trigger_word], cutoff=0.7) for word in words)

        if trigger:
            speak_text(text="How can I help you?")
            st_t = str(listen()).strip().lower()
            new_ck = guard(st_t)
            

            if new_ck == "yt":
                Youtubeplay(q=st_t)
            elif new_ck == "msg":
                whatsapp_send(what_Format_maker(user_prompt=str(st_t)))

            elif new_ck == "code":
                code_engine(q=str(st_t))

            elif new_ck == "web":
                web_return(q=str(st_t))
              
            elif new_ck == "cam":
                response_image(q=str(st_t))

            else:
                # lazy import only when needed
                from hina_brain import model_res
                model_res(up=str(st_t))
        else:
            continue

wakey_wakey()