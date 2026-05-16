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
        return {"reply": "⚠️ Tive uma instabilidade momentânea."}

async def process_interpreted_data(user, interpreted):
    intencao = interpreted.get("intencao")
    user_id = user["id"]
    data_ref = interpreted.get("data_referencia")
    if data_ref == "null": data_ref = None
    eventos_brutos = interpreted.get("eventos", [])
    whatsapp = user["whatsapp_number"]
    if data_ref: active_op = db.get_or_create_operation_by_date(user_id, data_ref)
    else:
        active_op = db.get_active_operation(user_id)
        if not active_op and len(eventos_brutos) > 0: active_op = db.start_operation(user_id)
    eventos_p = []
    for ev in eventos_brutos:
        app_name_raw = str(ev.get("app") or "").lower()
        if not app_name_raw or app_name_raw == "none":
            if float(ev.get("pacotes") or 0) > 0: ev["app"] = "Correios"
        if "shopee" in str(ev.get("app")).lower():
            ev["app"], ev["valor"], ev["km"], ev["tipo"] = "Shopee", 305.0 + float(ev.get("valor_extra") or 0), 60.0, "ganho"
        elif "correio" in str(ev.get("app")).lower():
            ev["app"], ev["km"], ev["tipo"] = "Correios", 20.0, "ganho"
            v, p = float(ev.get("valor") or 0), float(ev.get("pacotes") or 0)
            ev["valor"] = ((p * 2.0) if (v == 0 or v == p) else v) + float(ev.get("valor_extra") or 0)
        else:
            app_info = db.get_app_by_name(ev.get("app")) if ev.get("app") else None
            if app_info and (not ev.get("valor") or ev.get("valor") == 0):
                if app_info.get("tipo_remuneracao") == "pacote": ev["valor"] = (ev.get("pacotes", 0) * app_info["valor_base"]) + float(ev.get("valor_extra") or 0)
                elif app_info.get("tipo_remuneracao") == "rota": ev["valor"] = app_info["valor_base"] + float(ev.get("valor_extra") or 0)
            elif ev.get("valor"): ev["valor"] = float(ev["valor"]) + float(ev.get("valor_extra") or 0)
        if active_op:
            if data_ref: ev["data_referencia"] = data_ref
            db.add_event(user_id, active_op["id"], ev)
            eventos_p.append(ev)
    if intencao == "registro": return LogicService.format_events_confirmation(eventos_p, "DADOS REGISTRADOS", data_ref)
    if intencao == "pedir_link_dashboard": return f"📊 *Dashboard:* https://meibot.henriquedejesus.dev/dashboard/{whatsapp}"
    return "Processado."

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
            return {"user": user, "metrics": analysis["metrics"], "insight": analysis["insight"], "is_live": False, "created_at": analysis["created_at"], "history": history, "porteiros": porteiros}
    today = datetime.date.today()
    start_iso = today.replace(day=1).isoformat() + "T00:00:00Z"
    ev_live = db.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", start_iso).execute().data
    op_live = db.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).gte("data", today.replace(day=1).isoformat()).execute().data
    metrics_live = LogicService.calculate_metrics_grouped(ev_live, op_live)
    daily = {}
    for ev in ev_live:
        if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]:
            dt = datetime.datetime.fromisoformat(ev["timestamp"]).strftime('%Y-%m-%d')
            daily[dt] = daily.get(dt, 0) + float(ev.get("valor", 0))
    daily_list = sorted([{"date": d, "ganho": g} for d, g in daily.items()], key=lambda x: x['date'])
    return {"user": user, "metrics": metrics_live, "daily_performance": daily_list, "insight": "", "is_live": True, "history": history, "created_at": datetime.datetime.now().isoformat(), "porteiros": porteiros}

