import sys
import os
import asyncio
import datetime

# Adiciona o diretorio atual ao path para importar app.*
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db import DBService
from app.logic import LogicService
from app.ai_service import AIService


def _fmt_label(start_date, end_date):
    return f"{start_date.strftime('%d/%m')} a {end_date.strftime('%d/%m')}"


def _build_periods(today):
    # Semana termina no sabado (hoje), sem domingo.
    end_week_2 = today
    start_week_2 = end_week_2 - datetime.timedelta(days=5)

    end_week_1 = end_week_2 - datetime.timedelta(days=7)
    start_week_1 = end_week_1 - datetime.timedelta(days=5)

    return [
        {"label": "Semana 2", "start": start_week_2, "end": end_week_2},
        {"label": "Semana 1", "start": start_week_1, "end": end_week_1},
    ]


def _fetch_period_data(db, user_id, start_date, end_date):
    start_iso = start_date.isoformat()
    end_iso = (end_date + datetime.timedelta(days=1)).isoformat()

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

    return events, ops


async def main():
    if len(sys.argv) < 2:
        print("Uso: python reprocess_weeks.py <whatsapp_number>")
        return

    whatsapp = sys.argv[1]
    db = DBService()
    ai = AIService()

    user = db.get_user_by_whatsapp(whatsapp)
    if not user or not user.get("id"):
        print(f"Usuario com numero {whatsapp} nao encontrado.")
        return

    user_id = user["id"]
    history = db.get_analysis_history(user_id, limit=50)
    weekly_history = [h for h in history if h.get("periodo_tipo") == "semanal"]

    if len(weekly_history) < 2:
        print("Nao ha duas analises semanais para atualizar.")
        return

    # Ordena do mais antigo para o mais novo entre os dois ultimos
    weekly_history = sorted(weekly_history, key=lambda h: h.get("created_at"))[-2:]

    today = datetime.date.today()
    periods = _build_periods(today)

    for analysis, period in zip(weekly_history, periods):
        start_date = period["start"]
        end_date = period["end"]
        label = _fmt_label(start_date, end_date)

        events, ops = _fetch_period_data(db, user_id, start_date, end_date)
        if not events:
            print(f"{period['label']}: sem eventos de {label}. Pulando.")
            continue

        metrics = LogicService.calculate_metrics_grouped(events, ops)
        metrics["period_label"] = label
        metrics["period_start"] = start_date.isoformat()
        metrics["period_end"] = end_date.isoformat()

        print(f"Gerando insight para {period['label']} ({label})...")
        insight = await ai.generate_analyst_insight(metrics["consolidado"], None, period["label"], metrics.get("apps"))

        print(f"Atualizando analise {analysis['id']}...")
        response = db.supabase.table("historico_analises").update({
            "metrics": metrics,
            "insight": insight
        }).eq("id", analysis["id"]).execute()

        if response.data:
            print(f"OK: {period['label']} atualizada.")
        else:
            print(f"Erro ao atualizar {period['label']}: {response.error}")


if __name__ == "__main__":
    asyncio.run(main())
