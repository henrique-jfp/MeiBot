from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from .ai_service import AIService
from .db import DBService
from .logic import LogicService
from .routes_claim.router import router as routes_claim_router
import base64
import datetime
import traceback
import json
import asyncio

app = FastAPI()
db = DBService()
ai = AIService()

user_locks = {}
def get_user_lock(user_id):
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

def override_data_ref_from_text(content: str, data_ref: str):
    text = (content or "").lower()
    today = datetime.date.today()
    if "anteontem" in text: return (today - datetime.timedelta(days=2)).isoformat()
    if "ontem" in text: return (today - datetime.timedelta(days=1)).isoformat()
    if "hoje" in text: return today.isoformat()
    return data_ref

app.include_router(routes_claim_router)

@app.post("/webhook")
async def handle_webhook(request: Request):
    try:
        data = await request.json()
        whatsapp_number = data.get("from")
        message_type = data.get("type")
        content = data.get("content")
        
        user = db.get_user_by_whatsapp(whatsapp_number)
        if not user: user = db.create_user(whatsapp_number)
        if not user.get("id"): return {"reply": "❌ Erro de banco de dados."}

        lock = get_user_lock(user["id"])
        async with lock:
            response_text = ""
            if message_type == "text":
                interpreted = await ai.interpret_message(content)
                interpreted["data_referencia"] = override_data_ref_from_text(content, interpreted.get("data_referencia"))
                response_text = await process_interpreted_data(user, interpreted)
            elif message_type == "image":
                image_bytes = base64.b64decode(content)
                interpreted = await ai.process_image(image_bytes, "image/jpeg")
                response_text = await process_interpreted_data(user, interpreted)
            elif message_type == "audio":
                audio_bytes = base64.b64decode(content)
                transcription = await ai.transcribe_audio(audio_bytes)
                interpreted = await ai.interpret_message(transcription)
                response_text = await process_interpreted_data(user, interpreted)
                response_text = f"🎙️ *Transcrição:* \"{transcription}\"\n\n{response_text}"

        return {"reply": response_text}
    except Exception as e:
        traceback.print_exc()
        return {"reply": "⚠️ Tive uma instabilidade momentânea. Tente novamente em alguns segundos."}

