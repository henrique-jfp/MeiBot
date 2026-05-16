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

# Lock management
user_locks = {}
def get_user_lock(user_id):
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

# Business Logic Handlers
def override_data_ref_from_text(content: str, data_ref: str):
    text = (content or "").lower()
    today = datetime.date.today()
    if "anteontem" in text: return (today - datetime.timedelta(days=2)).isoformat()
    if "ontem" in text: return (today - datetime.timedelta(days=1)).isoformat()
    if "hoje" in text: return today.isoformat()
    return data_ref

async def process_interpreted_data(user, interpreted):
    intencao = interpreted.get("intencao")
    user_id = user["id"]
    whatsapp = user["whatsapp_number"]
    data_ref = interpreted.get("data_referencia")
    if data_ref == "null": data_ref = None
    eventos_brutos = interpreted.get("eventos", [])
    if data_ref: active_op = db.get_or_create_operation_by_date(user_id, data_ref)
    else:
        active_op = db.get_active_operation(user_id)
        if not active_op and len(eventos_brutos) > 0: active_op = db.start_operation(user_id)
    eventos_processados = []
    for ev in eventos_brutos:
        app_name_raw = str(ev.get("app") or "").lower()
        if not app_name_raw or app_name_raw == "none":
            if float(ev.get("pacotes") or 0) > 0: ev["app"] = "Correios"
        if "shopee" in str(ev.get("app")).lower():
            ev.update({"app": "Shopee", "valor": 305.0 + float(ev.get("valor_extra", 0)), "km": 60.0, "tipo": "ganho"})
        elif "correio" in str(ev.get("app")).lower():
            v, p = float(ev.get("valor", 0)), float(ev.get("pacotes", 0))
            valor_calc = (p * 2.0) if (v == 0 or v == p) else v
            ev.update({"app": "Correios", "km": 20.0, "tipo": "ganho", "valor": valor_calc + float(ev.get("valor_extra", 0))})
        if active_op:
            h_chegada = ev.get("hora_chegada_galpao")
            h_saida_galpao = ev.get("hora_saida_galpao")
            h_inicio_rota = ev.get("hora_inicio_rota")
            h_fim_espera = h_saida_galpao or h_inicio_rota
            if h_chegada and h_fim_espera:
                wait_event = {"tipo": "registro", "sub_tipo": "espera_galpao", "hora_inicio": h_chegada, "hora_fim": h_fim_espera, "descricao": "Espera no galpao"}
                if data_ref: wait_event["data_referencia"] = data_ref
                db.add_event(user_id, active_op["id"], wait_event)
                eventos_processados.append(wait_event)

            if data_ref: ev["data_referencia"] = data_ref
            db.add_event(user_id, active_op["id"], ev)
            eventos_processados.append(ev)
    if intencao == "registro": return LogicService.format_events_confirmation(eventos_processados, "DADOS REGISTRADOS", data_ref)
    if intencao == "pedir_link_dashboard": return f"📊 Dashboard: https://meibot.henriquedejesus.dev/dashboard/{whatsapp}"
    return "Processado."

# API Endpoints
@app.post("/webhook")
async def handle_webhook(request: Request):
    try:
        data = await request.json()
        whatsapp_number = data.get("from")
        user = db.get_user_by_whatsapp(whatsapp_number)
        if not user: user = db.create_user(whatsapp_number)
        lock = get_user_lock(user["id"])
        async with lock:
            if data.get("type") == "text":
                interpreted = await ai.interpret_message(data.get("content"))
                interpreted["data_referencia"] = override_data_ref_from_text(data.get("content"), interpreted.get("data_referencia"))
                response_text = await process_interpreted_data(user, interpreted)
            else: response_text = "Tipo de mensagem não suportado ainda."
        return {"reply": response_text}
    except Exception as e:
        traceback.print_exc()
        return {"reply": "⚠️ Tive uma instabilidade. Tente de novo."}

