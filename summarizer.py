from groq import Groq
import mysql.connector
from dotenv import load_dotenv
import os
load_dotenv()

char ="""
summarize in just small and dont show your words just summrzie
you are advance summarizing model who is here to summarize given data 
you are summazrizing tool for hina you are its agentic agent who have to summarzie all old chats of hina and user
you have summazrize like you are hina yourself like memories 
this  talk is between hina (who you are summaries in perspective of ) and boy sourav
"""


conn = mysql.connector.connect(
    user="sourav",
    password="souravdp",                  # Your actual password goes here
    unix_socket="/run/mysqld/mysqld.sock", # The path to your socket
    database="Hina",                      # Your database name
    auth_plugin='mysql_native_password'   # Leave this exactly as is
)
cursor = conn.cursor()
print("✅ Connected successfully via Unix socket.")


def get_data():
    data_res =[]
    cursor.execute('select ai,user from short_memo order by old desc limit 10')
    result=cursor.fetchall()
    k=0
    for i in result:
        data_res.append(i)
    return data_res


apisum=os.getenv("hinasum")


def model_res_sum(
        model: str = "llama-3.1-8b-instant",
        api_key: str =apisum,
        char: str = str(char),
        data: str = str(get_data()),
        special:str =""
    ):

    client = Groq(api_key=api_key)

    user_prompt = f"""you have to summarize summarize in just small and dont show your words just summarize
you are advance summarizing model who is here to summarize given data :=>{data}
also specially focus on ====>{special}

"""

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": str(char)},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        max_completion_tokens=512
    )

    k_res = completion.choices[0].message.content

    return k_res

print(model_res_sum())