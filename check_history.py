import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv("backend/.env")

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

try:
    supabase: Client = create_client(url, key)
    res = supabase.table("historico_analises").select("*").order("created_at", desc=True).execute()
    for r in res.data:
        m = r.get("metrics") or {}
        p_start = m.get("period_start", "N/A")
        print(f"ID: {r['id']} | User: {r['user_id']} | Tipo: {r['periodo_tipo']} | Created: {r['created_at']} | Start: {p_start}")
except Exception as e:
    print(f"Erro ao consultar banco: {e}")
