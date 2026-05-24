import sys
import os
import asyncio
import datetime

# Adiciona o diretorio atual ao path para importar app.*
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db import DBService
from app.logic import LogicService
from app.ai_service import AIService

async def main():
    whatsapp = "5521985287511"
    db = DBService()
    ai = AIService()

    user = db.get_user_by_whatsapp(whatsapp)
    if not user or not user.get("id"):
        print(f"Usuario {whatsapp} nao encontrado.")
        return

    user_id = user["id"]
    
    # Período da primeira semana do mês de Maio de 2026
    start_date = datetime.date(2026, 5, 4)
    end_date = datetime.date(2026, 5, 10)
    label = f"{start_date.strftime('%d/%m')} a {end_date.strftime('%d/%m')}"

    start_iso = start_date.isoformat()
    end_iso = (end_date + datetime.timedelta(days=1)).isoformat()

    print(f"Buscando eventos de {start_iso} a {end_iso}...")

    events_res = db.supabase.table("eventos").select("*, apps(*)")\
        .eq("user_id", user_id)\
        .gte("timestamp", start_iso)\
        .lt("timestamp", end_iso)\
        .execute()
    events = events_res.data or []

    ops_res = db.supabase.table("operacoes_dia").select("*")\
        .eq("user_id", user_id)\
        .gte("data", start_date.isoformat())\
        .lte("data", end_date.isoformat())\
        .execute()
    ops = ops_res.data or []

    if not events:
        print(f"Sem eventos neste periodo. Abortando.")
        return

    metrics = LogicService.calculate_metrics_grouped(events, ops)
    metrics["period_label"] = label
    metrics["period_start"] = start_date.isoformat()
    metrics["period_end"] = end_date.isoformat()

    print("Gerando insight com IA...")
    insight = await ai.generate_analyst_insight(metrics["consolidado"], None, "Semana 1", metrics.get("apps"))

    # Verifica se ja existe uma analise para esta semana (por seguranca)
    history = db.get_analysis_history(user_id, limit=50)
    existing_id = None
    for h in history:
        if h.get("periodo_tipo") == "semanal":
            m = h.get("metrics") or {}
            if m.get("period_start") == start_date.isoformat():
                existing_id = h["id"]
                break

    data_to_save = {
        "metrics": metrics,
        "insight": insight
    }

    if existing_id:
        print(f"Atualizando analise existente ID: {existing_id}...")
        res = db.supabase.table("historico_analises").update(data_to_save).eq("id", existing_id).execute()
    else:
        print("Criando nova analise na tabela historico_analises...")
        data_to_save["user_id"] = user_id
        data_to_save["periodo_tipo"] = "semanal"
        # Garante que a data de criação seja retroativa para manter a ordem cronológica visual
        data_to_save["created_at"] = f"{end_date.isoformat()}T23:59:59Z"
        res = db.supabase.table("historico_analises").insert(data_to_save).execute()

    if res.data:
        print("Sucesso! Analise da Semana 1 (04/05 a 10/05) gerada com sucesso.")
    else:
        print("Erro ao salvar analise.")

if __name__ == "__main__":
    asyncio.run(main())
