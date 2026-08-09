import sqlite3, os
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agent.db")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Check messages schema
cur.execute("PRAGMA table_info(messages)")
print("=== messages schema ===")
for r in cur.fetchall():
    print(r)

# Check tool_call_logs schema
cur.execute("PRAGMA table_info(tool_call_logs)")
print("\n=== tool_call_logs schema ===")
for r in cur.fetchall():
    print(r)

# Latest tool calls
cur.execute("SELECT * FROM tool_call_logs ORDER BY rowid DESC LIMIT 5")
print("\n=== latest tool calls ===")
for r in cur.fetchall():
    print(r)

# Latest messages
cur.execute("SELECT * FROM messages ORDER BY rowid DESC LIMIT 5")
print("\n=== latest messages ===")
for r in cur.fetchall():
    print(r)

conn.close()