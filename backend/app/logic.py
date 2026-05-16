import datetime
from collections import defaultdict

CUSTO_PROVISAO_KM = 0.20 # Provisão de 20 centavos por KM rodado

class LogicService:
    @staticmethod
    def format_brl(value):
        try:
            number = float(value or 0)
        except Exception:
            number = 0
        formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {formatted}"

    @staticmethod
    def format_decimal(value, digits=1):
        try:
            number = float(value or 0)
        except Exception:
            number = 0
        return f"{number:.{digits}f}".replace(".", ",")

    @staticmethod
    def format_events_confirmation(eventos, title, data_ref=None):
        if not eventos: return "Nenhum dado registrado."
        
        ganhos = [e for e in eventos if str(e.get("tipo")).upper() == "GANHO"]
        gastos = [e for e in eventos if str(e.get("tipo")).upper() == "GASTO"]
        
        data_str = ""
        if data_ref:
            try:
                dt = datetime.datetime.fromisoformat(data_ref)
                data_str = f" do dia *{dt.strftime('%d/%m/%Y')}*"
            except:
                data_str = f" do dia *{data_ref}*"

        res = f"✅ *Registro concluído*{data_str}\n\n"
        
        for g in ganhos:
            app = g.get("app", "Rota")
            valor = float(g.get("valor") or 0)
            res += f"💰 *{app}* — R$ {valor:.2f}\n"
        
        if gastos:
            res += "\n💸 *Despesas*\n"
            for gast in gastos:
                desc = gast.get("app") or gast.get("descricao") or "Gasto"
                icon = "🧾"
                desc_lower = desc.lower()
                if "combust" in desc_lower or "gasolin" in desc_lower or "etanol" in desc_lower: icon = "⛽"
                elif "aliment" in desc_lower or "lanche" in desc_lower: icon = "🍔"
                elif "ajudante" in desc_lower: icon = "👤"
                valor_gasto = float(gast.get('valor') or 0)
                res += f"• {icon} {desc}: R$ {valor_gasto:.2f}\n"
        
        for g in ganhos:
            km = g.get("km")
            pacotes = g.get("pacotes")
            if km or pacotes:
                res += "\n📦 *Entrega*\n"
                parts = []
                if km: parts.append(f"🚗 {float(km):.1f} km")
                if pacotes: parts.append(f"📦 {int(pacotes)} pacotes")
                res += " • ".join(parts) + "\n"
                break
        
        for g in ganhos:
            h_chegada = g.get("hora_chegada_galpao")
            h_inicio = g.get("hora_inicio_rota") or g.get("hora_inicio")
            h_fim = g.get("hora_fim_operacao") or g.get("hora_fim")
            if h_chegada or h_inicio or h_fim:
                res += "\n🕒 "
                times = [t for t in [h_chegada, h_inicio, h_fim] if t]
                res += " → ".join(times) + "\n"
                break
        return res

    @staticmethod
    def calculate_metrics_grouped(events: list, operations: list = None):
        apps_data = {}
        consolidado = {
            "total_ganhos": 0, "total_gastos": 0, "gastos_essenciais": 0, "gastos_nao_essenciais": 0,
            "km_total": 0, "total_pacotes": 0, "saldo": 0, "total_hours": 0, "tempo_espera_galpao": 0,
            "days_worked": 0, "ganho_por_hora": 0, "custo_por_km": 0, "saldo_com_provisao": 0,
            "ganho_por_hora_rua": 0, "pacotes_por_hora": 0, "pacotes_por_hora_rua": 0
        }

        def parse_date(value):
            if not value: return None
            try:
                text = str(value).replace('Z', '+00:00')
                return datetime.datetime.fromisoformat(text).date() if 'T' in text else datetime.date.fromisoformat(text)
            except: return None

        def add_duration_hours(start_val, end_val):
            if not start_val or not end_val: return 0
            try:
                fmt = "%H:%M"
                t1 = datetime.datetime.strptime(str(start_val), fmt)
                t2 = datetime.datetime.strptime(str(end_val), fmt)
                diff = (t2 - t1).total_seconds()
                if diff < 0: diff += 24 * 3600
                return max(diff, 0) / 3600
            except: return 0

        intervals_per_day = defaultdict(list)
        for ev in events:
            val = float(ev.get("valor") or 0)
            km_val = float(ev.get("km") or 0)
            pac_val = int(ev.get("pacotes") or 0)
            app_info = ev.get("apps")
            app_name = app_info.get("nome") if isinstance(app_info, dict) else (ev.get("app") or "Outros")
            
            tipo = str(ev.get("tipo") or "").lower()
            if app_name not in apps_data: apps_data[app_name] = {"ganhos": 0, "gastos": 0, "km": 0, "horas": 0, "pacotes": 0}

            if tipo in ["ganho", "rota", "corrida", "faturamento"]:
                apps_data[app_name]["ganhos"] += val
                apps_data[app_name]["pacotes"] += pac_val
                consolidado["total_ganhos"] += val
                consolidado["total_pacotes"] += pac_val
                consolidado["km_total"] += km_val
                apps_data[app_name]["km"] += km_val
            elif tipo in ["gasto", "despesa"]:
                consolidado["total_gastos"] += val
                desc = str(ev.get("descricao") or "").lower()
                if any(k in desc for k in ["combust", "gasolin", "ajudante", "pneu", "manuten"]): consolidado["gastos_essenciais"] += val
                else: consolidado["gastos_nao_essenciais"] += val

            if str(ev.get("sub_tipo")).lower() == "espera_galpao":
                consolidado["tempo_espera_galpao"] += add_duration_hours(ev.get("hora_inicio"), ev.get("hora_fim"))

            h_ini, h_fim = ev.get("hora_inicio"), ev.get("hora_fim")
            if h_ini and h_fim and (tipo in ["ganho", "rota"] or str(ev.get("sub_tipo")) == "espera_galpao"):
                try:
                    ev_date = parse_date(ev.get("timestamp"))
                    if ev_date:
                        fmt = "%H:%M"
                        t1 = datetime.datetime.combine(ev_date, datetime.datetime.strptime(str(h_ini), fmt).time())
                        t2 = datetime.datetime.combine(ev_date, datetime.datetime.strptime(str(h_fim), fmt).time())
                        if t2 < t1: t2 += datetime.timedelta(days=1)
                        intervals_per_day[ev_date].append((t1, t2))
                        apps_data[app_name]["horas"] += (t2 - t1).total_seconds() / 3600
                except: pass

        total_unique_hours = 0
        for day, intervals in intervals_per_day.items():
            intervals.sort()
            if not intervals: continue
            curr_start, curr_end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start <= curr_end: curr_end = max(curr_end, next_end)
                else: total_unique_hours += (curr_end - curr_start).total_seconds() / 3600; curr_start, curr_end = next_start, next_end
            total_unique_hours += (curr_end - curr_start).total_seconds() / 3600

        consolidado["days_worked"] = len(intervals_per_day) or (len(operations) if operations else 0)
        consolidado["total_hours"] = total_unique_hours
        consolidado["saldo"] = consolidado["total_ganhos"] - consolidado["total_gastos"]
        consolidado["saldo_com_provisao"] = consolidado["saldo"] - (consolidado["km_total"] * CUSTO_PROVISAO_KM)
        
        if consolidado["total_hours"] > 0:
            consolidado["ganho_por_hora"] = consolidado["saldo"] / consolidado["total_hours"]
            consolidado["pacotes_por_hora"] = consolidado["total_pacotes"] / consolidado["total_hours"]
        
        horas_na_rua = consolidado["total_hours"] - consolidado["tempo_espera_galpao"]
        if horas_na_rua > 0:
            consolidado["ganho_por_hora_rua"] = consolidado["total_ganhos"] / horas_na_rua
            consolidado["pacotes_por_hora_rua"] = consolidado["total_pacotes"] / horas_na_rua
        
        return {"consolidado": consolidado, "apps": apps_data}

    @staticmethod
    def format_summary_3_blocks(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None):
        c = metrics["consolidado"]
        apps = metrics.get("apps") or {}
        msg = f"╔════════════════════════════╗\n {title}\n╚════════════════════════════╝\n"
        
        for name, data in apps.items():
            if data["ganhos"] == 0: continue
            pac = int(data['pacotes'])
            h = data['horas']
            msg += f"\n📦 {name.upper()}\n┌──────────────────────────\n"
            msg += f" 💰 Faturamento: {LogicService.format_brl(data['ganhos'])}\n"
            msg += f" 📦 Pacotes:     {pac} ({pac/h:.1f}/h)\n" if h > 0 else f" 📦 Pacotes:     {pac}\n"
            msg += f" 🛣️ KM Rodados:  {data['km']:.1f} km\n ⏱️ Tempo Rota:  {h:.1f}h\n└──────────────────────────\n"

        msg += f"\n 🏢 CONSOLIDADO\n┌──────────────────────────\n"
        msg += f" 💰 Saldo Líquido: {LogicService.format_brl(c['saldo'])}\n"
        msg += f" 📈 Ganhos Totais: {LogicService.format_brl(c['total_ganhos'])}\n"
        msg += f" 📦 Total Pacotes: {int(c['total_pacotes'])}\n"
        msg += f" 🛣️ KM Total:      {c['km_total']:.1f} km\n"
        msg += f" ⏱️ Tempo Total:   {c['total_hours']:.1f}h\n"
        msg += f" 🚀 Pacotes/Hora:  {c['pacotes_por_hora_rua']:.1f}/h (rua)\n"
        msg += "└──────────────────────────\n"
        if analyst_insight: msg += f"\n 🤵 VISÃO DO ANALISTA\n\n{analyst_insight}"
        return msg

    @staticmethod
    def calculate_metrics(events: list, operations: list = None): return LogicService.calculate_metrics_grouped(events, operations)
    @staticmethod
    def format_summary(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None): return LogicService.format_summary_3_blocks(metrics, title, analyst_insight)
