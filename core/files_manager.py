import sys
import json
from ollama_call import call_ollama
from  image2text import get_img_res
from  hina_sdk import send_state
from hina_brain import Hina_res
from open_router import get_reliable_response
import subprocess as sub
import os
# args: [1] = json array of attachments, [2] = session_id, [3] = prompt/query
attachments_json = sys.argv[1] if len(sys.argv) > 1 else "[]"
session_id = sys.argv[2] if len(sys.argv) > 2 else ""
prompt = sys.argv[3] if len(sys.argv) > 3 else ""

attachments = json.loads(attachments_json)

type_ =  ""
path=""
url=""
og_name=""

for a in attachments:
    type_=a.get("type")
    path=a.get("path")
    url=a.get("url")
    og_name=a.get("original_name")
    print("---")
    print(prompt)
    print("type:", a.get("type"))
    print("path:", a.get("path"))
    print("url:", a.get("url"))
    print("original_name:", a.get("original_name"))

def get_short_data():
    if(type_=="image"):
        send_state(
            agent_name="Image Model..",
            state="Reading image...",
            color="think",
            msg="reasoning..",
            icon="fa-solid fa-images",
            done=False
        )
        k=get_img_res(file_loc=path)
        send_state(
            agent_name="Image Model..",
            state="Reading image...",
            color="think",
            #text=str(k),
            icon="fa-solid fa-images",
            msg="working..",
            done=False
        )
        print(k)
        Hina_res(
            query=prompt+ f"IMAGE MCP SERVER INJECTION : {k}",
            #summary=f"\n\nABOUT THE IMAGE by IMage Model : {k}"
        )
        return k
    else:
       send_state(
            agent_name="Thinking Model..",
            state="Reading file...",
            color="think",
            #text=str(k),
            icon="fa-solid fa-face-thinking",
            msg="working..",
            done=False
        )       
       data = sub.run(["cat",path],capture_output=True,text=True).stdout
       prompto =f"""
you are advance model for complex task give proper response for the data 

the data : {data}
"""
       j=Hina_res(
           query=prompt,
           summary=prompto  
       )
    send_state(
            agent_name="Thinking Model..",
            state="Making code...   ",
            color="think",
            text=str(j),
            icon="fa-solid fa-face-thinking",
            msg="Found..",
            done=True
        )  
    os.remove(path=path)

get_short_data()