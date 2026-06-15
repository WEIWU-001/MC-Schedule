import sqlite3
try:
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in c.fetchall()]
    print("Tables:", tables)
    
    if 'keywords' in tables:
        c.execute("SELECT * FROM keywords LIMIT 5")
        rows = c.fetchall()
        print("Keywords sample:", rows)
    else:
        print("ERROR: keywords table not found!")
        
    conn.close()
except Exception as e:
    print("Error:", e)
