import json
import re 
import os
import pymysql
from dotenv import load_dotenv
import uuid
load_dotenv()


def get_id():
    return uuid.uuid4().hex
conn = pymysql.connect(
    user=str(os.getenv("user")),
    password=os.getenv("pass"),            # Your actual password goes here
    unix_socket="/run/mysqld/mysqld.sock", # The path to your socket
    database="hina"                       # Your database name
)
cursor = conn.cursor()
def short_term_memory(user , ai , sm="offline",read:bool=False):
    if(read==False):
       cursor.execute(
        "insert into short_memo(id,user,ai,old) values(%s,%s,%s,CURRENT_TIMESTAMP)",
        (get_id(),ai,user))
       conn.commit()
    



def long_term_memory():
    print("long time memory conditions")


def perma_memo():
    print("always memory never forgets")


if __name__ == "__main__":
    short_term_memory(user="hey i am sourav",ai="i am hina btw")
    