async def process_interpreted_data(user, interpreted):
    intencao = interpreted.get("intencao")
    user_id = user["id"]
    data_ref = interpreted.get("data_referencia")
    if data_ref == "null": data_ref = None
    eventos_brutos = interpreted.get("eventos", [])
    whatsapp = user["whatsapp_number"]
    
    if intencao == "cadastrar_entregador":
        info = interpreted.get("entregador_info", {})
        res = db.add_entregador(user_id, info.get("nome"), info.get("valor_diaria"))
        return f"✅ Entregador *{info.get('nome')}* cadastrado!" if res else "❌ Erro."

    # 1. Pega ou cria a operação correta (suporte a retroativo)
    if data_ref:
        active_op = db.get_or_create_operation_by_date(user_id, data_ref)
    else:
        active_op = db.get_active_operation(user_id)
        if not active_op and len(eventos_brutos) > 0:
            active_op = db.start_operation(user_id)

    eventos_processados = []
    for ev in eventos_brutos:
        # Normalização e Regras de Negócio Hardcoded
        app_name_raw = str(ev.get("app") or "").lower()
        
        # Se a IA esquecer de colocar o nome do app, mas tiver pacotes, assumimos Correios por padrão (maior uso de pacotes)
        if not app_name_raw or app_name_raw == "none":
            if float(ev.get("pacotes") or 0) > 0:
                app_name_raw = "correios"
                ev["app"] = "Correios"
        
        if "shopee" in app_name_raw:
            ev["app"] = "Shopee"
            ev["valor"] = 305.0 + float(ev.get("valor_extra") or 0)
            ev["km"] = 60.0
            ev["tipo"] = "ganho"
        
        elif "correio" in app_name_raw:
            ev["app"] = "Correios"
            ev["km"] = 20.0
            ev["tipo"] = "ganho"
            
            v = float(ev.get("valor") or 0)
            p = float(ev.get("pacotes") or 0)
            
            # Se o valor extraído pela IA for zero, ou se ela se confundir e jogar o número
            # de pacotes dentro do campo "valor", nós forçamos a regra matemática correta.
            if v == 0 or v == p:
                ev["valor"] = (p * 2.0) + float(ev.get("valor_extra") or 0)
            else:
                ev["valor"] = v + float(ev.get("valor_extra") or 0)
        
        else:
            # Regras via Banco de Dados
            app_info = db.get_app_by_name(ev.get("app")) if ev.get("app") else None
            if app_info and (not ev.get("valor") or ev.get("valor") == 0):
                if app_info.get("tipo_remuneracao") == "pacote":
                    ev["valor"] = (ev.get("pacotes", 0) * app_info["valor_base"]) + float(ev.get("valor_extra") or 0)
                elif app_info.get("tipo_remuneracao") == "rota":
                    ev["valor"] = app_info["valor_base"] + float(ev.get("valor_extra") or 0)
            elif ev.get("valor"):
                ev["valor"] = float(ev["valor"]) + float(ev.get("valor_extra") or 0)

        # 2. Lançamento AUTOMÁTICO de repasse para entregador (Ajudante) via Banco
        app_info = db.get_app_by_name(ev.get("app")) if ev.get("app") else None
        if app_info and app_info.get("entregador_padrao_id"):
            res_ent = db.supabase.table("entregadores").select("valor_diaria").eq("id", app_info["entregador_padrao_id"]).execute()
            if res_ent.data:
                valor_pagamento = res_ent.data[0]["valor_diaria"]
                gasto_ent = {
                    "tipo": "gasto", "categoria": "Essencial",
                    "valor": valor_pagamento, "app": ev.get("app"),
                    "descricao": f"Pagamento ajudante {ev.get('app')} (Auto)"
                }
                if data_ref: gasto_ent["data_referencia"] = data_ref
                db.add_event(user_id, active_op["id"], gasto_ent)
                eventos_processados.append(gasto_ent)

        if active_op:
            h_chegada = ev.get("hora_chegada_galpao")
            h_saida_galpao = ev.get("hora_saida_galpao")
            h_inicio_rota = ev.get("hora_inicio_rota")
            h_fim_espera = h_saida_galpao or h_inicio_rota
            if h_chegada and h_fim_espera:
                wait_event = {
                    "tipo": "registro",
                    "sub_tipo": "espera_galpao",
                    "hora_inicio": h_chegada,
                    "hora_fim": h_fim_espera,
                    "descricao": "Espera no galpao"
                }
                if data_ref:
                    wait_event["data_referencia"] = data_ref
                db.add_event(user_id, active_op["id"], wait_event)
                eventos_processados.append(wait_event)

            if data_ref: ev["data_referencia"] = data_ref
            db.add_event(user_id, active_op["id"], ev)
            eventos_processados.append(ev)

    if intencao == "registro":
        return LogicService.format_events_confirmation(eventos_processados, "DADOS REGISTRADOS", data_ref) if eventos_processados else "Nada para registrar."

    if intencao == "resumo_diario":
        target_date = data_ref or datetime.date.today().isoformat()
        events_curr = db.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", target_date).lt("timestamp", (datetime.datetime.fromisoformat(target_date) + datetime.timedelta(days=1)).isoformat()).execute().data
        ops_curr = db.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).eq("data", target_date).execute().data
        metrics_curr = LogicService.calculate_metrics_grouped(events_curr, ops_curr)
        return await ai.generate_daily_insight(metrics_curr["consolidado"], None)

    if intencao in ["resumo_semanal", "resumo_mensal"]:
        url = f"https://meibot.henriquedejesus.dev/dashboard/{whatsapp}"
        return f"📊 *Automação Ativada!*\n\nOs relatórios agora são gerados de forma 100% automática! Todo sábado às 21h (e no último dia do mês), nossa inteligência artificial processa seus dados e cria o arquivo.\n\nVocê pode consultar as análises agrupadas por mês a qualquer momento no seu painel:\n🔗 {url}"

    if intencao == "encerrar":
        if active_op: db.end_operation(active_op["id"])
        return f"🚀 Operação encerrada com sucesso! Bom descanso."

    if intencao == "pergunta":
        events_db = db.get_all_time_summary(user_id)
        return await ai.answer_question(str(events_db), interpreted.get("pergunta", ""))

    # --- MAPEAMENTO DE PORTEIROS ---
    url_dashboard = f"https://meibot.henriquedejesus.dev/dashboard/{whatsapp}"

    if intencao == "cadastrar_porteiro":
        info = interpreted.get("porteiro_info", {})
        res = db.add_porteiro(user_id, info.get("rua"), info.get("numero"), info.get("nome"), info.get("turno"), info.get("notas"))
        if res == "DUPLICATE":
            return f"⚠️ O porteiro *{info.get('nome')}* já está mapeado para este endereço."
        return f"✅ Porteiro *{info.get('nome')}* mapeado com sucesso em {info.get('rua')}, {info.get('numero')}!\n\nVocê pode ver o mapa completo aqui:\n🔗 {url_dashboard}" if res else "❌ Erro ao cadastrar porteiro."

    if intencao == "consultar_porteiro":
        info = interpreted.get("porteiro_info", {})
        porteiros = db.get_porteiros_by_address(user_id, info.get("rua"), info.get("numero"))
        if not porteiros:
            return f"🔍 Nenhum porteiro encontrado para {info.get('rua')}, {info.get('numero')}."
        
        res = f"🏢 *Porteiros em {info.get('rua')}, {info.get('numero')}*\n\n"
        for p in porteiros:
            turno = f" ({p['turno']})" if p.get("turno") else ""
            res += f"• *{p['nome_porteiro']}*{turno}\n"
            if p.get("notas_predio"):
                res += f"  📝 Notas: {p['notas_predio']}\n"
        res += f"\n🔗 {url_dashboard}"
        return res

    if intencao == "listar_porteiros":
        porteiros = db.get_all_porteiros(user_id)
        if not porteiros:
            return "📭 Você ainda não mapeou nenhum porteiro."
        
        res = "📋 *MEU MAPEAMENTO ESTRATÉGICO*\n"
        
        # Agrupamento e Normalização por Rua
        grouped = {}
        for p in porteiros:
            rua_raw = p.get('rua') or "Rua Não Informada"
            rua = rua_raw.strip().title()
            
            # Normalização para Paissandu/Paisandu
            rua_norm = rua.upper()
            if "PAISANDU" in rua_norm or "PAISSANDU" in rua_norm:
                rua = "Paissandu"
            
            if rua not in grouped:
                grouped[rua] = []
            grouped[rua].append(p)
            
        # Ordenar ruas alfabeticamente
        for rua in sorted(grouped.keys()):
            items = grouped[rua]
            res += f"\n┏━━━━━━━━━━━━━━┓\n"
            res += f"┃ 🏢 *{rua.upper()}* \n"
            res += f"┗━━━━━━━━━━━━━━┛\n"
            
            # Ordenar por número
            try:
                items.sort(key=lambda x: int(''.join(filter(str.isdigit, x.get('numero', '0'))) or 0))
            except:
                pass

            for p in items:
                turno = f" *({p['turno']})*" if p.get("turno") else ""
                num = p.get('numero') or "?"
                nome = p.get('nome_porteiro') or "Porteiro Desconhecido"
                res += f"🔹 *N° {num}*: {nome}{turno}\n"
                if p.get("notas_predio"):
                    res += f"   ╰─ 📓 _\"{p['notas_predio']}\"_\n"
        
        res += f"\n────────────────\n"
        res += f"🖥️ *DASHBOARD COMPLETO:*\n🔗 {url_dashboard}"
        return res

    if intencao == "corrigir_porteiro":
        info = interpreted.get("porteiro_info", {})
        res = db.update_porteiro(user_id, info.get("rua"), info.get("numero"), info.get("nome_antigo"), info.get("nome"), info.get("turno"), info.get("notas"))
        return f"✅ Informações do porteiro atualizadas!\n\n🔗 {url_dashboard}" if res else "❌ Não consegui atualizar as informações. Verifique se o nome antigo está correto."

    if intencao == "pedir_link_dashboard":
        return f"📊 *Seu Painel de Performance e Mapa de Porteiros*:\n\n🔗 {url_dashboard}"

    return "Não entendi o que você quis dizer ou faltaram informações. Tente ser mais claro, ou digite 'Ajuda'."

