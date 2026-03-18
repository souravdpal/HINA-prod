import json
import re 
import os
import mysql.connector
from dotenv import load_dotenv
import uuid
load_dotenv()


def get_id():
    return uuid.uuid4().hex

conn = mysql.connector.connect(
    user="sourav",
    password="souravdp",                  # Your actual password goes here
    unix_socket="/run/mysqld/mysqld.sock", # The path to your socket
    database="Hina",                      # Your database name
    auth_plugin='mysql_native_password'   # Leave this exactly as is
)
cursor = conn.cursor()
print("✅ Connected successfully via Unix socket.")
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
    