@app.get("/dashboard/{whatsapp_number}", response_class=HTMLResponse)
async def dashboard_page(whatsapp_number: str):
    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>MeiBot - Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');
            body { font-family: 'Space Grotesk', sans-serif; background: #f8fafc; color: #0f172a; }
            .card { background: white; border: 1px solid #e2e8f0; border-radius: 16px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05); }
            .history-item { transition: all 0.2s; }
        </style>
    </head>
    <body class="flex flex-col lg:flex-row min-h-screen">
        <aside class="w-full lg:w-80 bg-white border-b lg:border-r border-slate-200 p-6 flex-shrink-0 z-50 sticky top-0 lg:h-screen lg:overflow-y-auto">
            <div class="flex items-center gap-3 mb-8">
                <div class="w-10 h-10 bg-teal-600 rounded-lg flex items-center justify-center text-white shadow-md"> <i class="fa-solid fa-bolt"></i> </div>
                <h1 class="font-bold text-lg">MeiBot</h1>
            </div>
            <div class="mb-6"><p class="text-[11px] font-bold text-slate-400 uppercase mb-3">Navegação</p>
                <div class="flex flex-row lg:flex-col gap-2">
                    <button id="btn-nav-performance" onclick="showSection('performance')" class="flex items-center gap-3 p-2.5 rounded-lg bg-teal-50 text-teal-700 font-semibold text-sm border border-teal-100 w-full text-left"><i class="fa-solid fa-chart-pie w-4"></i> Performance</button>
                    <button id="btn-nav-porteiros" onclick="showSection('porteiros')" class="flex items-center gap-3 p-2.5 rounded-lg bg-transparent text-slate-600 font-medium text-sm hover:bg-slate-50 w-full text-left mt-2"><i class="fa-solid fa-map-location-dot w-4"></i> Porteiros</button>
                </div>
            </div>
            <p class="text-[11px] font-bold text-slate-400 uppercase mb-3">Histórico</p>
            <nav id="history-list" class="space-y-2"></nav>
        </aside>

        <main class="flex-grow p-5 md:p-8 space-y-6 w-full max-w-7xl mx-auto">
            <header class="border-b border-slate-200 pb-5">
                <h2 class="text-2xl md:text-3xl font-bold text-slate-800" id="main-title">Visão Geral</h2>
                <p id="txt-periodo" class="text-slate-500 text-sm mt-1">Carregando...</p>
            </header>

            <div id="section-performance" class="space-y-6">
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div class="card p-5 border-l-4 border-l-teal-500"><p class="text-slate-500 text-[10px] font-bold uppercase">Saldo Líquido</p><p id="txt-saldo" class="text-2xl font-bold text-teal-700">R$ 0,00</p></div>
                    <div class="card p-5 border-l-4 border-l-sky-500"><p class="text-slate-500 text-[10px] font-bold uppercase">Saldo c/ Provisão</p><p id="txt-saldo-provisao" class="text-2xl font-bold text-sky-700">R$ 0,00</p></div>
                    <div class="card p-5 border-l-4 border-l-amber-500"><p class="text-slate-500 text-[10px] font-bold uppercase">KM Total</p><p id="txt-km-total" class="text-2xl font-bold text-amber-700">0 km</p></div>
                    <div class="card p-5 border-l-4 border-l-indigo-500"><p class="text-slate-500 text-[10px] font-bold uppercase">Total Pacotes</p><p id="txt-pacotes-total" class="text-2xl font-bold text-indigo-700">0 pac</p></div>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    <div class="card p-5"><p class="text-slate-400 text-[10px] font-bold uppercase">Faturamento Bruto</p><p id="txt-bruto" class="text-xl font-bold">R$ 0,00</p></div>
                    <div class="card p-5"><p class="text-slate-400 text-[10px] font-bold uppercase">Eficiência na Rua</p><p id="txt-ganho-hora-rua" class="text-xl font-bold text-violet-700">R$ 0,00/h</p></div>
                    <div class="card p-5"><p class="text-slate-400 text-[10px] font-bold uppercase">Pacotes/Hora (Rua)</p><p id="txt-pacotes-hora" class="text-xl font-bold text-indigo-700">0/h</p></div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div id="daily-chart-container" class="lg:col-span-2 card p-6"><h3 class="font-bold text-sm mb-6 uppercase">Performance Diária</h3><div class="h-[300px]"><canvas id="chartDaily"></canvas></div></div>
                    <div id="apps-chart-container" class="lg:col-span-2 card p-6" style="display:none;"><h3 class="font-bold text-sm mb-6 uppercase">Performance por App</h3><div class="h-[300px]"><canvas id="chartApps"></canvas></div></div>
                    <div class="card p-6 flex flex-col"><h3 class="font-bold text-sm mb-6 uppercase">Gastos</h3><div class="h-[200px] mb-6"><canvas id="chartGastos"></canvas></div><div class="space-y-2"><div class="flex justify-between text-[10px] font-bold uppercase"><span>Essenciais</span><span id="txt-essencial">R$ 0,00</span></div><div class="flex justify-between text-[10px] font-bold uppercase text-rose-600"><span>Não Essenciais</span><span id="txt-nao-essencial">R$ 0,00</span></div></div></div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div class="lg:col-span-2 card p-6"><h3 class="font-bold text-sm mb-6 uppercase tracking-tight">Detalhamento por App</h3><div id="list-apps" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div></div>
                    <div class="card p-6 bg-amber-50/30 border-amber-100"><h3 class="font-bold text-amber-800 text-sm mb-4 uppercase">Eficiência de Galpão</h3><div class="flex items-end gap-2 mb-2"><p id="txt-tempo-espera" class="text-3xl font-bold text-amber-700">0h</p><p class="text-xs text-amber-500 font-bold mb-1 uppercase">Espera</p></div><div class="w-full bg-amber-100 rounded-full h-2 overflow-hidden mb-4"><div id="bar-espera" class="bg-amber-500 h-full" style="width: 0%"></div></div><p id="txt-tempo-total" class="text-[10px] text-slate-500">Tempo Total: 0h</p></div>
                </div>

                <div id="insight-section" class="card overflow-hidden hidden"><div class="bg-teal-600 px-6 py-3 text-white font-bold text-sm uppercase">Análise da IA</div><div class="p-6 prose prose-sm max-w-none" id="txt-insight"></div></div>
            </div>

            <div id="section-porteiros" class="hidden space-y-6">
                <div class="card p-6 flex flex-col md:flex-row justify-between items-center gap-4">
                    <div><h3 class="text-xl font-bold">Diretório de Porteiros</h3><p id="porteiros-stats" class="text-slate-500 text-sm mt-1">Carregando...</p></div>
                    <input type="text" id="search-porteiros" oninput="handleSearch(this.value)" class="p-2.5 bg-slate-50 border rounded-xl text-sm w-full md:w-80" placeholder="Buscar endereço ou porteiro...">
                </div>
                <div class="space-y-4" id="porteiros-container"></div>
            </div>
        </main>

        <script>
            let dailyChart = null, appsChart = null, chartGastos = null, dashboardData = null;
            const WHATSAPP_ID = '""" + whatsapp_number + """';
            const fmt = (v) => (v || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2});

            function showSection(s) {
                document.getElementById('section-performance').classList.toggle('hidden', s !== 'performance');
                document.getElementById('section-porteiros').classList.toggle('hidden', s !== 'porteiros');
                document.getElementById('main-title').innerText = s === 'performance' ? 'Visão Geral' : 'Diretório de Porteiros';
                renderPorteiros();
            }

            function handleSearch(q) { renderPorteiros(q); }
            function renderPorteiros(f = '') {
                const c = document.getElementById('porteiros-container'), s = document.getElementById('porteiros-stats');
                if (!dashboardData?.porteiros?.length) return;
                const q = f.toLowerCase().trim(), g = {};
                dashboardData.porteiros.filter(p => !q || `${p.rua} ${p.numero} ${p.nome_porteiro}`.toLowerCase().includes(q)).forEach(p => { const r = p.rua || 'Outros'; if(!g[r]) g[r]=[]; g[r].push(p); });
                s.innerText = `${dashboardData.porteiros.length} prédios cadastrados`; c.innerHTML = '';
                Object.keys(g).sort().forEach((r, i) => {
                    let h = ''; g[r].forEach(p => { h += `<div class="bg-white rounded-xl p-4 border border-slate-100 shadow-sm"><p class="text-xs font-bold text-teal-600 uppercase">Nº ${p.numero}</p><h5 class="font-bold text-slate-800">${p.nome_porteiro || 'Porteiro'}</h5><p class="text-xs text-slate-500">${p.turno || 'Não inf.'}</p></div>`; });
                    const d = document.createElement('div'); d.className = 'bg-white rounded-2xl border p-4 shadow-sm';
                    d.innerHTML = `<h4 class="font-bold text-slate-800 uppercase mb-4">${r}</h4><div class="grid grid-cols-1 md:grid-cols-3 gap-4">${h}</div>`;
                    c.appendChild(d);
                });
            }

            async function loadDashboard(aid = null) {
                try {
                    const res = await fetch(aid ? `/api/dashboard/${WHATSAPP_ID}?analysis_id=${aid}` : `/api/dashboard/${WHATSAPP_ID}`);
                    const data = await res.json(); dashboardData = data;
                    const c = data.metrics.consolidado, apps = data.metrics.apps;
                    document.getElementById('txt-periodo').innerText = data.is_live ? 'Dados acumulados do mês' : `Relatório de ${new Date(data.created_at).toLocaleDateString('pt-BR')}`;
                    document.getElementById('txt-saldo').innerText = 'R$ ' + fmt(c.saldo);
                    document.getElementById('txt-saldo-provisao').innerText = 'R$ ' + fmt(c.saldo_com_provisao);
                    document.getElementById('txt-bruto').innerText = 'R$ ' + fmt(c.total_ganhos);
                    document.getElementById('txt-km-total').innerText = (c.km_total || 0).toFixed(1) + ' km';
                    document.getElementById('txt-pacotes-total').innerText = (c.total_pacotes || 0) + ' pac';
                    document.getElementById('txt-ganho-hora-rua').innerText = 'R$ ' + fmt(c.ganho_por_hora_rua) + '/h';
                    document.getElementById('txt-pacotes-hora').innerText = (c.pacotes_por_hora_rua || 0).toFixed(1) + '/h';
                    document.getElementById('txt-essencial').innerText = 'R$ ' + fmt(c.gastos_essenciais);
                    document.getElementById('txt-nao-essencial').innerText = 'R$ ' + fmt(c.gastos_nao_essenciais);
                    document.getElementById('txt-tempo-espera').innerText = (c.tempo_espera_galpao || 0).toFixed(1) + 'h';
                    document.getElementById('txt-tempo-total').innerText = 'Tempo Total: ' + (c.total_hours || 0).toFixed(1) + 'h';
                    document.getElementById('bar-espera').style.width = Math.min((c.tempo_espera_galpao / (c.total_hours || 1)) * 100, 100) + '%';
                    const ins = document.getElementById('insight-section');
                    if (!data.is_live && data.insight) { ins.classList.remove('hidden'); document.getElementById('txt-insight').innerHTML = marked.parse(data.insight); } else { ins.classList.add('hidden'); }
                    const list = document.getElementById('list-apps'); list.innerHTML = '';
                    Object.keys(apps).filter(n => apps[n].ganhos > 0).forEach(n => {
                        const a = apps[n]; list.innerHTML += `<div class="p-4 rounded-xl bg-slate-50 border shadow-sm"><p class="font-bold text-slate-800 text-sm uppercase">${n}</p><p class="text-[10px] text-slate-500 font-bold">R$ ${fmt(a.ganhos)} • ${a.pacotes} pac • ${a.km.toFixed(1)}km</p></div>`;
                    });
                    if (chartGastos) chartGastos.destroy();
                    chartGastos = new Chart(document.getElementById('chartGastos').getContext('2d'), { type: 'doughnut', data: { labels: ['Essenciais', 'Não Essenciais'], datasets: [{ data: [c.gastos_essenciais, c.gastos_nao_essenciais], backgroundColor: ['#0f766e', '#e11d48'] }] }, options: { responsive: true, maintainAspectRatio: false, cutout: '75%', plugins: { legend: { display: false } } } });
                    const dc = document.getElementById('daily-chart-container'), ac = document.getElementById('apps-chart-container');
                    if (data.is_live && data.daily_performance?.length > 0) {
                        dc.style.display = 'block'; ac.style.display = 'none';
                        if (dailyChart) dailyChart.destroy();
                        dailyChart = new Chart(document.getElementById('chartDaily').getContext('2d'), { type: 'bar', data: { labels: data.daily_performance.map(d => d.date.split('-')[2]), datasets: [{ label: 'Ganho', data: data.daily_performance.map(d => d.ganho), backgroundColor: '#0f766e', borderRadius: 4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } } });
                    } else {
                        dc.style.display = 'none'; ac.style.display = 'block';
                        if (appsChart) appsChart.destroy();
                        const sorted = Object.keys(apps).filter(n => apps[n].ganhos > 0);
                        appsChart = new Chart(document.getElementById('chartApps').getContext('2d'), { type: 'bar', data: { labels: sorted, datasets: [{ data: sorted.map(n => apps[n].ganhos), backgroundColor: ['#0f766e', '#f97316', '#6366f1'], borderRadius: 4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } } });
                    }
                    if (data.history) {
                        const hlist = document.getElementById('history-list'); hlist.innerHTML = '';
                        const live = document.createElement('div'); live.className = `history-item p-2.5 rounded-lg border cursor-pointer ${!aid ? 'bg-teal-50 border-teal-200' : 'bg-white'}`;
                        live.innerHTML = `<span class="text-[10px] font-bold uppercase ${!aid ? 'text-teal-600' : 'text-slate-500'}">AO VIVO</span><br><span class="text-xs font-medium">Dashboard Atual</span>`;
                        live.onclick = () => loadDashboard(); hlist.appendChild(live);
                        data.history.forEach((h, i) => {
                            const active = aid === h.id; const btn = document.createElement('div'); btn.className = `history-item p-2.5 rounded-lg border cursor-pointer mt-2 ${active ? 'bg-teal-50 border-teal-200' : 'bg-white'}`;
                            const cti = data.history.filter((x, j) => x.periodo_tipo === h.periodo_tipo && j >= i).length;
                            btn.innerHTML = `<span class="text-[10px] font-bold uppercase ${active ? 'text-teal-600' : 'text-slate-500'}">${h.periodo_tipo} ${cti}</span><br><span class="text-[10px] text-slate-400">Ver detalhes</span>`;
                            btn.onclick = () => loadDashboard(h.id); hlist.appendChild(btn);
                        });
                    }
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
