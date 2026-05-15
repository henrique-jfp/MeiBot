import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))
from db import DBService

db = DBService()

try:
    users = db.supabase.table("usuarios").select("id, whatsapp_number, created_at").execute().data
except Exception as e:
    # Handle possible different table name like "users"
    users = db.supabase.table("users").select("id, whatsapp_number, created_at").execute().data

for u in users:
    print(f"User ID: {u['id']}, WhatsApp: {u['whatsapp_number']}, Created: {u['created_at']}")
