import sys
import os
import asyncio
import datetime
import requests
import traceback
import argparse
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Adiciona o diretório atual ao path para importar app.*
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

VALID_PERIODS = {"semanal", "mensal"}


def load_app_timezone():
    try:
        return ZoneInfo("America/Sao_Paulo")
    except ZoneInfoNotFoundError:
        return datetime.timezone(datetime.timedelta(hours=-3), "America/Sao_Paulo")


APP_TZ = load_app_timezone()


@dataclass(frozen=True)
class ReportPeriod:
    tipo: str
    start: datetime.date
    end: datetime.date

    @property
    def exclusive_end(self):
        return self.end + datetime.timedelta(days=1)

    @property
    def label(self):
        return f"{self.start.strftime('%d/%m')} a {self.end.strftime('%d/%m')}"

    @property
    def created_at(self):
        close_time = datetime.datetime.combine(
            self.end,
            datetime.time(23, 59, 59),
            tzinfo=APP_TZ,
        )
        return close_time.isoformat()


def parse_date(value):
    if value is None or isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(value)


def resolve_report_period(periodo="semanal", reference_date=None, start_date=None, end_date=None):
    if periodo not in VALID_PERIODS:
        raise ValueError("periodo deve ser 'semanal' ou 'mensal'")

    start_date = parse_date(start_date)
    end_date = parse_date(end_date)
    if start_date or end_date:
        if not start_date or not end_date:
            raise ValueError("informe start_date e end_date juntos")
        if end_date < start_date:
            raise ValueError("end_date nao pode ser anterior a start_date")
        return ReportPeriod(periodo, start_date, end_date)

    reference_date = parse_date(reference_date) or datetime.datetime.now(APP_TZ).date()

    if periodo == "semanal":
        days_since_saturday = (reference_date.weekday() - 5) % 7
        period_end = reference_date - datetime.timedelta(days=days_since_saturday)
        period_start = period_end - datetime.timedelta(days=5)
        return ReportPeriod(periodo, period_start, period_end)

    first_day_this_month = reference_date.replace(day=1)
    period_end = first_day_this_month - datetime.timedelta(days=1)
    period_start = period_end.replace(day=1)
    return ReportPeriod(periodo, period_start, period_end)


def _period_start_iso(period_date):
    return datetime.datetime.combine(period_date, datetime.time.min, tzinfo=APP_TZ).isoformat()


def fetch_period_data(db, user_id, period):
    start_ts = _period_start_iso(period.start)
    end_ts = _period_start_iso(period.exclusive_end)

    events = db.supabase.table("eventos").select("*, apps(*)")\
        .eq("user_id", user_id)\
        .gte("timestamp", start_ts)\
        .lt("timestamp", end_ts)\
        .execute().data or []

    ops = db.supabase.table("operacoes_dia").select("*")\
        .eq("user_id", user_id)\
        .gte("data", period.start.isoformat())\
        .lt("data", period.exclusive_end.isoformat())\
        .execute().data or []

    return events, ops


def find_existing_analysis(db, user_id, period):
    response = db.supabase.table("historico_analises")\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("periodo_tipo", period.tipo)\
        .execute()

    for analysis in response.data or []:
        metrics = analysis.get("metrics") or {}
        if metrics.get("period_start") == period.start.isoformat():
            return analysis
    return None


def save_or_update_analysis(db, user_id, period, metrics, insight):
    data_to_save = {
        "metrics": metrics,
        "insight": insight,
    }

    existing = find_existing_analysis(db, user_id, period)
    if existing:
        print(f"Atualizando analise existente de {period.tipo} (ID: {existing['id']})")
        return db.supabase.table("historico_analises")\
            .update(data_to_save)\
            .eq("id", existing["id"])\
            .execute()

    print(f"Criando nova analise de {period.tipo}...")
    data_to_save["user_id"] = user_id
    data_to_save["periodo_tipo"] = period.tipo
    data_to_save["created_at"] = period.created_at
    return db.supabase.table("historico_analises").insert(data_to_save).execute()


async def generate_automated_reports(periodo="semanal", start_date=None, end_date=None, reference_date=None, notify=True):
    from app.db import DBService
    from app.ai_service import AIService
    from app.logic import LogicService

    db = DBService()
    ai = AIService()
    period = resolve_report_period(periodo, reference_date, start_date, end_date)
    
    print(f"[{datetime.datetime.now(APP_TZ)}] Iniciando geracao de relatorios: {period.tipo} ({period.label})")
    
    try:
        # Busca todos os usuários
        users = db.supabase.table("users").select("*").execute().data
        if not users:
            print("Nenhum usuário encontrado.")
            return

        for user in users:
            user_id = user["id"]
            whatsapp = user["whatsapp_number"]

            events, ops = fetch_period_data(db, user_id, period)
            
            if not events:
                print(f"Usuario {whatsapp}: sem dados para {period.label}. Pulando.")
                continue
            
            # Calcula métricas
            metrics = LogicService.calculate_metrics_grouped(events, ops)
            metrics["period_label"] = period.label
            metrics["period_start"] = period.start.isoformat()
            metrics["period_end"] = period.end.isoformat()
            
            # Gera Insight via IA (Groq 70b)
            label = "Semana Fechada" if period.tipo == "semanal" else "Mes Fechado"
            print(f"Gerando insight para {whatsapp}...")
            insight = await ai.generate_analyst_insight(metrics["consolidado"], None, label, metrics.get("apps"))
            
            # Salva/Atualiza permanentemente no histórico
            response = save_or_update_analysis(db, user_id, period, metrics, insight)
            
            if not response.data:
                print(f"!!!!!! Falha ao salvar/atualizar analise para {whatsapp}: {getattr(response, 'error', 'sem erro')}")
            
            # Envia para o WhatsApp via Bot (Node.js na porta 3000)
            if not notify:
                print(f"Notificacao desativada para {whatsapp}.")
                continue

            url = f"https://meibot.henriquedejesus.dev/dashboard/{whatsapp}"
            emoji = "📊" if period.tipo == "semanal" else "📅"
            msg = f"{emoji} *Relatorio {period.tipo.capitalize()} Disponivel!*\n\nSua analise estrategica de {period.label} foi gerada e arquivada no Dashboard.\n\nAcesse agora para ver lucros, gastos e a visao do analista:\n\n🔗 {url}"
            
            try:
                # O BOT_URL padrão é localhost:3000/send-message
                requests.post("http://localhost:3000/send-message", json={"to": whatsapp, "text": msg}, timeout=15)
                print(f"Sucesso: Relatório enviado para {whatsapp}")
            except Exception as e:
                print(f"Erro ao enviar WhatsApp para {whatsapp}: {e}")

    except Exception as e:
        print(f"Erro crítico no cron_reports: {e}")
        traceback.print_exc()


def build_parser():
    parser = argparse.ArgumentParser(description="Gera relatorios automaticos do MeiBot.")
    parser.add_argument("periodo", nargs="?", default="semanal", choices=sorted(VALID_PERIODS))
    parser.add_argument("start_date", nargs="?", help="Data inicial explicita no formato YYYY-MM-DD.")
    parser.add_argument("end_date", nargs="?", help="Data final explicita no formato YYYY-MM-DD.")
    parser.add_argument("--reference-date", help="Data de referencia no formato YYYY-MM-DD.")
    parser.add_argument("--no-notify", action="store_true", help="Nao envia mensagem no WhatsApp.")
    return parser

if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(generate_automated_reports(
        args.periodo,
        start_date=args.start_date,
        end_date=args.end_date,
        reference_date=args.reference_date,
        notify=not args.no_notify,
    ))