@app.get("/api/dashboard/{whatsapp_number}")
async def get_dashboard_data(whatsapp_number: str, analysis_id: str = None):
    user = db.get_user_by_whatsapp(whatsapp_number)
    if not user: return JSONResponse({"error": "User not found"}, status_code=404)
    user_id = user["id"]
    
    porteiros = db.get_all_porteiros(user_id)
    history = db.get_analysis_history(user_id, limit=30)

    if analysis_id:
        res = db.supabase.table("historico_analises").select("*").eq("id", analysis_id).execute()
        if res.data:
            analysis = res.data[0]
            return {
                "user": user, 
                "metrics": analysis["metrics"], 
                "insight": analysis["insight"], 
                "is_live": False,
                "created_at": analysis["created_at"],
                "history": history,
                "porteiros": porteiros
            }

    if history:
        today = datetime.date.today()
        month_start = today.replace(day=1)
        next_month = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        start_iso = month_start.isoformat() + "T00:00:00Z"
        end_iso = next_month.isoformat() + "T00:00:00Z"

        ev_live = db.supabase.table("eventos").select("*, apps(*)")\
            .eq("user_id", user_id)\
            .gte("timestamp", start_iso)\
            .lt("timestamp", end_iso)\
            .execute().data

        op_live = db.supabase.table("operacoes_dia").select("*")\
            .eq("user_id", user_id)\
            .gte("data", month_start.isoformat())\
            .lt("data", next_month.isoformat())\
            .execute().data

        metrics_live = LogicService.calculate_metrics_grouped(ev_live, op_live)

        # NOVO CÓDIGO: Calcular performance diária
        daily_performance = {}
        for ev in ev_live:
            tipo = ev.get("tipo", "").lower()
            if tipo in ["ganho", "rota", "corrida", "faturamento"]:
                try:
                    # Extrai a data do timestamp
                    event_date = datetime.datetime.fromisoformat(ev["timestamp"]).strftime('%Y-%m-%d')
                    valor = float(ev.get("valor", 0))
                    
                    # Agrupa os ganhos por dia
                    if event_date not in daily_performance:
                        daily_performance[event_date] = 0
                    daily_performance[event_date] += valor
                except:
                    continue # Ignora eventos com timestamp mal formatado

        # Transforma o dicionário em uma lista de objetos para o frontend
        daily_performance_list = [{"date": d, "ganho": g} for d, g in daily_performance.items()]
        daily_performance_list.sort(key=lambda x: x['date'])

        return {
            "user": user,
            "metrics": metrics_live,
            "daily_performance": daily_performance_list, # <-- NOVO CAMPO
            "insight": "",
            "is_live": True,
            "history": history,
            "created_at": datetime.datetime.now().isoformat(),
            "porteiros": porteiros
        }
    
    today = datetime.date.today()
    month_start = today.replace(day=1)
    next_month = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    start_iso = month_start.isoformat() + "T00:00:00Z"
    end_iso = next_month.isoformat() + "T00:00:00Z"

    ev_month = db.supabase.table("eventos").select("*, apps(*)")\
        .eq("user_id", user_id)\
        .gte("timestamp", start_iso)\
        .lt("timestamp", end_iso)\
        .execute().data

    op_month = db.supabase.table("operacoes_dia").select("*")\
        .eq("user_id", user_id)\
        .gte("data", month_start.isoformat())\
        .lt("data", next_month.isoformat())\
        .execute().data

    metrics_week = LogicService.calculate_metrics_grouped(ev_month, op_month)
    
    return {
        "user": user,
        "metrics": metrics_week,
        "insight": "",
        "is_live": True,
        "history": [],
        "porteiros": porteiros
    }

