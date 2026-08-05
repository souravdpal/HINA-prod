import os
import mariadb
from dotenv import load_dotenv
load_dotenv()

def query(sql: str, params: tuple = ()) -> list:
    conn = mariadb.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", f"{os.getenv("db_pass")}"),
        database=os.getenv("DB_NAME", "hina_prod2"),
        port=int(os.getenv("DB_PORT", 3306)),
    )

    # dictionary=True makes rows return as {'column': value} instead of raw tuples
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(sql, params)

        # If the statement returns data (SELECT, SHOW, etc.)
        if cursor.description:
            return cursor.fetchall()

        # If the statement modifies data (INSERT, UPDATE, DELETE)
        conn.commit()
        return [{"affected_rows": cursor.rowcount}]

    finally:
        cursor.close()
        conn.close()