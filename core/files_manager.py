import sys
import json
from image2text import get_img_res
from hina_sdk import send_state
from hina_direct import Hina_res
from model_call import AICaller, Format, Mode
import subprocess as sub
import os
# args: [1] = json array of attachments, [2] = session_id, [3] = prompt/query
attachments_json = sys.argv[1] if len(sys.argv) > 1 else "[]"
session_id = sys.argv[2] if len(sys.argv) > 2 else ""
prompt = sys.argv[3] if len(sys.argv) > 3 else ""

attachments = json.loads(attachments_json)

type_ = ""
path = ""
url = ""
og_name = ""

for a in attachments:
    type_ = a.get("type")
    path = a.get("path")
    url = a.get("url")
    og_name = a.get("original_name")
    print("---")
    print(prompt)
    print("type:", a.get("type"))
    print("path:", a.get("path"))
    print("url:", a.get("url"))
    print("original_name:", a.get("original_name"))


def get_short_data():
    if type_ == "image":
        send_state(
            agent_name="Image Model..",
            state="Reading image...",
            color="think",
            msg="reasoning..",
            icon="fa-solid fa-images",
            done=False
        )
        k = get_img_res(file_loc=path)
        print("[image2text] description:", k)  # was silently discarded before
        send_state(
            agent_name="Image Model..",
            state="Reading image...",
            color="think",
            icon="fa-solid fa-images",
            msg="working..",
            done=False
        )
        # Dropped the "IMAGE MCP SERVER INJECTION" label -- that phrase was
        # getting misread by the downstream model as a security-exploit
        # topic instead of an internal tag, causing hallucinated responses.
        j = Hina_res(
            user_query=prompt + f"\n\n[Image description from vision model properly refer to the image]: {k}",
            done=True
        )
        # Hina_res now sends its own done=True send_state internally, so the
        # UI stream properly closes here instead of hanging on "reading image..."
        return k
    else:
        send_state(
            agent_name="Thinking Model..",
            state="Reading file...",
            color="think",
            icon="fa-solid fa-face-thinking",
            msg="working..",
            done=False
        )
        data = sub.run(["cat", path], capture_output=True, text=True).stdout
        prompto = """
you are advance model for complex task give proper response for the data
"""
        j = Hina_res(
            user_query=f"sourav says : {prompt} and File agent injection into hina for the file sourav sent you : \n {data}",
            summary=prompto,
            done=True
        )
        # Hina_res now sends its own done=True send_state internally.
        return j


get_short_data()