import sqlite3
import os

# --- Configuration ---
# IMPORTANT: Replace 'database.db' with the actual name of your SQLite file
# if it is different in your app.py (e.g., 'voting.db').
DATABASE_NAME = 'votacao.db'

def create_initial_tables():
    """
    Connects to the database and creates the necessary tables for the voting system.
    If the tables already exist, they will not be re-created.
    """
    try:
        # Check if the database file already exists
        db_exists = os.path.exists(DATABASE_NAME)
        
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        
        print(f"Connected to database: {DATABASE_NAME}")

        # 1. Create the 'config' table (The table causing your current error)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        print("Table 'config' ensured.")

        # 2. Create the 'candidates' table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidatos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                image_url TEXT
            );
        """)
        print("Table 'candidates' ensured.")

        # 3. Create the 'votes' table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS votos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                voter_id TEXT NOT NULL UNIQUE,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (candidate_id) REFERENCES candidates(id)
            );
        """)
        print("Table 'votes' ensured.")

        # 4. Tabela de Eleitores
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS eleitores (
                cpf TEXT NOT NULL,
                turno TEXT NOT NULL,
                votou INTEGER NOT NULL,
                PRIMARY KEY (cpf, turno)
            )
        """)
        print("Table 'eleitores' ensured.")

        
        # Insert default configuration values if the database was just created
        if not db_exists:
            # Check if config table is empty before inserting initial data
            cursor.execute("SELECT COUNT(*) FROM config")
            if cursor.fetchone()[0] == 0:
                print("Inserting default configuration values...")
                initial_config = [
                    ('is_voting_open', '0'),  # 0 for false, 1 for true
                    ('admin_password_hash', 'REPLACE_ME_WITH_A_SECURE_HASH'),
                    ('election_title', 'Annual Board Election')
                ]
                cursor.executemany("INSERT INTO config (key, value) VALUES (?, ?)", initial_config)
                print("Default config inserted. ***REMEMBER TO HASH AND CHANGE THE DEFAULT ADMIN PASSWORD***")

        conn.commit()
        print("\nDatabase initialization complete! You can now run the Flask app.")

    except sqlite3.Error as e:
        print(f"An SQLite error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    create_initial_tables()
