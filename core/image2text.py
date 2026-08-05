from PIL import Image
from imagekitio import ImageKit
from dotenv import load_dotenv
from pathlib import Path
import os 
import uuid
from groq import Groq


load_dotenv()

imagekit = ImageKit(
    private_key=os.getenv("ig_private")
    #public_key=os.getenv("ig_public_key"),
    #url_endpoint=os.getenv("url_endpoint")
)

id_ = uuid.uuid4()

def link_cam_image(filepath: str) -> str:
    # Open the file in binary read mode to satisfy ImageKit's payload requirements
    with open(filepath, "rb") as img_file:
        res = imagekit.files.upload(
            file=img_file,
            file_name=f"{id_}",
            folder="/hina-ai",
        )
    
    # The file is automatically closed when exiting the 'with' block, 
    # making it safe to delete the screenshot immediately after.
    os.remove(filepath)
    return res.url

def get_img_res(file_loc: str):
    link = link_cam_image(filepath=file_loc)

    client = Groq(api_key=os.environ.get("api1"))
    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "describe this image in pointers describe how it looks what it about in pointers summary"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"{link}"
                        }
                    }
                ]
            }
        ],
        temperature=1,
        max_completion_tokens=512,
        top_p=1,
        stream=False,
        stop=None,
    )
    res_o = completion.choices[0].message.content
    print(res_o)
    return res_o


if __name__ == "__main__":
    print(get_img_res(file_loc="/home/sourav/Pictures/Screenshots/Screenshot From 2026-07-04 23-05-44.png"))