import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))
from db import DBService

db = DBService()

correct_user = "5521985287511"
incorrect_user = "47188973469733"

user_c = db.get_user_by_whatsapp(correct_user)
user_i = db.get_user_by_whatsapp(incorrect_user)

if not user_c or not user_i:
    print("One or both users not found.")
    sys.exit()

id_c = user_c["id"]
id_i = user_i["id"]

tables = ["mapeamento_porteiros"]

for table in tables:
    try:
        res = db.supabase.table(table).update({"user_id": id_c}).eq("user_id", id_i).execute()
        print(f"Updated {len(res.data)} records in {table}")
    except Exception as e:
        print(f"Error updating {table}: {e}")

try:
    res = db.supabase.table("users").delete().eq("id", id_i).execute()
    print("Deleted incorrect user from users table.")
except Exception as e:
    print(f"Error deleting user: {e}")
