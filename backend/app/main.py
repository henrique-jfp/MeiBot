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
        return {
            "user": user,
            "metrics": metrics_live,
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
            @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');
            :root {
                --ink: #0f172a;
                --line: #e2e8f0;
                --brand: #0f766e;
                --brand-strong: #115e59;
                --accent: #f59e0b;
                --surface: #ffffff;
            }
            body {
                font-family: 'Space Grotesk', sans-serif;
                background: radial-gradient(1200px 600px at 20% -10%, #d1fae5 0%, transparent 60%),
                            radial-gradient(900px 500px at 100% 0%, #fef3c7 0%, transparent 55%),
                            #f8fafc;
                color: var(--ink);
                overflow-x: hidden;
            }
            ::-webkit-scrollbar { width: 6px; height: 6px; }
            ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
            .history-item { transition: all 0.2s ease-in-out; }
            .history-item:hover { transform: translateY(-1px); box-shadow: 0 4px 6px -1px rgb(15 23 42 / 0.08); }
            .history-item:active { transform: translateY(0); }
            .card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 8px 18px -14px rgb(15 23 42 / 0.25); }
        </style>
    </head>
    <body class="flex flex-col lg:flex-row min-h-screen">
        <!-- Sidebar -->
        <aside class="w-full lg:w-80 bg-white/90 backdrop-blur border-b lg:border-b-0 lg:border-r border-slate-200 p-5 lg:p-6 flex-shrink-0 z-50 sticky top-0 lg:h-screen lg:overflow-y-auto">
            <div class="flex items-center gap-3 mb-8">
                <div class="w-10 h-10 bg-teal-600 rounded-lg flex items-center justify-center shadow-md shadow-teal-200 text-white"> 
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
                    <button onclick="showSection('porteiros')" class="flex items-center gap-3 p-2.5 rounded-lg bg-transparent text-slate-600 font-medium text-sm transition-colors hover:bg-slate-50 border border-transparent hover:border-slate-200">
                        <i class="fa-solid fa-map-location-dot w-4"></i> Porteiros
                    </button>
                </div>
            </div>

            <p class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-3">Histórico</p>
            <nav id="history-list" class="flex lg:flex-col gap-3 lg:gap-2.5 overflow-x-auto lg:overflow-visible pb-2 lg:pb-0 snap-x"></nav>
        </aside>

        <!-- Main Content -->
        <main class="flex-grow p-5 md:p-8 space-y-6 md:space-y-8 w-full max-w-7xl mx-auto">
            <header class="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-slate-200 pb-5 gap-4">
                <div>
                    <h2 class="text-2xl md:text-3xl font-bold text-slate-800 tracking-tight" id="main-title">Visão Geral</h2>
                    <p id="txt-periodo" class="text-slate-500 text-sm mt-1">Carregando dados estruturados...</p>
                </div>
                <div class="bg-white border border-slate-200 px-4 py-2.5 rounded-lg shadow-sm w-full md:w-auto flex items-center gap-3">
                    <div class="w-8 h-8 bg-slate-100 rounded-full flex items-center justify-center text-slate-400">
                        <i class="fa-solid fa-user"></i>
                    </div>
                    <div>
                        <p class="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">Operador</p>
                        <p class="text-sm font-bold text-slate-700">ID: """ + whatsapp_number + """</p>
                    </div>
                </div>
            </header>

            <!-- SECTION: PERFORMANCE -->
            <div id="section-performance" class="space-y-6">
                <!-- Main Metrics Grid -->
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div class="card p-5 border-l-4 border-l-slate-400">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-slate-500 text-[10px] font-bold uppercase tracking-wider">Faturamento Bruto</p>
                            <div class="w-7 h-7 bg-slate-50 rounded-lg flex items-center justify-center text-slate-400">
                                <i class="fa-solid fa-money-bill-wave text-xs"></i>
                            </div>
                        </div>
                        <p id="txt-bruto" class="text-2xl font-bold text-slate-800">R$ 0,00</p>
                        <p id="txt-faturamento-avg" class="text-[10px] text-slate-400 mt-1 font-medium">Média: R$ 0,00/dia</p>
                    </div>

                    <div class="card p-5 border-l-4 border-l-teal-500">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-teal-600 text-[10px] font-bold uppercase tracking-wider">Saldo Líquido</p>
                            <div class="w-7 h-7 bg-teal-50 rounded-lg flex items-center justify-center text-teal-500">
                                <i class="fa-solid fa-wallet text-xs"></i>
                            </div>
                        </div>
                        <p id="txt-saldo" class="text-2xl font-bold text-teal-700">R$ 0,00</p>
                        <p id="txt-margem" class="text-[10px] text-teal-500 mt-1 font-bold italic">Margem: 0%</p>
                    </div>

                    <div class="card p-5 border-l-4 border-l-indigo-500">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-indigo-600 text-[10px] font-bold uppercase tracking-wider">Eficiência Logística</p>
                            <div class="w-7 h-7 bg-indigo-50 rounded-lg flex items-center justify-center text-indigo-500">
                                <i class="fa-solid fa-gauge-high text-xs"></i>
                            </div>
                        </div>
                        <p id="txt-eficiencia" class="text-2xl font-bold text-indigo-700">R$ 0,00/km</p>
                        <p id="txt-ganho-hora" class="text-[10px] text-indigo-500 mt-1 font-medium">R$ 0,00/hora</p>
                    </div>

                    <div class="card p-5 border-l-4 border-l-amber-500">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-amber-600 text-[10px] font-bold uppercase tracking-wider">Tempo em Operação</p>
                            <div class="w-7 h-7 bg-amber-50 rounded-lg flex items-center justify-center text-amber-500">
                                <i class="fa-solid fa-clock text-xs"></i>
                            </div>
                        </div>
                        <p id="txt-tempo" class="text-2xl font-bold text-amber-700">0h</p>
                        <p id="txt-tempo-avg" class="text-[10px] text-amber-500 mt-1 font-medium">Média: 0h/dia</p>
                    </div>
                </div>

                <!-- Secondary Metrics & Charts Row -->
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <!-- Main Bar Chart (Stacked) -->
                    <div class="lg:col-span-2 card p-6">
                        <div class="flex justify-between items-center mb-6">
                            <h3 id="chart-title" class="font-bold text-slate-800 text-sm flex items-center gap-2 uppercase tracking-tight">
                                <i class="fa-solid fa-chart-column text-teal-600"></i> Performance por Período
                            </h3>
                            <div id="chart-legend" class="flex gap-3"></div>
                        </div>
                        <div class="relative w-full h-[300px]">
                            <canvas id="chartApps"></canvas>
                        </div>
                    </div>

                    <!-- Expense Distribution (Pie/Doughnut) -->
                    <div class="card p-6 flex flex-col">
                        <h3 class="font-bold text-slate-800 text-sm mb-6 flex items-center gap-2 uppercase tracking-tight">
                            <i class="fa-solid fa-chart-pie text-rose-500"></i> Distribuição de Gastos
                        </h3>
                        <div class="relative w-full h-[200px] mb-6">
                            <canvas id="chartGastos"></canvas>
                        </div>
                        <div class="space-y-3 mt-auto">
                            <div class="flex justify-between items-center p-2 rounded-lg bg-slate-50 border border-slate-100">
                                <span class="text-[10px] font-bold text-slate-500 uppercase">Essenciais</span>
                                <span id="txt-essencial" class="text-xs font-bold text-slate-700">R$ 0,00</span>
                            </div>
                            <div class="flex justify-between items-center p-2 rounded-lg bg-slate-50 border border-slate-100">
                                <span class="text-[10px] font-bold text-slate-500 uppercase">Não Essenciais</span>
                                <span id="txt-nao-essencial" class="text-xs font-bold text-rose-600">R$ 0,00</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- App Details & Waiting Time -->
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div class="lg:col-span-2 card p-6">
                        <h3 class="font-bold text-slate-800 text-sm mb-6 flex items-center gap-2 uppercase tracking-tight">
                            <i class="fa-solid fa-layer-group text-teal-600"></i> Detalhamento por App
                        </h3>
                        <div id="list-apps" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
                    </div>

                    <div class="card p-6 bg-amber-50/30 border-amber-100">
                        <h3 class="font-bold text-amber-800 text-sm mb-4 flex items-center gap-2 uppercase tracking-tight">
                            <i class="fa-solid fa-warehouse"></i> Eficiência de Galpão
                        </h3>
                        <div class="flex items-end gap-2 mb-2">
                            <p id="txt-tempo-espera" class="text-3xl font-bold text-amber-700">0h</p>
                            <p class="text-xs text-amber-500 font-bold mb-1 uppercase">Total Espera</p>
                        </div>
                        <p id="txt-tempo-espera-avg" class="text-xs text-amber-600 font-medium mb-4 italic">Média: 0h/dia</p>
                        <div class="w-full bg-amber-100 rounded-full h-2 overflow-hidden">
                            <div id="bar-espera" class="bg-amber-500 h-full transition-all" style="width: 0%"></div>
                        </div>
                        <p class="text-[10px] text-amber-500 mt-2 font-bold uppercase tracking-wider">Perda de produtividade por espera</p>
                    </div>
                </div>

                <!-- Strategic Analysis Section -->
                <div class="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm transition-all hover:border-teal-200">
                    <div class="bg-teal-600 px-6 py-4 flex items-center justify-between">
                        <h3 class="text-white font-bold text-sm uppercase tracking-wider flex items-center gap-2"> 
                            <i class="fa-solid fa-robot"></i> Inteligência Artificial MeiBot
                        </h3>
                        <div class="px-2 py-1 bg-teal-500/30 rounded-md text-[10px] text-white font-bold border border-white/20 uppercase">
                            Analista Estratégico
                        </div>
                    </div>
                    <div class="p-6 md:p-8 bg-slate-50/50">
                        <div id="txt-insight" class="prose prose-sm max-w-none text-slate-700 leading-relaxed font-medium"></div>
                    </div>
                </div>
            </div>

            <!-- SECTION: PORTEIROS -->
            <div id="section-porteiros" class="hidden space-y-6">
                <!-- Header Limpo -->
                <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
                    <div>
                        <h3 class="text-xl font-bold text-slate-800 flex items-center gap-2">
                            <span class="text-2xl">🗺️</span> Mapeamento de Porteiros
                        </h3>
                        <p id="porteiros-stats" class="text-slate-500 text-sm mt-1 font-medium">Carregando estatísticas...</p>
                    </div>
                    <div class="relative w-full md:w-96 group">
                        <div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                            <i class="fa-solid fa-magnifying-glass text-slate-400 group-focus-within:text-teal-600 transition-colors"></i>
                        </div>
                        <input type="text" id="search-porteiros" oninput="handleSearch(this.value)" 
                            class="block w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 focus:bg-white transition-all" 
                            placeholder="Buscar prédio, rua ou porteiro...">
                    </div>
                </div>

                <div class="space-y-4" id="porteiros-container">
                    <!-- Accordions por rua serão injetados aqui -->
                    <p class="text-slate-400 italic text-center py-10">Carregando diretório de porteiros...</p>
                </div>
            </div>
        </main>

        <script>
            let myChart = null;
            let dashboardData = null;
            const WHATSAPP_ID = '""" + whatsapp_number + """';

            function showSection(section) {
                document.getElementById('section-performance').classList.add('hidden');
                document.getElementById('section-porteiros').classList.add('hidden');
                document.getElementById('section-' + section).classList.remove('hidden');
                document.getElementById('main-title').innerText = section === 'performance' ? 'Visão Geral' : 'Diretório de Porteiros';
                
                const btns = document.querySelectorAll('aside nav button, aside div button');
                btns.forEach(b => {
                    b.className = "flex items-center gap-3 p-2.5 rounded-lg bg-transparent text-slate-600 font-medium text-sm transition-colors hover:bg-slate-50 border border-transparent hover:border-slate-200";
                });
                
                const activeBtn = Array.from(btns).find(b => b.getAttribute('onclick').includes(section));
                if(activeBtn) {
                    activeBtn.className = "flex items-center gap-3 p-2.5 rounded-lg bg-teal-50 text-teal-700 font-semibold text-sm transition-colors border border-teal-100";
                }

                if (section === 'porteiros') renderPorteiros();
            }

            function handleSearch(query) {
                renderPorteiros(query);
            }

            function renderPorteiros(filterText = '') {
                const container = document.getElementById('porteiros-container');
                const statsEl = document.getElementById('porteiros-stats');
                
                if (!dashboardData || !dashboardData.porteiros || dashboardData.porteiros.length === 0) {
                    container.innerHTML = '<div class="card p-12 text-center bg-white border-dashed border-2 border-slate-200"><p class="text-slate-500 font-medium">Nenhum porteiro mapeado ainda.</p></div>';
                    statsEl.innerText = '0 prédios cadastrados • 0 ruas';
                    return;
                }

                const query = (filterText || '').toLowerCase().trim();
                
                // Utilitários de normalização
                const normalizeStreetLabel = (value) => {
                    let text = (value || '').trim().replace(/\s+/g, ' ');
                    if (!text) return 'Sem Rua';
                    
                    // Remove números perdidos no final do nome da rua (ex: Senador Vergueiro 35 -> Senador Vergueiro)
                    text = text.replace(/\s+\d+$/, '');

                    const upper = text.toUpperCase();
                    
                    // Normalização agressiva para ruas conhecidas com muitos erros
                    if (upper.includes('PAISANDU') || upper.includes('PAISSANDU') || upper.includes('PAYSANDU') || upper.includes('BAISSANDU') || upper.includes('PAISSÃO')) {
                        return 'Rua Paissandu';
                    }
                    if (upper.includes('VERGUEIRO') || upper.includes('BERGUEIRO')) {
                        return 'Rua Senador Vergueiro';
                    }
                    if (upper.includes('BARATA') && upper.includes('RIBEIRO')) {
                        return 'Rua Barata Ribeiro';
                    }
                    if (upper.includes('SANTA') && upper.includes('CLARA')) {
                        return 'Rua Santa Clara';
                    }
                    if (upper.includes('COPACABANA') && (upper.includes('AV') || upper.includes('AVENIDA'))) {
                        return 'Avenida Nossa Sra. de Copacabana';
                    }

                    // Padronização genérica
                    const smallWords = ['de', 'da', 'do', 'das', 'dos', 'e'];
                    return text.toLowerCase()
                        .replace(/\b(r|r\.|rua)\b/gi, 'Rua')
                        .replace(/\b(av|av\.|avenida)\b/gi, 'Avenida')
                        .replace(/\b\w/g, (m) => m.toUpperCase())
                        .split(' ')
                        .map(word => smallWords.includes(word.toLowerCase()) ? word.toLowerCase() : word)
                        .join(' ');
                };

                // Filtragem
                const filteredPorteiros = dashboardData.porteiros.filter(p => {
                    if (!query) return true;
                    const content = `${p.rua} ${p.numero} ${p.nome_porteiro} ${p.notas_predio || ''}`.toLowerCase();
                    return content.includes(query);
                });

                if (filteredPorteiros.length === 0) {
                    container.innerHTML = '<div class="card p-12 text-center bg-white"><p class="text-slate-500 font-medium">Nenhum resultado para sua busca.</p></div>';
                    return;
                }

                // Agrupamento
                const grouped = {};
                filteredPorteiros.forEach(p => {
                    const rua = normalizeStreetLabel(p.rua);
                    if (!grouped[rua]) grouped[rua] = [];
                    grouped[rua].push(p);
                });

                const sortedStreets = Object.keys(grouped).sort();
                statsEl.innerText = `${dashboardData.porteiros.length} prédios cadastrados • ${Object.keys(grouped).length} ruas`;

                container.innerHTML = '';
                
                sortedStreets.forEach((rua, idx) => {
                    const items = grouped[rua].sort((a, b) => {
                        const numA = parseInt(String(a.numero || '').replace(/\D/g, '')) || 0;
                        const numB = parseInt(String(b.numero || '').replace(/\D/g, '')) || 0;
                        return numA - numB;
                    });

                    const sectionId = `rua-${idx}`;
                    const accordion = document.createElement('div');
                    accordion.className = 'bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm transition-all hover:border-slate-300';
                    
                    let cardsHtml = '';
                    items.forEach(p => {
                        // Extração de Tags
                        const tags = [];
                        const notes = (p.notas_predio || '').toLowerCase();
                        
                        const greenWords = ['banheiro', 'bebedouro', 'recebe pacote', 'fácil', 'tranquilo', '24h', 'liberado'];
                        const yellowWords = ['troca', 'atenção', 'limite', 'horário', 'esperar'];
                        const redWords = ['não recebe', 'difícil', 'complicado', 'ruim', 'problema', 'evitar'];

                        greenWords.forEach(w => { if(notes.includes(w)) tags.push({text: w, color: 'bg-emerald-50 text-emerald-700 border-emerald-100'}); });
                        yellowWords.forEach(w => { if(notes.includes(w)) tags.push({text: w, color: 'bg-amber-50 text-amber-700 border-amber-100'}); });
                        redWords.forEach(w => { if(notes.includes(w)) tags.push({text: w, color: 'bg-rose-50 text-rose-700 border-rose-100'}); });

                        const tagsHtml = tags.map(t => `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold border uppercase tracking-tight ${t.color}">${t.text}</span>`).join('');
                        
                        // Tentativa de extrair nome do prédio das notas
                        let predioNome = 'Edifício';
                        const predioMatch = p.notas_predio ? p.notas_predio.match(/edifício\s+([^,.-]+)/i) || p.notas_predio.match(/residencial\s+([^,.-]+)/i) : null;
                        if (predioMatch) predioNome = predioMatch[0];

                        cardsHtml += `
                            <div class="bg-slate-50/50 rounded-xl p-4 border border-slate-100 flex flex-col justify-between hover:bg-white hover:border-teal-200 transition-all group">
                                <div>
                                    <div class="flex justify-between items-start mb-3">
                                        <div>
                                            <p class="text-xs font-bold text-teal-600 uppercase tracking-wider">Nº ${p.numero}</p>
                                            <h5 class="font-bold text-slate-800 leading-tight">${predioNome}</h5>
                                        </div>
                                        <div class="w-8 h-8 bg-white rounded-lg border border-slate-200 flex items-center justify-center text-slate-400 group-hover:text-teal-500 group-hover:border-teal-100 transition-colors">
                                            <i class="fa-solid fa-building text-sm"></i>
                                        </div>
                                    </div>
                                    
                                    <div class="space-y-2 mb-4">
                                        <div class="flex items-center gap-2 text-slate-600">
                                            <i class="fa-solid fa-user-tie text-xs w-4"></i>
                                            <span class="text-sm font-semibold">${p.nome_porteiro || 'Não inf.'}</span>
                                        </div>
                                        ${p.turno ? `
                                            <div class="flex items-center gap-2 text-slate-500">
                                                <i class="fa-solid fa-clock text-xs w-4"></i>
                                                <span class="text-xs font-medium">${p.turno}</span>
                                            </div>
                                        ` : ''}
                                    </div>

                                    <div class="flex flex-wrap gap-1.5 mb-4">
                                        ${tagsHtml}
                                    </div>
                                </div>

                                ${p.notas_predio ? `
                                    <details class="mt-auto border-t border-slate-100 pt-3 group/details">
                                        <summary class="list-none cursor-pointer flex items-center gap-1.5 text-xs font-bold text-slate-400 hover:text-teal-600 transition-colors">
                                            <i class="fa-solid fa-note-sticky text-[10px]"></i>
                                            VER OBSERVAÇÕES
                                            <i class="fa-solid fa-chevron-down text-[10px] ml-auto transition-transform group-open/details:rotate-180"></i>
                                        </summary>
                                        <div class="mt-2 p-3 bg-white rounded-lg border border-slate-100 shadow-inner">
                                            <p class="text-xs text-slate-600 leading-relaxed italic">"${p.notas_predio}"</p>
                                        </div>
                                    </details>
                                ` : ''}
                            </div>
                        `;
                    });

                    accordion.innerHTML = `
                        <button onclick="document.getElementById('${sectionId}').classList.toggle('hidden'); this.querySelector('.chevron').classList.toggle('rotate-180')" 
                            class="w-full px-6 py-4 flex items-center justify-between bg-white hover:bg-slate-50 transition-colors text-left">
                            <div class="flex items-center gap-3">
                                <div class="w-10 h-10 bg-teal-50 rounded-xl flex items-center justify-center text-teal-600 shadow-sm border border-teal-100">
                                    <i class="fa-solid fa-map-pin"></i>
                                </div>
                                <div>
                                    <h4 class="font-bold text-slate-800 uppercase tracking-tight">${rua}</h4>
                                    <p class="text-[10px] text-slate-400 font-bold uppercase">${items.length} PRÉDIOS CADASTRADOS</p>
                                </div>
                            </div>
                            <i class="fa-solid fa-chevron-down text-slate-300 transition-transform chevron"></i>
                        </button>
                        <div id="${sectionId}" class="px-6 pb-6 pt-2">
                            <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                                ${cardsHtml}
                            </div>
                        </div>
                    `;
                    container.appendChild(accordion);
                });
            }

            let chartGastos = null;

            async function loadDashboard(analysisId = null) {
                try {
                    let url = '/api/dashboard/' + WHATSAPP_ID;
                    if (analysisId) url += '?analysis_id=' + analysisId;
                    
                    const response = await fetch(url);
                    const data = await response.json();
                    if (data.error) throw new Error(data.error);

                    dashboardData = data;
                    const c = data.metrics.consolidado;
                    const apps = data.metrics.apps;

                    document.getElementById('txt-periodo').innerText = 'Relatório processado em: ' + new Date(data.created_at || new Date()).toLocaleDateString('pt-BR');
                    
                    const fmt = (val) => (val || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2});
                    
                    // Main Cards
                    document.getElementById('txt-bruto').innerText = 'R$ ' + fmt(c.total_ganhos);
                    document.getElementById('txt-saldo').innerText = 'R$ ' + fmt(c.saldo);
                    document.getElementById('txt-eficiencia').innerText = 'R$ ' + (c.total_ganhos / (c.km_total || 1)).toFixed(2) + '/km';
                    document.getElementById('txt-tempo').innerText = (c.total_hours || 0).toFixed(1) + 'h';
                    
                    // Sub-metrics
                    document.getElementById('txt-faturamento-avg').innerText = 'Média: R$ ' + fmt(c.avg_faturamento_per_day) + '/dia';
                    document.getElementById('txt-margem').innerText = 'Margem: ' + (c.margem_liquida || 0).toFixed(1) + '%';
                    document.getElementById('txt-ganho-hora').innerText = 'R$ ' + fmt(c.ganho_por_hora) + '/hora';
                    
                    const daysWorked = c.days_worked || 0;
                    const avgHours = (c.avg_hours_per_day || (daysWorked ? (c.total_hours || 0) / daysWorked : 0));
                    document.getElementById('txt-tempo-avg').innerText = `Média: ${avgHours.toFixed(1)}h/dia (${daysWorked} dias)`;

                    // Expense breakdown
                    document.getElementById('txt-essencial').innerText = 'R$ ' + fmt(c.gastos_essenciais);
                    document.getElementById('txt-nao-essencial').innerText = 'R$ ' + fmt(c.gastos_nao_essenciais);

                    // Wait Time
                    document.getElementById('txt-tempo-espera').innerText = (c.tempo_espera_galpao || 0).toFixed(1) + 'h';
                    const avgWait = (c.avg_wait_per_day || (daysWorked ? (c.tempo_espera_galpao || 0) / daysWorked : 0));
                    document.getElementById('txt-tempo-espera-avg').innerText = `Média: ${avgWait.toFixed(1)}h/dia`;
                    
                    const waitPercent = Math.min((c.tempo_espera_galpao / (c.total_hours || 1)) * 100, 100);
                    document.getElementById('bar-espera').style.width = waitPercent + '%';
                    
                    // Analysis Insight
                    const analysisSection = document.getElementById('txt-insight').closest('div.bg-white');
                    if (data.is_live) {
                        analysisSection.classList.add('hidden');
                    } else {
                        analysisSection.classList.remove('hidden');
                        document.getElementById('txt-insight').innerHTML = marked.parse(data.insight || "");
                    }

                    // App List Details
                    const listContainer = document.getElementById('list-apps');
                    listContainer.innerHTML = '';
                    const sortedAppNames = Object.keys(apps).filter(name => name !== 'Outros').sort((a,b) => apps[b].ganhos - apps[a].ganhos);
                    
                    sortedAppNames.forEach(name => {
                        const app = apps[name];
                        const rkm = (app.ganhos / (app.km || 1)).toFixed(2);
                        const rhora = (app.ganhos / (app.horas || 1)).toFixed(2);
                        const percent = (app.ganhos / (c.total_ganhos || 1)) * 100;
                        
                        listContainer.innerHTML += `
                            <div class="p-4 rounded-xl bg-slate-50 border border-slate-100 group hover:border-teal-200 transition-all">
                                <div class="flex justify-between items-start mb-3">
                                    <div>
                                        <p class="font-bold text-slate-800 text-sm uppercase tracking-tight">${name}</p>
                                        <p class="text-[10px] text-slate-500 font-bold uppercase">${app.km.toFixed(1)}km • ${app.horas.toFixed(1)}h</p>
                                    </div>
                                    <div class="text-right">
                                        <p class="font-bold text-teal-700 text-sm">R$ ${fmt(app.ganhos)}</p>
                                        <p class="text-[10px] text-teal-500 font-bold uppercase">${percent.toFixed(0)}% do total</p>
                                    </div>
                                </div>
                                <div class="grid grid-cols-2 gap-2 mt-4">
                                    <div class="bg-white p-2 rounded-lg border border-slate-100 text-center">
                                        <p class="text-[9px] font-bold text-slate-400 uppercase">Eficiência/KM</p>
                                        <p class="text-xs font-bold text-slate-700">R$ ${rkm}</p>
                                    </div>
                                    <div class="bg-white p-2 rounded-lg border border-slate-100 text-center">
                                        <p class="text-[9px] font-bold text-slate-400 uppercase">Eficiência/Hora</p>
                                        <p class="text-xs font-bold text-slate-700">R$ ${rhora}</p>
                                    </div>
                                </div>
                            </div>
                        `;
                    });

                    // History Sidebar
                    if (data.history) {
                        const histList = document.getElementById('history-list');
                        histList.innerHTML = '';
                        
                        const grouped = {};
                        data.history.forEach(h => {
                            const date = new Date(h.created_at);
                            const monthKey = date.toLocaleDateString('pt-BR', { month: 'short', year: 'numeric' }).toUpperCase();
                            if(!grouped[monthKey]) grouped[monthKey] = [];
                            grouped[monthKey].push(h);
                        });

                        const liveWrapper = document.createElement('div');
                        liveWrapper.className = 'mb-4';
                        liveWrapper.innerHTML = `<p class="text-[10px] font-bold text-slate-400 mb-2 px-1">AO VIVO</p>`;

                        const liveItem = document.createElement('div');
                        const liveActive = !analysisId;
                        liveItem.className = `history-item p-2.5 rounded-lg border text-left cursor-pointer flex flex-col gap-0.5 ${liveActive ? 'bg-teal-50 border-teal-200' : 'bg-white border-slate-200 hover:border-teal-300'}`;
                        liveItem.innerHTML = `
                            <span class="text-[10px] font-bold uppercase ${liveActive ? 'text-teal-600' : 'text-slate-500'}">MES ATUAL</span>
                            <span class="text-xs font-medium text-slate-700">Dashboard em tempo real</span>
                        `;
                        liveItem.onclick = () => { loadDashboard(); if(window.innerWidth < 768) window.scrollTo({top: 0, behavior: 'smooth'}); };
                        liveWrapper.appendChild(liveItem);
                        histList.appendChild(liveWrapper);

                        for(const [month, items] of Object.entries(grouped)) {
                            const wrapper = document.createElement('div');
                            wrapper.className = 'mb-4';
                            wrapper.innerHTML = `<p class="text-[10px] font-bold text-slate-400 mb-2 px-1">${month}</p>`;
                            
                            const itemsList = document.createElement('div');
                            itemsList.className = 'flex flex-col gap-1.5';
                            
                            items.forEach(h => {
                                const active = analysisId === h.id;
                                const btn = document.createElement('div');
                                btn.className = `history-item p-2.5 rounded-lg border text-left cursor-pointer flex flex-col gap-0.5 ${active ? 'bg-teal-50 border-teal-200' : 'bg-white border-slate-200 hover:border-teal-300'}`;
                                btn.innerHTML = `
                                    <span class="text-[10px] font-bold uppercase ${active ? 'text-teal-600' : 'text-slate-500'}">${h.periodo_tipo}</span>
                                    <span class="text-xs font-medium text-slate-700">${new Date(h.created_at).toLocaleDateString('pt-BR')}</span>
                                `;
                                btn.onclick = () => { loadDashboard(h.id); if(window.innerWidth < 768) window.scrollTo({top: 0, behavior: 'smooth'}); };
                                itemsList.appendChild(btn);
                            });
                            
                            wrapper.appendChild(itemsList);
                            histList.appendChild(wrapper);
                        }
                    }

                    // --- CHARTS LOGIC ---
                    
                    // 1. Expense Doughnut Chart
                    if (chartGastos) chartGastos.destroy();
                    const ctxGastos = document.getElementById('chartGastos').getContext('2d');
                    chartGastos = new Chart(ctxGastos, {
                        type: 'doughnut',
                        data: {
                            labels: ['Essenciais', 'Não Essenciais'],
                            datasets: [{
                                data: [c.gastos_essenciais, c.gastos_nao_essenciais],
                                backgroundColor: ['#0f766e', '#e11d48'],
                                borderWeight: 0,
                                cutout: '75%'
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { display: false },
                                tooltip: { cornerRadius: 8, padding: 10 }
                            }
                        }
                    });

                    // 2. Performance Stacked Bar Chart
                    const chartTitle = document.getElementById('chart-title');
                    const chartLegend = document.getElementById('chart-legend');
                    chartLegend.innerHTML = '';
                    
                    let chartDatasets = [];
                    let chartLabels = [];
                    let isStacked = false;

                    const colors = {
                        'Correios': '#0f766e',
                        'Shopee': '#f97316',
                        'Loggi': '#6366f1',
                        'Mercado Livre': '#facc15',
                        'Outros': '#94a3b8'
                    };

                    const getAppColor = (name) => colors[name] || '#64748b';

                    if (data.history && data.history.length) {
                        const refDate = new Date(data.created_at || new Date());
                        const refMonth = refDate.getMonth();
                        const refYear = refDate.getFullYear();
                        
                        const weekly = data.history
                            .filter(h => h.periodo_tipo === 'semanal')
                            .filter(h => {
                                const d = new Date(h.created_at);
                                return d.getMonth() === refMonth && d.getFullYear() === refYear;
                            })
                            .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

                        if (weekly.length) {
                            chartTitle.innerHTML = '<i class="fa-solid fa-chart-column text-teal-600"></i> Performance Semanal (Mês)';
                            chartLabels = weekly.map(h => new Date(h.created_at).toLocaleDateString('pt-BR', {day: '2-digit', month: '2-digit'}));
                            isStacked = true;
                            
                            // Coleta todos os apps presentes no histórico
                            const allApps = new Set();
                            weekly.forEach(h => {
                                if (h.metrics && h.metrics.apps) {
                                    Object.keys(h.metrics.apps).forEach(a => allApps.add(a));
                                }
                            });

                            allApps.forEach(appName => {
                                const dataPoints = weekly.map(h => (h.metrics?.apps?.[appName]?.ganhos || 0));
                                if (dataPoints.some(v => v > 0)) {
                                    chartDatasets.push({
                                        label: appName,
                                        data: dataPoints,
                                        backgroundColor: getAppColor(appName),
                                        borderRadius: 4,
                                        stack: 'performance'
                                    });
                                    
                                    // Add to legend
                                    chartLegend.innerHTML += `
                                        <div class="flex items-center gap-1.5">
                                            <div class="w-2.5 h-2.5 rounded-full" style="background-color: ${getAppColor(appName)}"></div>
                                            <span class="text-[10px] font-bold text-slate-500 uppercase">${appName}</span>
                                        </div>
                                    `;
                                }
                            });
                        }
                    }

                    // Se não houver histórico semanal ou for o dashboard live sem dados de semanas
                    if (chartDatasets.length === 0) {
                        chartTitle.innerHTML = '<i class="fa-solid fa-chart-column text-teal-600"></i> Distribuição por App (Atual)';
                        chartLabels = sortedAppNames;
                        chartDatasets = [{
                            data: sortedAppNames.map(name => apps[name].ganhos),
                            backgroundColor: sortedAppNames.map(name => getAppColor(name)),
                            borderRadius: 6
                        }];
                    }

                    if (myChart) myChart.destroy();
                    const ctx = document.getElementById('chartApps').getContext('2d');
                    myChart = new Chart(ctx, { 
                        type: 'bar', 
                        data: { 
                            labels: chartLabels, 
                            datasets: chartDatasets 
                        }, 
                        options: { 
                            responsive: true, 
                            maintainAspectRatio: false,
                            plugins: { 
                                legend: { display: false }, 
                                tooltip: { 
                                    cornerRadius: 8, 
                                    padding: 12,
                                    callbacks: {
                                        label: (context) => {
                                            let label = context.dataset.label || '';
                                            if (label) label += ': ';
                                            if (context.parsed.y !== null) {
                                                label += 'R$ ' + context.parsed.y.toLocaleString('pt-BR');
                                            }
                                            return label;
                                        }
                                    }
                                } 
                            }, 
                            scales: { 
                                y: { 
                                    stacked: isStacked,
                                    border: {display: false}, 
                                    grid: { color: '#f1f5f9', drawTicks: false }, 
                                    ticks: { font: { family: 'Space Grotesk', size: 10 }, color: '#64748b' } 
                                }, 
                                x: { 
                                    stacked: isStacked,
                                    border: {display: false}, 
                                    grid: { display: false }, 
                                    ticks: { font: { family: 'Space Grotesk', size: 10, weight: '700' }, color: '#475569' } 
                                } 
                            } 
                        } 
                    });
                } catch (e) { 
                    console.error('Dashboard Error:', e);
                    document.getElementById('txt-periodo').innerText = 'Erro ao carregar dados. Verifique a conexão.';
                }
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