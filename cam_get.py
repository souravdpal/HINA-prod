from PIL import Image
from imagekitio import ImageKit
from dotenv import load_dotenv
import cv2
from pathlib import Path
import os 
import uuid
from groq import Groq

load_dotenv()

raw_file_Dir =Path("/run/media/sourav/souravMain/HINA-prod/scr")

raw_file_Dir.mkdir(parents=True,exist_ok=True)
file_name =f"{uuid.uuid4().hex}.jpg"
print(file_name)


imagekit = ImageKit(
    private_key=os.getenv("ig_private_key")
    #public_key=os.getenv("ig_public_key"),
    #url_endpoint=os.getenv("url_endpoint")
)

def take_image():
    cap=cv2.VideoCapture(0)
    if not cap.isOpened():
        print("cam not opening..")
    ret,frame=cap.read()
    cap.release()
    if not ret:
        raise Exception("failed to capture image")
    file_path=os.path.join(raw_file_Dir,file_name)
    cv2.imwrite(file_path,frame)
    print(f"Image saved to {file_path}")
    return file_path

def link_cam_image()->str:
    res = imagekit.files.upload(
        file=raw_file_Dir/take_image(),
        file_name=f"{file_name}",
        folder="/hina-ai",
    )
    os.remove(raw_file_Dir/file_name)
    return  res.url

def get_img_res():
    link =link_cam_image()

    client = Groq(api_key=os.environ.get("image_key"))
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
    stop=None,)
    res_o = completion.choices[0].message.content
    print(res_o)
    return(res_o)

def response_image(q):
    from hina_brain import model_res
    model_res(up=q,sec_data=f"Hina i am  your camera agent and becuse sourav wanted acces cam so i click pic you can see i found here summary: {str(get_img_res())}")

    
    
