import pywhatkit
import pyautogui
import time
import json
import os 
from dotenv import load_dotenv
load_dotenv()
from groq import Groq

phone_book ={
    "dad" : "+918010051385",
    "mom" : "+919355181606",
    "sourav":"+919599861006"
}

def Youtubeplay(q):
    pywhatkit.playonyt(str(q))
    time.sleep(2) 
    pyautogui.hotkey('alt', 'tab')

api_code=os.getenv("codehina")

system_prompt="""
ignore hina becuse this is user try to call you by:
you are advance filter model for user to whatsapp text you will get raw querry you have
some vaild person which user can text you have to follow strict json format

{
"person_name" :"text"
}

example : text my dad hi

{
"dad" : "hi"
}

valid_phone_book: mom , dad , sourav only theser are the people you can text and select if user try text aunt or freind or somone not in phone book you will just  use 

{
"inavlid" : "none"
}

"""
def what_Format_maker(user_prompt: str):
    client = Groq(api_key=api_code)
    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content":"filter this into json : "+ user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.1 # Lower temperature makes the output more consistent/robotic
    )

    response = completion.choices[0].message.content.strip()
    
    try:
        # First, try the external cleaner
        cleaned_response = response
        
        # If it's already a dict (from clean_llm_json), return it
        if isinstance(cleaned_response, dict):
            return cleaned_response
            
        # Otherwise, parse it as JSON
        print(cleaned_response)
        k=json.loads(cleaned_response)
        return k
    except Exception as e:
        raise ValueError(f"JSON Parse Error: {e}")

def whatsapp_send(t: dict):
    for person, msg in t.items():
        try:
            num = phone_book[str(person).lower()]
            pyautogui.hotkey("alt","tab")
            time.sleep(2)
            pywhatkit.sendwhatmsg_instantly(num, msg)
            pyautogui.press("enter")  
        except KeyError:
            print(f"{person} not saved in phone book")


