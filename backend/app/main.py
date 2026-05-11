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
        
        # Agrupamento por Rua
        grouped = {}
        for p in porteiros:
            rua = p['rua'].strip().title()
            if rua not in grouped:
                grouped[rua] = []
            grouped[rua].append(p)
            
        for rua, items in grouped.items():
            res += f"\n──────────────\n"
            res += f"🏢 *{rua.upper()}*\n"
            res += f"──────────────\n"
            
            for p in items:
                turno = f" *({p['turno']})*" if p.get("turno") else ""
                res += f"📍 *N° {p['numero']}*: {p['nome_porteiro']}{turno}\n"
                if p.get("notas_predio"):
                    res += f"└─ 📓 _\"{p['notas_predio']}\"_\n"
        
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
        <title>MeiBot Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
            body { font-family: 'Inter', sans-serif; background-color: #f9fafb; overflow-x: hidden; }
            .card-gradient { background: linear-gradient(135deg, #128C7E 0%, #075E54 100%); }
            .history-item { transition: all 0.2s; }
            .history-item:active { transform: scale(0.98); }
            ::-webkit-scrollbar { width: 4px; height: 4px; }
            ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
            .tab-active { border-bottom: 3px solid #128C7E; color: #128C7E; }
        </style>
    </head>
    <body class="flex flex-col md:flex-row min-h-screen">
        <!-- Sidebar Responsiva -->
        <aside class="w-full md:w-72 bg-white border-b md:border-b-0 md:border-r border-gray-200 p-4 md:p-6 flex-shrink-0 z-50 sticky top-0 md:h-screen md:overflow-y-auto">
            <div class="flex items-center justify-between md:justify-start md:gap-3 mb-4 md:mb-10">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 bg-green-500 rounded-xl flex items-center justify-center shadow-lg shadow-green-100 text-white"> 
                        <i class="fa-solid fa-robot"></i> 
                    </div>
                    <span class="font-bold text-xl text-gray-800">MeiBot <span class="text-green-600">Pro</span></span>
                </div>
            </div>
            
            <div class="mb-8">
                <h4 class="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-4">Navegação</h4>
                <div class="flex flex-col gap-2">
                    <button onclick="showSection('performance')" class="flex items-center gap-3 p-3 rounded-xl bg-gray-50 text-gray-700 font-bold text-sm transition-all hover:bg-gray-100">
                        <i class="fa-solid fa-chart-line text-green-600"></i> Performance
                    </button>
                    <button onclick="showSection('porteiros')" class="flex items-center gap-3 p-3 rounded-xl bg-white text-gray-700 font-bold text-sm transition-all hover:bg-gray-100 border border-gray-100">
                        <i class="fa-solid fa-building-user text-blue-500"></i> Porteiros
                    </button>
                </div>
            </div>

            <h4 class="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-4">Pasta de Arquivos</h4>
            <nav id="history-list" class="flex md:flex-col gap-3 md:gap-4 overflow-x-auto md:overflow-visible pb-2 md:pb-0 snap-x"></nav>
        </aside>

        <!-- Main Content -->
        <main class="flex-grow p-4 md:p-10 space-y-6 md:space-y-8 w-full max-w-7xl mx-auto">
            <header class="flex flex-col md:flex-row justify-between items-start md:items-end border-b pb-6 gap-4">
                <div>
                    <h2 class="text-2xl md:text-3xl font-black text-gray-800 tracking-tight" id="main-title">Painel de Performance</h2>
                    <p id="txt-periodo" class="text-gray-400 text-sm font-medium">Carregando dados...</p>
                </div>
                <div class="bg-gray-100 p-3 rounded-2xl w-full md:w-auto">
                    <p class="text-[10px] text-gray-400 font-bold uppercase tracking-wider">Conta Comigo Logística</p>
                    <p class="text-xs font-bold text-gray-700 uppercase tracking-tighter">ID: """ + whatsapp_number + """</p>
                </div>
            </header>

            <!-- SECTION: PERFORMANCE -->
            <div id="section-performance" class="space-y-6 md:space-y-8">
                <!-- Cards Financeiros: Responsivos (2 colunas mobile, 6 colunas desktop) -->
                <div class="grid grid-cols-2 lg:grid-cols-6 gap-3 md:gap-4">
                    <div class="bg-white p-4 rounded-2xl shadow-sm border border-gray-100">
                        <p class="text-gray-400 text-[10px] font-bold uppercase mb-1">Bruto</p>
                        <p id="txt-bruto" class="text-base md:text-xl font-black text-gray-800 truncate">---</p>
                    </div>
                    <div class="bg-white p-4 rounded-2xl shadow-sm border border-gray-100">
                        <p class="text-red-400 text-[10px] font-bold uppercase mb-1">Essenciais</p>
                        <p id="txt-essencial" class="text-base md:text-xl font-black text-gray-800 truncate">---</p>
                    </div>
                    <div class="bg-white p-4 rounded-2xl shadow-sm border border-gray-100">
                        <p class="text-orange-400 text-[10px] font-bold uppercase mb-1 truncate">Não Essenc.</p>
                        <p id="txt-nao-essencial" class="text-base md:text-xl font-black text-gray-800 truncate">---</p>
                    </div>
                    <div class="bg-white p-3 md:p-4 rounded-2xl shadow-sm border border-gray-100 border-l-4 border-l-green-500">
                        <p class="text-green-600 text-[10px] font-bold uppercase mb-1">Líquido</p>
                        <p id="txt-saldo" class="text-base md:text-xl font-black text-green-600 truncate">---</p>
                    </div>
                    <div class="bg-white p-4 rounded-2xl shadow-sm border border-gray-100">
                        <p class="text-blue-500 text-[10px] font-bold uppercase mb-1">R$ / KM</p>
                        <p id="txt-eficiencia" class="text-base md:text-xl font-black text-blue-600 truncate">---</p>
                    </div>
                    <div class="bg-white p-4 rounded-2xl shadow-sm border border-gray-100">
                        <p class="text-purple-500 text-[10px] font-bold uppercase mb-1">Tempo</p>
                        <p id="txt-tempo" class="text-base md:text-xl font-black text-purple-600 truncate">---</p>
                    </div>
                </div>

                <!-- Gráfico e Detalhes -->
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div class="lg:col-span-2 bg-white p-6 md:p-8 rounded-[2.5rem] shadow-sm border border-gray-100 w-full overflow-hidden">
                        <h3 class="font-bold text-gray-800 text-xs md:text-sm mb-6 uppercase tracking-widest flex items-center gap-2">
                            <i class="fa-solid fa-chart-column text-green-500"></i> Faturamento por Plataforma
                        </h3>
                        <div class="relative w-full h-[200px] md:h-[250px]">
                            <canvas id="chartApps"></canvas>
                        </div>
                    </div>
                    <div class="bg-white p-6 md:p-8 rounded-[2.5rem] shadow-sm border border-gray-100 w-full">
                        <h3 class="font-bold text-gray-800 text-xs md:text-sm mb-6 uppercase tracking-widest flex items-center gap-2">
                            <i class="fa-solid fa-list-check text-blue-500"></i> Metas e Tempos
                        </h3>
                        <div id="list-apps" class="space-y-5 md:space-y-6"></div>
                    </div>
                </div>

                <!-- VISÃO DO ANALISTA: Destaque Especial -->
                <div class="card-gradient p-8 md:p-12 rounded-[2.5rem] text-white shadow-2xl relative overflow-hidden">
                    <i class="fa-solid fa-quote-left absolute top-6 left-6 text-white/5 text-8xl md:text-9xl"></i>
                    <div class="relative z-10">
                        <h3 class="text-lg md:text-xl font-bold mb-6 md:mb-8 flex items-center gap-3"> 
                            <span class="w-10 h-10 bg-white/20 rounded-full flex items-center justify-center">
                                <i class="fa-solid fa-user-tie text-white"></i> 
                            </span>
                            Visão do Analista Estratégico 
                        </h3>
                        <div id="txt-insight" class="text-white/90 leading-relaxed whitespace-pre-line text-sm md:text-lg italic font-light"></div>
                    </div>
                </div>
            </div>

            <!-- SECTION: PORTEIROS -->
            <div id="section-porteiros" class="hidden space-y-6">
                <div class="bg-white p-8 rounded-[2.5rem] shadow-sm border border-gray-100">
                    <h3 class="font-bold text-gray-800 text-sm mb-6 uppercase tracking-widest flex items-center gap-2">
                        <i class="fa-solid fa-map-location-dot text-blue-500"></i> Mapeamento de Porteiros
                    </h3>
                    <div id="porteiros-list" class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <p class="text-gray-400 italic">Carregando mapeamento...</p>
                    </div>
                </div>
            </div>
        </main>

        <script>
            let myChart = null;
            let dashboardData = null;

            function showSection(section) {
                document.getElementById('section-performance').classList.add('hidden');
                document.getElementById('section-porteiros').classList.add('hidden');
                document.getElementById('section-' + section).classList.remove('hidden');
                document.getElementById('main-title').innerText = section === 'performance' ? 'Painel de Performance' : 'Mapeamento de Porteiros';
                
                if (section === 'porteiros') renderPorteiros();
            }

            function renderPorteiros() {
                const container = document.getElementById('porteiros-list');
                if (!dashboardData || !dashboardData.porteiros || dashboardData.porteiros.length === 0) {
                    container.innerHTML = '<p class="text-gray-400 italic col-span-full">Nenhum porteiro mapeado ainda. Cadastre via WhatsApp!</p>';
                    return;
                }

                container.innerHTML = '';
                // Agrupar por endereço
                const grouped = {};
                dashboardData.porteiros.forEach(p => {
                    const addr = p.rua + ', ' + p.numero;
                    if (!grouped[addr]) grouped[addr] = [];
                    grouped[addr].push(p);
                });

                for (const addr in grouped) {
                    const card = document.createElement('div');
                    card.className = 'bg-gray-50 p-6 rounded-2xl border border-gray-100';
                    let porteirosHtml = '';
                    grouped[addr].forEach(p => {
                        porteirosHtml += `
                            <div class="mt-4 border-t border-gray-200 pt-4">
                                <p class="font-bold text-gray-800">${p.nome_porteiro} ${p.turno ? '<span class="text-[10px] bg-blue-100 text-blue-600 px-2 py-0.5 rounded-full ml-2 uppercase font-black">' + p.turno + '</span>' : ''}</p>
                                ${p.notas_predio ? '<p class="text-xs text-gray-500 mt-1 italic">"'+p.notas_predio+'"</p>' : ''}
                            </div>
                        `;
                    });
                    card.innerHTML = `
                        <div class="flex items-center gap-3 text-blue-600 mb-2">
                            <i class="fa-solid fa-location-dot"></i>
                            <span class="font-black text-xs uppercase tracking-tight">${addr}</span>
                        </div>
                        ${porteirosHtml}
                    `;
                    container.appendChild(card);
                }
            }

            async function loadDashboard(analysisId = null) {
                try {
                    let url = '/api/dashboard/""" + whatsapp_number + """';
                    if (analysisId) url += '?analysis_id=' + analysisId;
                    const response = await fetch(url);
                    const data = await response.json();
                    if (data.error) return;

                    dashboardData = data;
                    const c = data.metrics.consolidado;
                    const apps = data.metrics.apps;

                    // Header
                    document.getElementById('txt-periodo').innerText = 'Relatório de: ' + new Date(data.created_at || new Date()).toLocaleDateString('pt-BR');
                    
                    // Cards
                    document.getElementById('txt-bruto').innerText = 'R$ ' + c.total_ganhos.toLocaleString('pt-BR', {minimumFractionDigits: 2});
                    document.getElementById('txt-essencial').innerText = 'R$ ' + (c.gastos_essenciais || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2});
                    document.getElementById('txt-nao-essencial').innerText = 'R$ ' + (c.gastos_nao_essenciais || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2});
                    document.getElementById('txt-saldo').innerText = 'R$ ' + c.saldo.toLocaleString('pt-BR', {minimumFractionDigits: 2});
                    document.getElementById('txt-eficiencia').innerText = 'R$ ' + (c.total_ganhos / (c.km_total || 1)).toFixed(2);
                    document.getElementById('txt-tempo').innerText = (c.total_hours || 0).toFixed(1) + 'h';
                    document.getElementById('txt-insight').innerText = data.insight;

                    // Detalhamento de Apps
                    const listContainer = document.getElementById('list-apps');
                    listContainer.innerHTML = '';
                    const appNames = Object.keys(apps);
                    const appGanhos = [];
                    appNames.forEach(name => {
                        const app = apps[name];
                        appGanhos.push(app.ganhos);
                        const rkm = (app.ganhos / (app.km || 1)).toFixed(2);
                        const div = document.createElement('div');
                        div.className = 'border-l-4 border-green-500 pl-4 py-1';
                        div.innerHTML = `<div class="flex justify-between font-black text-sm text-gray-800"><span>${name}</span><span class="text-green-600">R$ ${app.ganhos.toFixed(2)}</span></div><div class="text-[10px] text-gray-400 uppercase font-black tracking-tight mt-1">${app.km.toFixed(1)}km • R$ ${rkm}/km • ${app.horas.toFixed(1)}h</div>`;
                        listContainer.appendChild(div);
                    });

                    // AGRUPAMENTO MENSAL NA SIDEBAR
                    if (data.history) {
                        const histList = document.getElementById('history-list');
                        histList.innerHTML = '';
                        
                        const grouped = {};
                        data.history.forEach(h => {
                            const date = new Date(h.created_at);
                            const monthKey = date.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' }).toUpperCase();
                            if(!grouped[monthKey]) grouped[monthKey] = [];
                            grouped[monthKey].push(h);
                        });

                        for(const [month, items] of Object.entries(grouped)) {
                            const monthWrapper = document.createElement('div');
                            monthWrapper.className = 'min-w-[150px] md:min-w-0 md:mb-8 flex-shrink-0 snap-start';
                            monthWrapper.innerHTML = `<h5 class="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-4 bg-gray-50 px-2 py-1 rounded-md inline-block border border-gray-100">${month}</h5>`;
                            
                            const itemsList = document.createElement('div');
                            itemsList.className = 'flex flex-col gap-2 md:pl-2 md:border-l-2 md:border-gray-100';
                            
                            items.forEach(h => {
                                const active = analysisId === h.id || (!analysisId && h.id === data.history[0]?.id);
                                const btn = document.createElement('div');
                                btn.className = `history-item p-3 rounded-2xl border shadow-sm transition-all text-left cursor-pointer ${active ? 'bg-green-600 border-green-600 text-white' : 'bg-white border-gray-100 text-gray-700'}`;
                                btn.innerHTML = `<p class="text-[10px] font-black uppercase tracking-tighter">${h.periodo_tipo}</p><p class="text-[9px] ${active ? 'text-green-100' : 'text-gray-400'} font-bold">${new Date(h.created_at).toLocaleDateString('pt-BR')}</p>`;
                                btn.onclick = () => { loadDashboard(h.id); if(window.innerWidth < 768) window.scrollTo({top: 400, behavior: 'smooth'}); };
                                itemsList.appendChild(btn);
                            });
                            
                            monthWrapper.appendChild(itemsList);
                            histList.appendChild(monthWrapper);
                        }
                    }

                    // Chart
                    if (myChart) myChart.destroy();
                    const ctx = document.getElementById('chartApps').getContext('2d');
                    myChart = new Chart(ctx, { 
                        type: 'bar', 
                        data: { labels: appNames, datasets: [{ label: 'Bruto', data: appGanhos, backgroundColor: '#128C7E', borderRadius: 12, barThickness: window.innerWidth < 768 ? 20 : 35 }] }, 
                        options: { 
                            responsive: true, maintainAspectRatio: false,
                            plugins: { legend: { display: false } }, 
                            scales: { y: { beginAtZero: true, grid: { color: '#f3f4f6', borderDash: [5, 5] }, ticks: { font: { size: 10, weight: 'bold' } } }, x: { grid: { display: false }, ticks: { font: { size: 10, weight: 'bold' } } } } 
                        } 
                    });
                } catch (e) { console.error(e); }
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