@app.get("/dashboard/{whatsapp_number}", response_class=HTMLResponse)
async def dashboard_page(whatsapp_number: str):
    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>MeiBot - Dashboard Analítico</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            :root {
                --ink: #0f172a;
                --line: #e2e8f0;
                --brand: #0f766e;
            }
            body {
                font-family: 'Inter', sans-serif;
                background-color: #f8fafc;
                color: var(--ink);
            }
            .tooltip-container { position: relative; display: inline-flex; align-items: center; gap: 6px;}
            .tooltip {
                display: none;
                position: absolute;
                bottom: 100%;
                left: 50%;
                transform: translateX(-50%);
                margin-bottom: 8px;
                background-color: #1e293b;
                color: white;
                padding: 10px;
                border-radius: 8px;
                font-size: 12px;
                width: 240px;
                text-align: center;
                z-index: 10;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                opacity: 0;
                transition: opacity 0.2s;
                pointer-events: none;
            }
            .tooltip-container:hover .tooltip { display: block; opacity: 1;}
            .card { background: white; border: 1px solid var(--line); border-radius: 16px; }
        </style>
    </head>
    <body class="flex flex-col lg:flex-row min-h-screen">
        <aside class="w-full lg:w-80 bg-white/95 backdrop-blur border-b lg:border-b-0 lg:border-r border-slate-200 p-5 lg:p-6 flex-shrink-0 z-50 sticky top-0 lg:h-screen lg:overflow-y-auto">
            <div class="flex items-center gap-3 mb-8">
                <div class="w-10 h-10 bg-teal-600 rounded-lg flex items-center justify-center text-white"> 
                    <i class="fa-solid fa-bolt"></i> 
                </div>
                <div>
                    <h1 class="font-bold text-lg text-slate-800 leading-tight">MeiBot</h1>
                    <p class="text-xs text-slate-500 font-medium">Dashboard Analítico</p>
                </div>
            </div>
            
            <div class="mb-6">
                <p class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-3">Navegação</p>
                <div class="flex flex-row lg:flex-col gap-2">
                    <button onclick="showSection('performance')" class="flex items-center gap-3 p-2.5 rounded-lg bg-teal-50 text-teal-700 font-semibold text-sm transition-colors border border-teal-100">
                        <i class="fa-solid fa-chart-pie w-4"></i> Performance
                    </button>
                    <button onclick="showSection('porteiros')" class="flex items-center gap-3 p-2.5 rounded-lg text-slate-600 font-medium text-sm transition-colors hover:bg-slate-100">
                        <i class="fa-solid fa-map-location-dot w-4"></i> Porteiros
                    </button>
                </div>
            </div>

            <p class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-3">Histórico</p>
            <nav id="history-list" class="flex lg:flex-col gap-3 lg:gap-2.5 overflow-x-auto lg:overflow-visible pb-2 lg:pb-0 snap-x"></nav>
        </aside>

        <main class="flex-grow p-5 md:p-8 space-y-6 md:space-y-8 w-full max-w-7xl mx-auto">
            <header class="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-slate-200 pb-5 gap-4">
                <div>
                    <h2 class="text-2xl md:text-3xl font-bold text-slate-800 tracking-tight" id="main-title">Visão Geral</h2>
                    <p id="txt-periodo" class="text-slate-500 text-sm mt-1">Carregando dados...</p>
                </div>
            </header>

            <div id="section-performance" class="space-y-6">
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    <div class="card p-5"><div class="tooltip-container mb-2"><p class="text-slate-500 text-sm font-semibold">Faturamento Bruto</p><i class="fa-solid fa-circle-info text-slate-400 text-xs"></i><span class="tooltip">Soma de todos os ganhos registrados no período.</span></div><p id="txt-bruto" class="text-3xl font-bold text-slate-800">R$ 0,00</p></div>
                    <div class="card p-5"><div class="tooltip-container mb-2"><p class="text-slate-500 text-sm font-semibold">Saldo Líquido</p><i class="fa-solid fa-circle-info text-slate-400 text-xs"></i><span class="tooltip">Faturamento Bruto menos todos os gastos.</span></div><p id="txt-saldo" class="text-3xl font-bold text-teal-700">R$ 0,00</p></div>
                    <div class="card p-5"><div class="tooltip-container mb-2"><p class="text-slate-500 text-sm font-semibold">Saldo c/ Provisão</p><i class="fa-solid fa-circle-info text-slate-400 text-xs"></i><span class="tooltip">Saldo líquido menos uma reserva de R$0,20 por KM rodado para manutenções.</span></div><p id="txt-saldo-provisao" class="text-3xl font-bold text-sky-700">R$ 0,00</p></div>
                    <div class="card p-5"><div class="tooltip-container mb-2"><p class="text-slate-500 text-sm font-semibold">Eficiência (KM)</p><i class="fa-solid fa-circle-info text-slate-400 text-xs"></i><span class="tooltip">Quanto você fatura para cada KM rodado.</span></div><p id="txt-eficiencia" class="text-3xl font-bold text-indigo-700">R$ 0,00/km</p></div>
                    <div class="card p-5"><div class="tooltip-container mb-2"><p class="text-slate-500 text-sm font-semibold">Eficiência (Hora)</p><i class="fa-solid fa-circle-info text-slate-400 text-xs"></i><span class="tooltip">Seu ganho líquido por hora total de trabalho.</span></div><p id="txt-ganho-hora" class="text-3xl font-bold text-indigo-700">R$ 0,00/h</p></div>
                    <div class="card p-5"><div class="tooltip-container mb-2"><p class="text-slate-500 text-sm font-semibold">Eficiência na Rua</p><i class="fa-solid fa-circle-info text-slate-400 text-xs"></i><span class="tooltip">Ganho bruto por hora em rota, descontando o tempo de espera no galpão.</span></div><p id="txt-ganho-hora-rua" class="text-3xl font-bold text-violet-700">R$ 0,00/h</p></div>
                </div>

                <div id="daily-chart-container" class="card p-6" style="display: none;">
                    <h3 class="font-bold text-slate-800 text-sm mb-6 uppercase tracking-tight">Performance Diária (Mês Atual)</h3>
                    <div class="relative w-full h-[300px]"><canvas id="chartDaily"></canvas></div>
                </div>
                <div id="apps-chart-container" class="card p-6" style="display: none;">
                    <h3 class="font-bold text-slate-800 text-sm mb-6 uppercase tracking-tight">Performance por Período</h3>
                    <div class="relative w-full h-[300px]"><canvas id="chartApps"></canvas></div>
                </div>
                
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div class="lg:col-span-2 card p-6"><h3 class="font-bold text-slate-800 text-sm mb-6 uppercase tracking-tight">Detalhamento por App</h3><div id="list-apps" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div></div>
                    <div class="card p-6 flex flex-col"><h3 class="font-bold text-slate-800 text-sm mb-6 uppercase tracking-tight">Distribuição de Gastos</h3><div class="relative w-full h-[200px] mb-6"><canvas id="chartGastos"></canvas></div></div>
                </div>
            </div>
            
            <div id="section-porteiros" class="hidden"></div>
        </main>

        <script>
            let dailyChart = null, appsChart = null, chartGastos = null;
            let dashboardData = null;
            const WHATSAPP_ID = '""" + whatsapp_number + """';

            function showSection(section) {
                document.getElementById('section-performance').style.display = 'none';
                document.getElementById('section-porteiros').style.display = 'none';
                document.getElementById('section-' + section).style.display = 'block';
                document.getElementById('main-title').innerText = section === 'performance' ? 'Visão Geral' : 'Diretório de Porteiros';
                const btns = document.querySelectorAll('aside button');
                btns.forEach(b => {
                    const isTarget = b.getAttribute('onclick').includes(section);
                    b.classList.toggle('bg-teal-50', isTarget);
                    b.classList.toggle('text-teal-700', isTarget);
                    b.classList.toggle('font-semibold', isTarget);
                    b.classList.toggle('bg-transparent', !isTarget);
                    b.classList.toggle('text-slate-600', !isTarget);
                });
                if (section === 'porteiros') renderPorteiros();
            }

            function renderPorteiros() {
                // Logic for rendering porteiros - assuming it exists or will be added
                document.getElementById('section-porteiros').innerHTML = '<p>Funcionalidade de porteiros a ser implementada aqui.</p>';
            }

            const fmt = (val) => (val || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2});

            async function loadDashboard(analysisId = null) {
                try {
                    const url = analysisId ? `/api/dashboard/${WHATSAPP_ID}?analysis_id=${analysisId}` : `/api/dashboard/${WHATSAPP_ID}`;
                    const response = await fetch(url);
                    const data = await response.json();
                    if (data.error) throw new Error(data.error);

                    dashboardData = data;
                    const c = data.metrics.consolidado;
                    const apps = data.metrics.apps;

                    document.getElementById('txt-bruto').innerText = 'R$ ' + fmt(c.total_ganhos);
                    document.getElementById('txt-saldo').innerText = 'R$ ' + fmt(c.saldo);
                    document.getElementById('txt-saldo-provisao').innerText = 'R$ ' + fmt(c.saldo_com_provisao);
                    document.getElementById('txt-eficiencia').innerText = 'R$ ' + (c.total_ganhos / (c.km_total || 1)).toFixed(2) + '/km';
                    document.getElementById('txt-ganho-hora').innerText = 'R$ ' + fmt(c.ganho_por_hora) + '/h';
                    document.getElementById('txt-ganho-hora-rua').innerText = 'R$ ' + fmt(c.ganho_por_hora_rua) + '/h';

                    const listContainer = document.getElementById('list-apps');
                    listContainer.innerHTML = '';
                    for (const name in apps) {
                        const app = apps[name];
                        listContainer.innerHTML += `<div class="p-4 rounded-xl bg-slate-50 border"><p class="font-bold text-sm">${name}</p><p class="text-teal-700">R$ ${fmt(app.ganhos)}</p></div>`;
                    }

                    if (chartGastos) chartGastos.destroy();
                    chartGastos = new Chart(document.getElementById('chartGastos').getContext('2d'), {
                        type: 'doughnut',
                        data: { labels: ['Essenciais', 'Não Essenciais'], datasets: [{ data: [c.gastos_essenciais, c.gastos_nao_essenciais], backgroundColor: ['#0f766e', '#e11d48'] }] },
                        options: { responsive: true, maintainAspectRatio: false, cutout: '75%', plugins: { legend: { display: false } } }
                    });

                    const dailyContainer = document.getElementById('daily-chart-container');
                    const appsContainer = document.getElementById('apps-chart-container');
                    if (data.is_live && data.daily_performance?.length > 0) {
                        dailyContainer.style.display = 'block';
                        appsContainer.style.display = 'none';
                        if (dailyChart) dailyChart.destroy();
                        dailyChart = new Chart(document.getElementById('chartDaily').getContext('2d'), {
                            type: 'bar',
                            data: {
                                labels: data.daily_performance.map(d => new Date(d.date + 'T00:00:00').toLocaleDateString('pt-BR', { day: '2-digit' })),
                                datasets: [{ label: 'Faturamento Diário', data: data.daily_performance.map(d => d.ganho), backgroundColor: '#0f766e' }]
                            },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
                        });
                    } else {
                        dailyContainer.style.display = 'none';
                        appsContainer.style.display = 'block';
                        if (appsChart) appsChart.destroy();
                        const sortedAppNames = Object.keys(apps).filter(name => name !== 'Outros').sort((a,b) => apps[b].ganhos - apps[a].ganhos);
                        appsChart = new Chart(document.getElementById('chartApps').getContext('2d'), {
                            type: 'bar',
                            data: {
                                labels: sortedAppNames,
                                datasets: [{ data: sortedAppNames.map(name => apps[name].ganhos), backgroundColor: ['#0f766e', '#f97316', '#6366f1'] }]
                            },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
                        });
                    }
                } catch (e) { console.error('Dashboard Error:', e); }
            }
            loadDashboard();
        </script>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)