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
        
        if "shopee" in app_name_raw:
            ev["app"] = "Shopee"
            ev["valor"] = 305.0 + float(ev.get("valor_extra") or 0)
            ev["km"] = 60.0
            ev["tipo"] = "ganho"
        
        elif "correio" in app_name_raw:
            ev["app"] = "Correios"
            ev["km"] = 20.0
            ev["tipo"] = "ganho"
            if not ev.get("valor") or ev.get("valor") == 0:
                ev["valor"] = (float(ev.get("pacotes") or 0) * 2.0) + float(ev.get("valor_extra") or 0)
            else:
                ev["valor"] = float(ev["valor"]) + float(ev.get("valor_extra") or 0)
        
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

    return "Não entendi o que você quis dizer."

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
                "created_at": analysis["created_at"],
                "history": history,
                "porteiros": porteiros
            }

    if history:
        latest = history[0]
        return {
            "user": user,
            "metrics": latest["metrics"],
            "insight": latest["insight"],
            "history": history,
            "created_at": latest["created_at"],
            "porteiros": porteiros
        }
    
    ev_week = db.get_weekly_summary(user_id)
    op_week = db.get_operations_for_period(user_id, 7)
    metrics_week = LogicService.calculate_metrics_grouped(ev_week, op_week)
    
    return {
        "user": user,
        "metrics": metrics_week,
        "insight": "Seu primeiro relatório automatizado será gerado neste sábado às 21h. Aguarde!",
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
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
            body { font-family: 'Inter', sans-serif; background-color: #f8fafc; color: #0f172a; overflow-x: hidden; }
            ::-webkit-scrollbar { width: 6px; height: 6px; }
            ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
            .history-item { transition: all 0.2s ease-in-out; }
            .history-item:hover { transform: translateY(-1px); box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); }
            .history-item:active { transform: translateY(0); }
        </style>
    </head>
    <body class="flex flex-col md:flex-row min-h-screen">
        <!-- Sidebar -->
        <aside class="w-full md:w-72 bg-white border-b md:border-b-0 md:border-r border-slate-200 p-5 md:p-6 flex-shrink-0 z-50 sticky top-0 md:h-screen md:overflow-y-auto">
            <div class="flex items-center gap-3 mb-8">
                <div class="w-10 h-10 bg-indigo-600 rounded-lg flex items-center justify-center shadow-md shadow-indigo-200 text-white"> 
                    <i class="fa-solid fa-bolt"></i> 
                </div>
                <div>
                    <h1 class="font-bold text-lg text-slate-800 leading-tight">MeiBot</h1>
                    <p class="text-xs text-slate-500 font-medium">Dashboard Analítico</p>
                </div>
            </div>
            
            <div class="mb-8">
                <p class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-3">Navegação</p>
                <div class="flex flex-col gap-1.5">
                    <button onclick="showSection('performance')" class="flex items-center gap-3 p-2.5 rounded-lg bg-indigo-50 text-indigo-700 font-semibold text-sm transition-colors border border-indigo-100">
                        <i class="fa-solid fa-chart-pie w-4"></i> Performance
                    </button>
                    <button onclick="showSection('porteiros')" class="flex items-center gap-3 p-2.5 rounded-lg bg-transparent text-slate-600 font-medium text-sm transition-colors hover:bg-slate-50 border border-transparent hover:border-slate-200">
                        <i class="fa-solid fa-map-location-dot w-4"></i> Porteiros
                    </button>
                </div>
            </div>

            <p class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-3">Histórico</p>
            <nav id="history-list" class="flex md:flex-col gap-3 md:gap-2.5 overflow-x-auto md:overflow-visible pb-2 md:pb-0 snap-x"></nav>
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
                <!-- Cards Financeiros -->
                <div class="grid grid-cols-2 lg:grid-cols-6 gap-4">
                    <div class="bg-white p-5 rounded-xl shadow-sm border border-slate-200">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-slate-500 text-xs font-semibold uppercase">Faturamento</p>
                            <i class="fa-solid fa-arrow-trend-up text-slate-300"></i>
                        </div>
                        <p id="txt-bruto" class="text-xl md:text-2xl font-bold text-slate-800">---</p>
                    </div>
                    
                    <div class="bg-white p-5 rounded-xl shadow-sm border border-slate-200">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-slate-500 text-xs font-semibold uppercase">Essenciais</p>
                            <i class="fa-solid fa-gas-pump text-slate-300"></i>
                        </div>
                        <p id="txt-essencial" class="text-xl md:text-2xl font-bold text-slate-800">---</p>
                    </div>
                    
                    <div class="bg-white p-5 rounded-xl shadow-sm border border-slate-200">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-slate-500 text-xs font-semibold uppercase">Não Essenciais</p>
                            <i class="fa-solid fa-burger text-slate-300"></i>
                        </div>
                        <p id="txt-nao-essencial" class="text-xl md:text-2xl font-bold text-orange-600">---</p>
                    </div>
                    
                    <div class="bg-white p-5 rounded-xl shadow-sm border border-indigo-200 border-t-4 border-t-indigo-600">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-indigo-600 text-xs font-bold uppercase">Saldo Líquido</p>
                            <i class="fa-solid fa-wallet text-indigo-300"></i>
                        </div>
                        <p id="txt-saldo" class="text-xl md:text-2xl font-bold text-indigo-700">---</p>
                    </div>
                    
                    <div class="bg-white p-5 rounded-xl shadow-sm border border-slate-200">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-slate-500 text-xs font-semibold uppercase">Eficiência</p>
                            <i class="fa-solid fa-gauge-high text-slate-300"></i>
                        </div>
                        <p id="txt-eficiencia" class="text-xl md:text-2xl font-bold text-slate-800">---</p>
                    </div>
                    
                    <div class="bg-white p-5 rounded-xl shadow-sm border border-slate-200">
                        <div class="flex justify-between items-start mb-2">
                            <p class="text-slate-500 text-xs font-semibold uppercase">Tempo Total</p>
                            <i class="fa-solid fa-clock text-slate-300"></i>
                        </div>
                        <p id="txt-tempo" class="text-xl md:text-2xl font-bold text-slate-800">---</p>
                    </div>
                </div>

                <!-- Gráficos e Apps -->
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div class="lg:col-span-2 bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                        <h3 class="font-semibold text-slate-800 text-sm mb-6 flex items-center gap-2">
                            <i class="fa-solid fa-chart-bar text-indigo-500"></i> Distribuição de Ganhos
                        </h3>
                        <div class="relative w-full h-[250px]">
                            <canvas id="chartApps"></canvas>
                        </div>
                    </div>
                    
                    <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                        <h3 class="font-semibold text-slate-800 text-sm mb-6 flex items-center gap-2">
                            <i class="fa-solid fa-layer-group text-indigo-500"></i> Detalhamento por App
                        </h3>
                        <div id="list-apps" class="space-y-4"></div>
                    </div>
                </div>

                <!-- Visão do Analista (Clean) -->
                <div class="bg-indigo-50 p-6 md:p-8 rounded-xl border border-indigo-100 shadow-sm relative overflow-hidden">
                    <div class="absolute -right-4 -top-4 text-indigo-100 opacity-50">
                        <i class="fa-solid fa-quote-right text-9xl"></i>
                    </div>
                    <div class="relative z-10">
                        <h3 class="text-indigo-800 font-bold text-sm uppercase tracking-wider mb-4 flex items-center gap-2"> 
                            <i class="fa-solid fa-robot"></i> Análise Estratégica
                        </h3>
                        <div id="txt-insight" class="text-slate-700 leading-relaxed whitespace-pre-line text-sm md:text-base font-medium"></div>
                    </div>
                </div>
            </div>

            <!-- SECTION: PORTEIROS -->
            <div id="section-porteiros" class="hidden space-y-6">
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-6" id="porteiros-list">
                    <p class="text-slate-400 italic">Carregando diretório de porteiros...</p>
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
                    activeBtn.className = "flex items-center gap-3 p-2.5 rounded-lg bg-indigo-50 text-indigo-700 font-semibold text-sm transition-colors border border-indigo-100";
                }

                if (section === 'porteiros') renderPorteiros();
            }

            function renderPorteiros() {
                const container = document.getElementById('porteiros-list');
                if (!dashboardData || !dashboardData.porteiros || dashboardData.porteiros.length === 0) {
                    container.innerHTML = '<div class="col-span-full bg-white p-8 rounded-xl border border-slate-200 text-center"><p class="text-slate-500">Nenhum porteiro mapeado ainda.</p></div>';
                    return;
                }

                container.innerHTML = '';
                const grouped = {};
                dashboardData.porteiros.forEach(p => {
                    let rua = (p.rua || "Sem Rua").trim().toUpperCase();
                    if (rua.includes("PAISANDU") || rua.includes("PAISSANDU")) rua = "PAISSANDU";
                    if (!grouped[rua]) grouped[rua] = [];
                    grouped[rua].push(p);
                });

                Object.keys(grouped).sort().forEach(rua => {
                    const streetCard = document.createElement('div');
                    streetCard.className = 'bg-white p-6 rounded-xl shadow-sm border border-slate-200 h-fit';
                    
                    const items = grouped[rua].sort((a, b) => {
                        return (parseInt(a.numero.replace(/\\D/g, '')) || 0) - (parseInt(b.numero.replace(/\\D/g, '')) || 0);
                    });

                    let porteirosHtml = '';
                    items.forEach(p => {
                        porteirosHtml += `
                            <div class="py-3 border-b border-slate-100 last:border-0">
                                <div class="flex items-start justify-between">
                                    <div>
                                        <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">N° ${p.numero}</p>
                                        <p class="font-semibold text-slate-800 text-sm">${p.nome_porteiro} ${p.turno ? '<span class="text-[9px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded ml-1 uppercase font-bold">' + p.turno + '</span>' : ''}</p>
                                    </div>
                                </div>
                                ${p.notas_predio ? `
                                    <div class="mt-2 bg-slate-50 p-2.5 rounded-lg border border-slate-100">
                                        <p class="text-xs text-slate-600 italic">"${p.notas_predio}"</p>
                                    </div>
                                ` : ''}
                            </div>
                        `;
                    });

                    streetCard.innerHTML = `
                        <div class="flex items-center gap-3 mb-4 pb-4 border-b border-slate-100">
                            <div class="w-8 h-8 bg-indigo-50 rounded-lg flex items-center justify-center text-indigo-600">
                                <i class="fa-solid fa-map-pin"></i>
                            </div>
                            <div>
                                <h4 class="font-bold text-sm text-slate-800 uppercase tracking-tight">${rua}</h4>
                                <p class="text-[10px] text-slate-500 font-medium">${items.length} edifício(s)</p>
                            </div>
                        </div>
                        <div class="space-y-1">
                            ${porteirosHtml}
                        </div>
                    `;
                    container.appendChild(streetCard);
                });
            }

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
                    document.getElementById('txt-bruto').innerText = 'R$ ' + fmt(c.total_ganhos);
                    document.getElementById('txt-essencial').innerText = 'R$ ' + fmt(c.gastos_essenciais);
                    document.getElementById('txt-nao-essencial').innerText = 'R$ ' + fmt(c.gastos_nao_essenciais);
                    document.getElementById('txt-saldo').innerText = 'R$ ' + fmt(c.saldo);
                    document.getElementById('txt-eficiencia').innerText = 'R$ ' + (c.total_ganhos / (c.km_total || 1)).toFixed(2) + '/km';
                    document.getElementById('txt-tempo').innerText = (c.total_hours || 0).toFixed(1) + 'h';
                    document.getElementById('txt-insight').innerText = data.insight;

                    const listContainer = document.getElementById('list-apps');
                    listContainer.innerHTML = '';
                    const appNames = Object.keys(apps);
                    const appGanhos = [];
                    appNames.forEach(name => {
                        const app = apps[name];
                        appGanhos.push(app.ganhos);
                        const rkm = (app.ganhos / (app.km || 1)).toFixed(2);
                        listContainer.innerHTML += `
                            <div class="flex items-center justify-between p-3 rounded-lg bg-slate-50 border border-slate-100">
                                <div>
                                    <p class="font-semibold text-slate-800 text-sm">${name}</p>
                                    <p class="text-[10px] text-slate-500 font-medium">${app.km.toFixed(1)}km • ${app.horas.toFixed(1)}h</p>
                                </div>
                                <div class="text-right">
                                    <p class="font-bold text-indigo-600 text-sm">R$ ${app.ganhos.toFixed(2)}</p>
                                    <p class="text-[10px] text-slate-400 font-medium">R$ ${rkm}/km</p>
                                </div>
                            </div>
                        `;
                    });

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

                        for(const [month, items] of Object.entries(grouped)) {
                            const wrapper = document.createElement('div');
                            wrapper.className = 'mb-4';
                            wrapper.innerHTML = `<p class="text-[10px] font-bold text-slate-400 mb-2 px-1">${month}</p>`;
                            
                            const itemsList = document.createElement('div');
                            itemsList.className = 'flex flex-col gap-1.5';
                            
                            items.forEach(h => {
                                const active = analysisId === h.id || (!analysisId && h.id === data.history[0]?.id);
                                const btn = document.createElement('div');
                                btn.className = `history-item p-2.5 rounded-lg border text-left cursor-pointer flex flex-col gap-0.5 ${active ? 'bg-indigo-50 border-indigo-200' : 'bg-white border-slate-200 hover:border-indigo-300'}`;
                                btn.innerHTML = `
                                    <span class="text-[10px] font-bold uppercase ${active ? 'text-indigo-600' : 'text-slate-500'}">${h.periodo_tipo}</span>
                                    <span class="text-xs font-medium text-slate-700">${new Date(h.created_at).toLocaleDateString('pt-BR')}</span>
                                `;
                                btn.onclick = () => { loadDashboard(h.id); if(window.innerWidth < 768) window.scrollTo({top: 0, behavior: 'smooth'}); };
                                itemsList.appendChild(btn);
                            });
                            
                            wrapper.appendChild(itemsList);
                            histList.appendChild(wrapper);
                        }
                    }

                    if (myChart) myChart.destroy();
                    const ctx = document.getElementById('chartApps').getContext('2d');
                    myChart = new Chart(ctx, { 
                        type: 'bar', 
                        data: { 
                            labels: appNames, 
                            datasets: [{ 
                                data: appGanhos, 
                                backgroundColor: '#4f46e5',
                                borderRadius: 6,
                                barThickness: window.innerWidth < 768 ? 24 : 40 
                            }] 
                        }, 
                        options: { 
                            responsive: true, 
                            maintainAspectRatio: false,
                            plugins: { legend: { display: false }, tooltip: { cornerRadius: 8, padding: 12 } }, 
                            scales: { 
                                y: { border: {display: false}, grid: { color: '#f1f5f9', drawTicks: false }, ticks: { font: { family: 'Inter', size: 11 }, color: '#64748b' } }, 
                                x: { border: {display: false}, grid: { display: false }, ticks: { font: { family: 'Inter', size: 11, weight: '500' }, color: '#475569' } } 
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