import sys
import os
import asyncio
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db import DBService
from app.logic import LogicService
from app.ai_service import AIService

async def main():
    target_user_whatsapp = "5521985287511" 
    db_service = DBService()
    user = db_service.get_user_by_whatsapp(target_user_whatsapp)
    if not user or not user.get('id'):
        print(f"Usuário com número {target_user_whatsapp} não encontrado.")
        return

    user_id = user['id']
    ai = AIService()

    print(f"Buscando histórico para o user_id: {user_id}")
    history = db_service.get_analysis_history(user_id, limit=100)
    
    if not history:
        print("Nenhum histórico encontrado.")
        return

    oldest_weekly = None
    for analysis in reversed(history):
        if analysis['periodo_tipo'] == 'semanal':
            oldest_weekly = analysis
            break
            
    if not oldest_weekly:
        print("Nenhuma análise semanal encontrada para reprocessar.")
        return

    analysis_id = oldest_weekly['id']
    created_at_str = oldest_weekly['created_at']
    print(f"Análise semanal mais antiga encontrada: ID {analysis_id}, Criada em {created_at_str}")

    created_at_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
    end_date = created_at_dt.date()
    start_date = end_date - timedelta(days=5)
    period_label = f"{start_date.strftime('%d/%m')} a {end_date.strftime('%d/%m')}"
    print(f"Período a ser reprocessado: {period_label}")

    start_str, end_str = start_date.isoformat(), (end_date + timedelta(days=1)).isoformat()
    print(f"Buscando eventos de {start_str} a {end_str}")
    
    events_res = db_service.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", start_str).lt("timestamp", end_str).execute()
    events = events_res.data or []
    
    ops_res = db_service.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).gte("data", start_date.isoformat()).lte("data", end_date.isoformat()).execute()
    ops = ops_res.data or []

    if not events:
        print("Nenhum evento encontrado para o período. Abortando.")
        return

    print(f"Recalculando métricas com {len(events)} eventos e {len(ops)} operações...")
    metrics = LogicService.calculate_metrics_grouped(events, ops)
    metrics["period_label"] = period_label

    print("Gerando novo insight com a IA...")
    insight = await ai.generate_daily_insight(metrics['consolidado'], None)

    print(f"Atualizando a análise {analysis_id} no banco de dados...")
    response = db_service.supabase.table("historico_analises").update({
        "metrics": metrics,
        "insight": insight
    }).eq("id", analysis_id).execute()

    if response.data:
        print("✅ Sucesso! Análise da 'Semana 1' foi reprocessada e corrigida.")
    else:
        print(f"❌ Erro! Não foi possível atualizar a análise: {response.error}")

if __name__ == "__main__":
    asyncio.run(main())
