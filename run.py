from pathlib import Path

from engine.executor import execute_migrations
from engine.adapters.mysql import MySQLAdapter
from engine.versioning import load_migrations

def main():
    db_url = "mysql://safedb:safedbpass@127.0.0.1:3306/safedb_test"
    
    print("Loading migrations...")
    migrations_dir = Path("migrations")
    migrations = load_migrations(migrations_dir)
    
    print(f"Loaded {len(migrations)} migrations.")
    for m in migrations:
        print(f"  - {m.filename}")
        
    print("Connecting to MySQL...")
    adapter = MySQLAdapter(host="127.0.0.1", user="safedb", password="safedbpass", database="safedb_test")
    
    print("Executing migrations...")
    try:
        execute_migrations(migrations, adapter)
        print("Success!")
    except Exception as e:
        print(f"Migration Failed: {e}")

if __name__ == "__main__":
    main()
