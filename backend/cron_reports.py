import sys
import os
import asyncio
import datetime
import requests
import traceback

# Adiciona o diretório atual ao path para importar app.*
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db import DBService
from app.ai_service import AIService
from app.logic import LogicService

async def generate_automated_reports(periodo="semanal"):
    db = DBService()
    ai = AIService()
    
    print(f"[{datetime.datetime.now()}] Iniciando geração de relatórios: {periodo}")
    
    try:
        # Busca todos os usuários
        users = db.supabase.table("users").select("*").execute().data
        if not users:
            print("Nenhum usuário encontrado.")
            return

        for user in users:
            user_id = user["id"]
            whatsapp = user["whatsapp_number"]
            
            # Define o período de busca (7 ou 30 dias)
            days = 7 if periodo == "semanal" else 30
            
            # Busca eventos e operações
            if periodo == "semanal":
                events = db.get_weekly_summary(user_id)
            else:
                events = db.get_monthly_summary(user_id)
            
            if not events:
                print(f"Usuário {whatsapp}: Sem dados para o período. Pulando.")
                continue
                
            ops = db.get_operations_for_period(user_id, days)
            
            # Calcula métricas
            metrics = LogicService.calculate_metrics_grouped(events, ops)
            
            # Gera Insight via IA (Groq 70b)
            label = "Semana Atual" if periodo == "semanal" else "Mês Atual"
            print(f"Gerando insight para {whatsapp}...")
            insight = await ai.generate_analyst_insight(metrics["consolidado"], None, label, metrics.get("apps"))
            
            # Salva permanentemente no histórico
            db.save_analysis(user_id, periodo, metrics, insight)
            
            # Envia para o WhatsApp via Bot (Node.js na porta 3000)
            url = f"https://meibot.henriquedejesus.dev/dashboard/{whatsapp}"
            emoji = "📊" if periodo == "semanal" else "📅"
            msg = f"{emoji} *Relatório {periodo.capitalize()} Disponível!*\n\nSua análise estratégica foi gerada e arquivada na sua pasta mensal no Dashboard.\n\nAcesse agora para ver lucros, gastos e a visão do analista:\n\n🔗 {url}"
            
            try:
                # O BOT_URL padrão é localhost:3000/send-message
                requests.post("http://localhost:3000/send-message", json={"to": whatsapp, "text": msg}, timeout=15)
                print(f"Sucesso: Relatório enviado para {whatsapp}")
            except Exception as e:
                print(f"Erro ao enviar WhatsApp para {whatsapp}: {e}")

    except Exception as e:
        print(f"Erro crítico no cron_reports: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    # Padrão é semanal. Pode ser chamado com 'mensal' como argumento.
    p = sys.argv[1] if len(sys.argv) > 1 else "semanal"
    asyncio.run(generate_automated_reports(p))
