import os
import json
import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

def diagnostic():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    print(f"URL: {url[:20]}...")
    
    supabase = create_client(url, key)
    
    # Busca o usuário pelo seu número
    whatsapp = "5521985287511"
    user_res = supabase.table("users").select("*").eq("whatsapp_number", whatsapp).execute()
    
    if not user_res.data:
        print(f"ERRO: Usuário {whatsapp} não encontrado no banco!")
        return

    user = user_res.data[0]
    user_id = user["id"]
    print(f"Usuário encontrado: {user['nome']} (ID: {user_id})")

    # Verifica total de eventos SEM FILTRO DE DATA
    total_ev = supabase.table("eventos").select("count", count="exact").eq("user_id", user_id).execute()
    print(f"Total de eventos no histórico: {total_ev.count}")

    # Verifica eventos dos últimos 7 dias
    seven_days_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    recent_ev = supabase.table("eventos").select("*").eq("user_id", user_id).gte("timestamp", seven_days_ago).execute()
    print(f"Eventos nos últimos 7 dias: {len(recent_ev.data)}")
    
    if len(recent_ev.data) > 0:
        print("Amostra do primeiro evento recente:")
        print(json.dumps(recent_ev.data[0], indent=2))

    # Verifica operações
    ops = supabase.table("operacoes_dia").select("*").eq("user_id", user_id).execute()
    print(f"Total de operações diárias: {len(ops.data)}")

if __name__ == "__main__":
    diagnostic()
