import hashlib
import uuid
from typing import Optional, Set
from sql_db import query

"""
Database Schema Reference:
+--------------+-------------+------+-----+---------------------+----------------+
| Field        | Type        | Null | Key | Default             | Extra          |
+--------------+-------------+------+-----+---------------------+----------------+
| id           | bigint(20)  | NO   | PRI | NULL                | auto_increment |
| session_id   | varchar(64) | NO   | MUL | NULL                |                |
| category     | varchar(50) | NO   | MUL | NULL                |                |
| fact         | text        | NO   |     | NULL                |                |
| fact_hash    | char(64)    | NO   |     | NULL                |                |
| created_at   | timestamp   | YES  |     | current_timestamp() |                |
| last_seen_at | timestamp   | YES  |     | current_timestamp() |                |
+--------------+-------------+------+-----+---------------------+----------------+
"""

# Global configuration for allowed memory categories
VALID_CATEGORIES: Set[str] = {
    "music",
    "gernal",
    "dates",
    "space",
    "personal",
    "fun",
    "secret"
}

def is_valid_category(category: str) -> bool:
    """Checks if the given category is permitted in the long term memory."""
    return category.strip().lower() in VALID_CATEGORIES

def long_term_data(direct: bool = False, q: str = "", cat3: str = "") -> None:
    """
    Validates and stores/updates facts in the long-term memory database.
    """
    # 1. Resolve memory and category based on execution mode
    if direct:
        memory = q.strip()
        cat = cat3.strip().lower()
    else:
        memory = input("Enter a memory you want to store in HINA DB: ").strip()
        print(f"Allowed categories: {', '.join(sorted(VALID_CATEGORIES))}")
        cat = input("Enter category of the memory: ").strip().lower()

    # 2. Validation Layer
    if not memory:
        print("[-] Error: Memory string cannot be empty.")
        return

    if not is_valid_category(cat):
        print(f"[-] Validation Error: '{cat}' is not a recognized category.")
        print(f"[*] Expected one of: {list(VALID_CATEGORIES)}")
        return

    # 3. Generate Identifiers
    session_id = str(uuid.uuid4())
    fact_hash = hashlib.sha256(memory.encode('utf-8')).hexdigest()

    # 4. Formulate SQL Upsert Query
    q_name = """
        INSERT INTO long_term_memory (session_id, category, fact, fact_hash) 
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE last_seen_at = CURRENT_TIMESTAMP;
    """
    
    data = (session_id, cat, memory, fact_hash)

    # 5. DB Execution
    try:
        query(q_name, data)
        print(f"[+] Successfully persistent: Stored under category '{cat}'.")
    except Exception as e:
        print(f"[-] Database operation failed: {e}")

if __name__ == "__main__":
    # Test validation failure or success locally
    long_term_data(direct=False)