@app.get("/api/dashboard/{whatsapp_number}")
async def get_dashboard_data(whatsapp_number: str, analysis_id: str = None):
    user = db.get_user_by_whatsapp(whatsapp_number)
    if not user: return JSONResponse({"error": "User not found"}, status_code=404)
    user_id = user["id"]
    porteiros = db.get_all_porteiros(user_id)
    history = db.get_analysis_history(user_id, limit=30)

    def _calc_period_range(analysis):
        metrics = analysis.get("metrics") or {}
        start_iso = metrics.get("period_start")
        end_iso = metrics.get("period_end")
        if start_iso and end_iso:
            try:
                return datetime.date.fromisoformat(start_iso), datetime.date.fromisoformat(end_iso)
            except Exception:
                pass

        created_at = analysis.get("created_at")
        periodo_tipo = analysis.get("periodo_tipo")
        if not created_at or not periodo_tipo:
            return None, None
        try:
            created_dt = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            return None, None
        if periodo_tipo == "semanal":
            day = created_dt.weekday()
            start = (created_dt - datetime.timedelta(days=day)).date()
            end = start + datetime.timedelta(days=6)
            return start, end
        if periodo_tipo == "mensal":
            start = created_dt.replace(day=1).date()
            end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
            return start, end
        return None, None
    if analysis_id:
        res = db.supabase.table("historico_analises").select("*").eq("id", analysis_id).execute()
        if res.data:
            analysis = res.data[0]
            start_date, end_date = _calc_period_range(analysis)
            daily_list = []
            if start_date and end_date:
                start_iso = start_date.isoformat()
                end_iso = (end_date + datetime.timedelta(days=1)).isoformat()
                ev_hist = db.supabase.table("eventos").select("*")\
                    .eq("user_id", user_id)\
                    .gte("timestamp", start_iso)\
                    .lt("timestamp", end_iso)\
                    .execute().data
                daily_perf = {ev["timestamp"].split("T")[0]: 0 for ev in ev_hist if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]}
                for ev in ev_hist:
                    if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]:
                        daily_perf[ev["timestamp"].split("T")[0]] += float(ev.get("valor", 0))
                daily_list = sorted([{"date": d, "ganho": g} for d, g in daily_perf.items()], key=lambda x: x["date"])

            return {"user": user, "metrics": analysis["metrics"], "insight": analysis["insight"], "is_live": False, "created_at": analysis["created_at"], "periodo_tipo": analysis.get("periodo_tipo"), "daily_performance": daily_list, "history": history, "porteiros": porteiros}
    today = datetime.date.today()
    start_iso, end_iso = (today.replace(day=1).isoformat(), (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1).isoformat())
    ev_live = db.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", start_iso + "T00:00:00Z").lt("timestamp", end_iso + "T00:00:00Z").execute().data
    op_live = db.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).gte("data", start_iso).lt("data", end_iso).execute().data
    metrics_live = LogicService.calculate_metrics_grouped(ev_live, op_live)
    daily_perf = {ev["timestamp"].split("T")[0]: 0 for ev in ev_live if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]}
    for ev in ev_live:
        if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]: daily_perf[ev["timestamp"].split("T")[0]] += float(ev.get("valor", 0))
    daily_list = sorted([{"date": d, "ganho": g} for d, g in daily_perf.items()], key=lambda x: x['date'])
    return {"user": user, "metrics": metrics_live, "daily_performance": daily_list, "is_live": True, "history": history, "created_at": datetime.datetime.now().isoformat(), "periodo_tipo": None, "porteiros": porteiros}

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
            body { font-family: 'Space Grotesk', sans-serif; background-color: #f8fafc; color: #0f172a; overflow-x: hidden; }
            .card { background-color: white; border-radius: 1rem; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05); }
            .tooltip-container { position: relative; display: inline-flex; align-items: center; gap: 4px; }
            .tooltip { display: none; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); margin-bottom: 8px; background-color: #1e293b; color: white; padding: 10px; border-radius: 8px; font-size: 11px; width: 240px; text-align: center; z-index: 100; font-weight: 500; pointer-events: none; }
            .tooltip-container:hover .tooltip { display: block; }
            .history-item { transition: all 0.2s; }
        </style>
    </head>
    <body class="flex flex-col lg:flex-row min-h-screen">
        <aside class="w-full lg:w-80 bg-white/95 backdrop-blur border-b lg:border-r border-slate-200 p-6 flex-shrink-0 z-50 sticky top-0 lg:h-screen lg:overflow-y-auto">
            <div class="flex items-center gap-3 mb-8"><div class="w-10 h-10 bg-teal-600 rounded-lg flex items-center justify-center text-white shadow-md"><i class="fa-solid fa-bolt"></i></div><div><h1 class="font-bold text-lg">MeiBot</h1><p class="text-xs text-slate-500 font-medium">Dashboard Analítico</p></div></div>
            <div class="mb-6"><p class="text-[11px] font-bold text-slate-400 uppercase mb-3">Navegação</p><div class="flex flex-row lg:flex-col gap-2"><button id="btn-nav-performance" onclick="showSection('performance')" class="flex items-center gap-3 p-2.5 rounded-lg bg-teal-50 text-teal-700 font-semibold text-sm border border-teal-100 w-full text-left"><i class="fa-solid fa-chart-pie w-4"></i> Performance</button><button id="btn-nav-porteiros" onclick="showSection('porteiros')" class="flex items-center gap-3 p-2.5 rounded-lg bg-transparent text-slate-600 font-medium text-sm hover:bg-slate-50 w-full text-left"><i class="fa-solid fa-map-location-dot w-4"></i> Porteiros</button></div></div>
            <p class="text-[11px] font-bold text-slate-400 uppercase mb-3">Histórico</p><nav id="history-list" class="space-y-2"></nav>
        </aside>

        <main class="flex-grow p-5 md:p-8 space-y-6 w-full max-w-7xl mx-auto">
            <header class="border-b border-slate-200 pb-5"><h2 class="text-2xl md:text-3xl font-bold" id="main-title">Visão Geral</h2><p id="txt-periodo" class="text-slate-500 text-sm mt-1">Carregando...</p></header>

            <div id="section-performance" class="space-y-6">
                <!-- METRICS GRID -->
                <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div class="card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase">Faturamento Bruto</p><p id="txt-bruto" class="text-2xl font-bold">R$ 0,00</p></div>
                    <div class="card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase">Saldo Líquido</p><p id="txt-saldo" class="text-2xl font-bold text-teal-700">R$ 0,00</p></div>
                    <div class="card p-5"><div class="tooltip-container"><p class="text-slate-500 text-[10px] font-bold uppercase">Saldo c/ Provisão</p><i class="fa-solid fa-circle-info text-[10px] text-slate-300"></i><span class="tooltip">Seu saldo líquido menos R$ 0,20 por KM rodado para cobrir custos de manutenção futuros.</span></div><p id="txt-saldo-provisao" class="text-2xl font-bold text-sky-700">R$ 0,00</p></div>
                    <div class="card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase">KM Total</p><p id="txt-km-total" class="text-2xl font-bold">0 km</p></div>
                    <div class="card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase">Pacotes Entregues</p><p id="txt-pacotes-total" class="text-2xl font-bold">0</p></div>
                    <div class="card p-5"><div class="tooltip-container"><p class="text-slate-500 text-[10px] font-bold uppercase">Pacotes / Hora (Rua)</p><i class="fa-solid fa-circle-info text-[10px] text-slate-300"></i><span class="tooltip">Quantos pacotes você entrega por hora efetivamente na rua, descontando o tempo de espera no galpão.</span></div><p id="txt-pacotes-hora-rua" class="text-2xl font-bold">0/h</p></div>
                    <div class="card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase">Eficiência (R$/KM)</p><p id="txt-eficiencia" class="text-2xl font-bold">R$ 0,00</p></div>
                    <div class="card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase">Eficiência (R$/Hora)</p><p id="txt-ganho-hora" class="text-2xl font-bold">R$ 0,00</p></div>
                    <div class="card p-5"><div class="tooltip-container"><p class="text-slate-500 text-[10px] font-bold uppercase">Eficiência na Rua</p><i class="fa-solid fa-circle-info text-[10px] text-slate-300"></i><span class="tooltip">Seu faturamento bruto por hora em rota, uma medida real de produtividade.</span></div><p id="txt-ganho-hora-rua" class="text-2xl font-bold text-violet-700">R$ 0,00/h</p></div>
                </div>

                <!-- CHARTS & DETAILS -->
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div id="daily-chart-container" class="lg:col-span-2 card p-6"><h3 class="font-bold text-sm mb-6 uppercase">Performance Diária</h3><div class="h-[300px]"><canvas id="chartDaily"></canvas></div></div>
                    <div id="apps-chart-container" class="lg:col-span-2 card p-6" style="display:none;"><h3 class="font-bold text-sm mb-6 uppercase">Performance por Período</h3><div class="h-[300px]"><canvas id="chartApps"></canvas></div></div>
                    <div class="card p-6 flex flex-col"><h3 class="font-bold text-sm mb-6 uppercase">Distribuição de Gastos</h3><div class="h-[200px] mb-6"><canvas id="chartGastos"></canvas></div><div class="space-y-2 text-[10px] font-bold uppercase"><div class="flex justify-between"><span>Essenciais</span><span id="txt-essencial">R$ 0,00</span></div><div class="flex justify-between text-rose-600"><span>Não Essenciais</span><span id="txt-nao-essencial">R$ 0,00</span></div></div></div>
                </div>
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div class="lg:col-span-2 card p-6"><h3 class="font-bold text-sm mb-6 uppercase">Detalhamento por App</h3><div id="list-apps" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div></div>
                    <div class="card p-6 bg-amber-50/30 border-amber-100"><h3 class="font-bold text-amber-800 text-sm mb-4 uppercase">Eficiência de Galpão</h3><div class="flex items-end gap-2 mb-2"><p id="txt-tempo-espera" class="text-3xl font-bold text-amber-700">0h</p><p class="text-xs text-amber-500 font-bold mb-1 uppercase">Espera</p></div><div class="w-full bg-amber-100 rounded-full h-2 mb-4"><div id="bar-espera" class="bg-amber-500 h-full w-0"></div></div><p id="txt-tempo-total" class="text-[10px] text-slate-500">Tempo Total: 0h</p></div>
                </div>
                <div id="insight-section" class="card hidden"><div class="bg-teal-600 px-6 py-3 text-white font-bold text-sm uppercase">Análise da IA</div><div class="p-6 prose prose-sm max-w-none" id="txt-insight"></div></div>
            </div>
            <div id="section-porteiros" class="hidden space-y-6">
                <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
                    <div>
                        <h3 class="text-xl font-bold text-slate-800 flex items-center gap-2">
                            <i class="fa-solid fa-map-location-dot text-teal-600"></i> Mapeamento de Porteiros
                        </h3>
                        <p id="porteiros-stats" class="text-slate-500 text-sm mt-1 font-medium">Carregando estatisticas...</p>
                    </div>
                    <div class="relative w-full md:w-96 group">
                        <div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                            <i class="fa-solid fa-magnifying-glass text-slate-400 group-focus-within:text-teal-600 transition-colors"></i>
                        </div>
                        <input type="text" id="search-porteiros" oninput="handleSearch(this.value)"
                            class="block w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 focus:bg-white transition-all"
                            placeholder="Buscar predio, rua ou porteiro...">
                    </div>
                </div>

                <div class="space-y-4" id="porteiros-container">
                    <p class="text-slate-400 italic text-center py-10">Carregando diretorio de porteiros...</p>
                </div>
            </div>
        </main>

        <script>
            let dailyChart, appsChart, chartGastos, dashboardData;
            const WHATSAPP_ID = '""" + whatsapp_number + """';
            const fmt = (v, p=2) => (v || 0).toLocaleString('pt-BR', {minimumFractionDigits: p});

            function showSection(s) {
                document.getElementById('section-performance').classList.toggle('hidden', s !== 'performance');
                document.getElementById('section-porteiros').classList.toggle('hidden', s !== 'porteiros');
                document.getElementById('main-title').innerText = s === 'performance' ? 'Visão Geral' : 'Diretório de Porteiros';
                if (s === 'porteiros') renderPorteiros();
            }

            function handleSearch(query) {
                renderPorteiros(query);
            }

            function renderPorteiros(filterText = '') {
                const container = document.getElementById('porteiros-container');
                const statsEl = document.getElementById('porteiros-stats');

                if (!dashboardData || !dashboardData.porteiros || dashboardData.porteiros.length === 0) {
                    container.innerHTML = '<div class="card p-12 text-center bg-white border-dashed border-2 border-slate-200"><p class="text-slate-500 font-medium">Nenhum porteiro mapeado ainda.</p></div>';
                    statsEl.innerText = '0 predios cadastrados - 0 ruas';
                    return;
                }

                const query = (filterText || '').toLowerCase().trim();

                const normalizeStreetLabel = (value) => {
                    let text = (value || '').trim().replace(/\s+/g, ' ');
                    if (!text) return 'Sem Rua';

                    text = text.replace(/\s+\d+$/, '');

                    const upper = text.toUpperCase();
                    if (upper.includes('PAISANDU') || upper.includes('PAISSANDU') || upper.includes('PAYSANDU') || upper.includes('BAISSANDU') || upper.includes('PAISSAO')) {
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

                    const smallWords = ['de', 'da', 'do', 'das', 'dos', 'e'];
                    return text.toLowerCase()
                        .replace(/\b(r|r\.|rua)\b/gi, 'Rua')
                        .replace(/\b(av|av\.|avenida)\b/gi, 'Avenida')
                        .replace(/\b\w/g, (m) => m.toUpperCase())
                        .split(' ')
                        .map(word => smallWords.includes(word.toLowerCase()) ? word.toLowerCase() : word)
                        .join(' ');
                };

                const filteredPorteiros = dashboardData.porteiros.filter(p => {
                    if (!query) return true;
                    const content = `${p.rua} ${p.numero} ${p.nome_porteiro} ${p.notas_predio || ''}`.toLowerCase();
                    return content.includes(query);
                });

                if (filteredPorteiros.length === 0) {
                    container.innerHTML = '<div class="card p-12 text-center bg-white"><p class="text-slate-500 font-medium">Nenhum resultado para sua busca.</p></div>';
                    return;
                }

                const grouped = {};
                filteredPorteiros.forEach(p => {
                    const rua = normalizeStreetLabel(p.rua);
                    if (!grouped[rua]) grouped[rua] = [];
                    grouped[rua].push(p);
                });

                const sortedStreets = Object.keys(grouped).sort();
                statsEl.innerText = `${dashboardData.porteiros.length} predios cadastrados - ${Object.keys(grouped).length} ruas`;

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
                        const tags = [];
                        const notes = (p.notas_predio || '').toLowerCase();

                        const greenWords = ['banheiro', 'bebedouro', 'recebe pacote', 'facil', 'tranquilo', '24h', 'liberado'];
                        const yellowWords = ['troca', 'atencao', 'limite', 'horario', 'esperar'];
                        const redWords = ['nao recebe', 'dificil', 'complicado', 'ruim', 'problema', 'evitar'];

                        greenWords.forEach(w => { if (notes.includes(w)) tags.push({ text: w, color: 'bg-emerald-50 text-emerald-700 border-emerald-100' }); });
                        yellowWords.forEach(w => { if (notes.includes(w)) tags.push({ text: w, color: 'bg-amber-50 text-amber-700 border-amber-100' }); });
                        redWords.forEach(w => { if (notes.includes(w)) tags.push({ text: w, color: 'bg-rose-50 text-rose-700 border-rose-100' }); });

                        const tagsHtml = tags.map(t => `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold border uppercase tracking-tight ${t.color}">${t.text}</span>`).join('');

                        let predioNome = 'Edificio';
                        const predioMatch = p.notas_predio ? p.notas_predio.match(/edificio\s+([^,.-]+)/i) || p.notas_predio.match(/residencial\s+([^,.-]+)/i) : null;
                        if (predioMatch) predioNome = predioMatch[0];

                        cardsHtml += `
                            <div class="bg-slate-50/50 rounded-xl p-4 border border-slate-100 flex flex-col justify-between hover:bg-white hover:border-teal-200 transition-all group">
                                <div>
                                    <div class="flex justify-between items-start mb-3">
                                        <div>
                                            <p class="text-xs font-bold text-teal-600 uppercase tracking-wider">N. ${p.numero || '-'}</p>
                                            <h5 class="font-bold text-slate-800 leading-tight">${predioNome}</h5>
                                        </div>
                                        <div class="w-8 h-8 bg-white rounded-lg border border-slate-200 flex items-center justify-center text-slate-400 group-hover:text-teal-500 group-hover:border-teal-100 transition-colors">
                                            <i class="fa-solid fa-building text-sm"></i>
                                        </div>
                                    </div>

                                    <div class="space-y-2 mb-4">
                                        <div class="flex items-center gap-2 text-slate-600">
                                            <i class="fa-solid fa-user-tie text-xs w-4"></i>
                                            <span class="text-sm font-semibold">${p.nome_porteiro || 'Nao informado'}</span>
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
                                            VER OBSERVACOES
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
                                    <p class="text-[10px] text-slate-400 font-bold uppercase">${items.length} PREDIOS CADASTRADOS</p>
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

            function formatPeriodRange(data) {
                const metrics = data && data.metrics ? data.metrics : {};
                if (metrics.period_label) return metrics.period_label;
                const createdAt = data && data.created_at ? new Date(data.created_at) : null;
                if (!createdAt || Number.isNaN(createdAt.getTime())) return null;
                const tipo = data.periodo_tipo;
                if (tipo === 'semanal') {
                    const day = (createdAt.getDay() + 6) % 7;
                    const start = new Date(createdAt);
                    start.setDate(createdAt.getDate() - day);
                    const end = new Date(start);
                    end.setDate(start.getDate() + 6);
                    const startStr = start.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    const endStr = end.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    return `${startStr} a ${endStr}`;
                }
                if (tipo === 'mensal') {
                    const start = new Date(createdAt.getFullYear(), createdAt.getMonth(), 1);
                    const end = new Date(createdAt.getFullYear(), createdAt.getMonth() + 1, 0);
                    const startStr = start.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    const endStr = end.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    return `${startStr} a ${endStr}`;
                }
                return createdAt.toLocaleDateString('pt-BR');
            }

            async function loadDashboard(aid = null) {
                try {
                    const res = await fetch(aid ? `/api/dashboard/${WHATSAPP_ID}?analysis_id=${aid}` : `/api/dashboard/${WHATSAPP_ID}`);
                    const data = await res.json(); dashboardData = data;
                    const c = data.metrics.consolidado, apps = data.metrics.apps;
                    
                    // Populate Header
                    const periodo = data.is_live ? 'Dados acumulados do mes' : (formatPeriodRange(data) || `Analise de ${new Date(data.created_at).toLocaleDateString('pt-BR')}`);
                    document.getElementById('txt-periodo').innerText = periodo;
                    
                    // Populate Metrics Grid
                    document.getElementById('txt-bruto').innerText = 'R$ ' + fmt(c.total_ganhos);
                    document.getElementById('txt-saldo').innerText = 'R$ ' + fmt(c.saldo);
                    document.getElementById('txt-saldo-provisao').innerText = 'R$ ' + fmt(c.saldo_com_provisao);
                    document.getElementById('txt-km-total').innerText = fmt(c.km_total, 1) + ' km';
                    document.getElementById('txt-pacotes-total').innerText = fmt(c.total_pacotes, 0);
                    document.getElementById('txt-pacotes-hora-rua').innerText = fmt(c.pacotes_por_hora_rua, 1) + '/h';
                    document.getElementById('txt-eficiencia').innerText = 'R$ ' + fmt(c.total_ganhos / (c.km_total || 1));
                    document.getElementById('txt-ganho-hora').innerText = 'R$ ' + fmt(c.ganho_por_hora);
                    document.getElementById('txt-ganho-hora-rua').innerText = 'R$ ' + fmt(c.ganho_por_hora_rua);
                    
                    // Populate Details
                    document.getElementById('txt-essencial').innerText = 'R$ ' + fmt(c.gastos_essenciais);
                    document.getElementById('txt-nao-essencial').innerText = 'R$ ' + fmt(c.gastos_nao_essenciais);
                    document.getElementById('txt-tempo-espera').innerText = fmt(c.tempo_espera_galpao, 1) + 'h';
                    document.getElementById('txt-tempo-total').innerText = 'Tempo Total: ' + fmt(c.total_hours, 1) + 'h';
                    document.getElementById('bar-espera').style.width = Math.min((c.tempo_espera_galpao / (c.total_hours || 1)) * 100, 100) + '%';
                    
                    // AI Insight
                    const ins = document.getElementById('insight-section');
                    if (!data.is_live) {
                        ins.classList.remove('hidden');
                        if (data.insight) {
                            document.getElementById('txt-insight').innerHTML = marked.parse(data.insight);
                        } else {
                            document.getElementById('txt-insight').innerHTML = '<p>Analise indisponivel para este periodo. Reprocese para gerar.</p>';
                        }
                    } else { ins.classList.add('hidden'); }
                    
                    // App Details - Rich version
                    const list = document.getElementById('list-apps'); list.innerHTML = '';
                    Object.keys(apps).filter(n => apps[n].ganhos > 0).sort((a,b) => apps[b].ganhos - apps[a].ganhos).forEach(name => {
                        const app = apps[name];
                        const rkm = (app.ganhos / (app.km || 1));
                        const rhora = (app.ganhos / (app.horas || 1));
                        const percent = (app.ganhos / (c.total_ganhos || 1)) * 100;
                        list.innerHTML += `
                            <div class="p-4 rounded-xl bg-slate-50 border border-slate-100 group hover:border-teal-200 transition-all shadow-sm">
                                <div class="flex justify-between items-start mb-3">
                                    <div><p class="font-bold text-slate-800 text-sm uppercase">${name}</p><p class="text-[10px] text-slate-500 font-bold uppercase">${fmt(app.km,1)}km • ${fmt(app.horas,1)}h</p></div>
                                    <div class="text-right"><p class="font-bold text-teal-700 text-sm">R$ ${fmt(app.ganhos)}</p><p class="text-[10px] text-teal-500 font-bold uppercase">${fmt(percent,0)}% do total</p></div>
                                </div>
                                <div class="grid grid-cols-2 gap-2 mt-4">
                                    <div class="bg-white p-2 rounded-lg border text-center shadow-inner"><p class="text-[9px] font-bold text-slate-400 uppercase">R$/KM</p><p class="text-xs font-bold">R$ ${fmt(rkm)}</p></div>
                                    <div class="bg-white p-2 rounded-lg border text-center shadow-inner"><p class="text-[9px] font-bold text-slate-400 uppercase">R$/Hora</p><p class="text-xs font-bold">R$ ${fmt(rhora)}</p></div>
                                </div>
                            </div>`;
                    });

                    // Charts
                    const dailyContainer = document.getElementById('daily-chart-container');
                    const appsContainer = document.getElementById('apps-chart-container');
                    const dailyPerf = Array.isArray(data.daily_performance) ? data.daily_performance : [];
                    if (dailyPerf.length > 0) {
                        dailyContainer.style.display = '';
                        appsContainer.style.display = 'none';
                        const labels = dailyPerf.map((d) => {
                            const dt = new Date(d.date);
                            return Number.isNaN(dt.getTime()) ? d.date : dt.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                        });
                        const values = dailyPerf.map((d) => d.ganho || 0);
                        if (dailyChart) dailyChart.destroy();
                        dailyChart = new Chart(document.getElementById('chartDaily').getContext('2d'), {
                            type: 'line',
                            data: { labels: labels, datasets: [{ label: 'Ganho diario', data: values, borderColor: '#0f766e', backgroundColor: 'rgba(15,118,110,0.12)', tension: 0.3, fill: true, pointRadius: 3 }] },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { ticks: { callback: (v) => 'R$ ' + fmt(v) } } } }
                        });
                    } else {
                        dailyContainer.style.display = 'none';
                        appsContainer.style.display = '';
                    }

                    if (chartGastos) chartGastos.destroy();
                    chartGastos = new Chart(document.getElementById('chartGastos').getContext('2d'), { type: 'doughnut', data: { labels: ['Essenciais', 'Não Essenciais'], datasets: [{ data: [c.gastos_essenciais, c.gastos_nao_essenciais], backgroundColor: ['#0f766e', '#e11d48'] }] }, options: { responsive: true, maintainAspectRatio: false, cutout: '75%', plugins: { legend: { display: false } } } });
                    
                    // History Nav
                    const hlist = document.getElementById('history-list'); hlist.innerHTML = '';
                    const live = document.createElement('a'); live.href = '#'; live.className = 'history-item block p-3 rounded-lg ' + (!aid ? 'bg-teal-50 border-teal-200 border' : 'bg-white');
                    live.innerHTML = `<span class="text-xs font-bold uppercase ${!aid ? 'text-teal-600' : 'text-slate-500'}">AO VIVO</span><span class="block text-xs font-medium ${!aid ? 'text-teal-800':'text-slate-700'}">Dashboard Atual</span>`;
                    live.onclick = (e) => { e.preventDefault(); loadDashboard(); }; hlist.appendChild(live);
                    data.history.forEach((h, i) => {
                        const btn = document.createElement('a'); btn.href = '#'; btn.className = 'history-item block p-3 rounded-lg mt-2 ' + (aid === h.id ? 'bg-teal-50 border-teal-200 border' : 'bg-white');
                        const cti = data.history.filter((x, j) => x.periodo_tipo === h.periodo_tipo && j >= i).length;
                        const periodLabel = formatPeriodRange(h) || `Analise de ${new Date(h.created_at).toLocaleDateString('pt-BR')}`;
                        btn.innerHTML = `<span class="text-xs font-bold uppercase ${aid === h.id ? 'text-teal-600':'text-slate-500'}">${h.periodo_tipo} ${cti}</span><span class="block text-[11px] text-slate-500">${periodLabel}</span>`;
                        btn.onclick = (e) => { e.preventDefault(); loadDashboard(h.id); }; hlist.appendChild(btn);
                    });
                    const sectionOpen = !document.getElementById('section-porteiros').classList.contains('hidden');
                    if (sectionOpen) {
                        const existingFilter = document.getElementById('search-porteiros')?.value || '';
                        renderPorteiros(existingFilter);
                    }
                } catch (e) { console.error('Dashboard load error:', e); }
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
