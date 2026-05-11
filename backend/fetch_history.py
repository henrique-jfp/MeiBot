import os
import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

def fetch_history():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    supabase = create_client(url, key)
    
    # Usuário principal (o que tem mais eventos)
    user_id = "f226e668-51a6-4ca8-980b-d863b176829e"
    user_res = supabase.table("users").select("*").eq("id", user_id).execute()
    
    if not user_res.data:
        print(f"Usuário {user_id} não encontrado.")
        return

    user = user_res.data[0]
    whatsapp = user.get("whatsapp_number")
    print(f"==========================================")
    print(f"RELATÓRIO COMPLETO: {user.get('nome') or whatsapp}")
    print(f"==========================================\n")

    # Buscar TODAS as operações
    ops_res = supabase.table("operacoes_dia").select("*").eq("user_id", user_id).order("data").execute()
    ops = ops_res.data

    # Buscar TODOS os eventos
    evs_res = supabase.table("eventos").select("*, apps(nome)").eq("user_id", user_id).order("timestamp").execute()
    evs = evs_res.data

    # Agrupar por data
    history = {}
    
    for op in ops:
        d = op["data"]
        if d not in history: history[d] = {"operacao": op, "eventos": []}
        else: history[d]["operacao"] = op

    for ev in evs:
        d = ev["timestamp"][:10]
        if d not in history: history[d] = {"operacao": None, "eventos": [ev]}
        else: history[d]["eventos"].append(ev)

    print("--- RESUMO DIÁRIO ---")
    for date_str, data in sorted(history.items()):
        print(f"📅 DATA: {date_str}")
        
        op = data["operacao"]
        if op:
            status = op.get("status", "N/A")
            h_inicio = op.get("hora_inicio", "").split('T')[-1][:5] if op.get("hora_inicio") else "--:--"
            h_fim = op.get("hora_fim", "").split('T')[-1][:5] if op.get("hora_fim") else "--:--"
            print(f"  🔹 Operação: {status.upper()} | Início: {h_inicio} | Fim: {h_fim}")
        
        if data["eventos"]:
            for ev in data["eventos"]:
                tipo = ev.get("tipo", "registro").upper()
                valor = ev.get("valor", 0)
                km = ev.get("km", 0)
                pacotes = ev.get("pacotes", 0)
                app = ev.get("apps", {}).get("nome", "N/A") if ev.get("apps") else "N/A"
                desc = ev.get("descricao", "")
                
                info = []
                if valor: info.append(f"R$ {valor:.2f}")
                if km: info.append(f"{km}km")
                if pacotes: info.append(f"{pacotes} pacotes")
                if app != "N/A": info.append(f"App: {app}")
                
                line = f"    - [{tipo}] " + " | ".join(info)
                if desc: line += f" ({desc})"
                print(line)
        else:
            print("  🔹 Sem eventos registrados.")
        print("-" * 40)

    # Buscar Mapeamento de Porteiros
    porteiros_res = supabase.table("mapeamento_porteiros").select("*").eq("user_id", user_id).order("rua").execute()
    if porteiros_res.data:
        print("\n--- MAPEAMENTO DE PORTEIROS ---")
        for p in porteiros_res.data:
            print(f"🏠 {p['rua']}, {p['numero']} - Porteiro: {p['nome_porteiro']} ({p.get('turno', 'N/A')})")
            if p.get('notas_predio'): print(f"   Notas: {p['notas_predio']}")

    # Buscar Análises Históricas
    analises_res = supabase.table("historico_analises").select("*").eq("user_id", user_id).order("created_at").execute()
    if analises_res.data:
        print("\n--- HISTÓRICO DE ANÁLISES ---")
        for a in analises_res.data:
            data_analise = a['created_at'][:10]
            tipo = a.get('periodo_tipo', 'N/A').upper()
            print(f"📊 {data_analise} | TIPO: {tipo}")
            print(f"   Insight: {a.get('insight', '')[:100]}...")

if __name__ == "__main__":
    fetch_history()
