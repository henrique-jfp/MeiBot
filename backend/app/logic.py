import datetime

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
        
        # Bloco de Ganhos
        for g in ganhos:
            app = g.get("app", "Rota")
            valor = g.get("valor", 0)
            res += f"💰 *{app}* — R$ {valor:.2f}\n"
        
        # Bloco de Despesas
        if gastos:
            res += "\n💸 *Despesas*\n"
            for gast in gastos:
                desc = gast.get("app") or gast.get("descricao") or "Gasto"
                # Icones amigáveis para gastos comuns
                icon = "🧾"
                if "combust" in desc.lower() or "gas" in desc.lower(): icon = "⛽"
                elif "aliment" in desc.lower() or "comid" in desc.lower() or "coca" in desc.lower(): icon = "🍔"
                elif "ajudante" in desc.lower(): icon = "👤"
                
                res += f"• {icon} {desc}: R$ {gast.get('valor', 0):.2f}\n"
        
        # Bloco de Entrega (pega dados do primeiro ganho que tiver pacotes/km)
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
        
        # Bloco de Horários
        for g in ganhos:
            h_chegada = g.get("hora_chegada_galpao")
            h_inicio = g.get("hora_inicio_rota") or g.get("hora_inicio")
            h_fim = g.get("hora_fim_operacao") or g.get("hora_fim")
            
            if h_chegada or h_inicio or h_fim:
                res += "\n🕒 "
                times = []
                if h_chegada: times.append(h_chegada)
                if h_inicio: times.append(h_inicio)
                if h_fim: times.append(h_fim)
                res += " → ".join(times) + "\n"
                
                # Cálculos de Duração e Espera
                stats = []
                fmt = "%H:%M"
                if h_inicio and h_fim:
                    try:
                        t1 = datetime.datetime.strptime(h_inicio, fmt)
                        t2 = datetime.datetime.strptime(h_fim, fmt)
                        diff = (t2 - t1).total_seconds()
                        if diff < 0: diff += 24 * 3600
                        h = int(diff // 3600)
                        m = int((diff % 3600) // 60)
                        stats.append(f"⏱️ {h}h{m}min")
                    except: pass
                
                if h_chegada and h_inicio:
                    try:
                        t1 = datetime.datetime.strptime(h_chegada, fmt)
                        t2 = datetime.datetime.strptime(h_inicio, fmt)
                        diff = (t2 - t1).total_seconds()
                        if diff < 0: diff += 24 * 3600
                        espera = int(diff // 60)
                        stats.append(f"💤 {espera} min")
                    except: pass
                
                if stats:
                    res += " • ".join(stats) + "\n"
                break

        return res

    @staticmethod
    def calculate_metrics_grouped(events: list, operations: list = None):
        apps_data = {}
        
        # Consolidados da Empresa
        consolidado = {
            "total_ganhos": 0,
            "total_gastos": 0,
            "gastos_essenciais": 0,
            "gastos_nao_essenciais": 0,
            "total_ajustes": 0,
            "km_total": 0,
            "saldo": 0,
            "total_hours": 0,
            "ganho_por_hora": 0,
            "custo_por_km": 0,
            "total_operacoes": len(operations) if operations else 0
        }

        for ev in events:
            # Pega o valor de forma ultra-robusta
            try:
                val = float(ev.get("valor") or 0)
            except:
                val = 0
                
            # Pega o KM de forma ultra-robusta
            try:
                km_val = float(ev.get("km") or 0)
            except:
                km_val = 0

            # Identifica o app (considerando o join do Supabase)
            app_info = ev.get("apps")
            app_name = "Outros"
            if isinstance(app_info, dict):
                app_name = app_info.get("nome") or "Outros"
            elif ev.get("app"):
                app_name = ev.get("app")

            tipo = str(ev.get("tipo") or "").lower()
            categoria = str(ev.get("categoria") or "").lower()

            if app_name not in apps_data:
                apps_data[app_name] = {"ganhos": 0, "gastos": 0, "km": 0, "horas": 0}

            if tipo in ["ganho", "rota", "corrida", "faturamento"]:
                apps_data[app_name]["ganhos"] += val
                consolidado["total_ganhos"] += val
            elif tipo in ["gasto", "despesa", "saída"]:
                # REGRA DE ISOLAMENTO: Só desconta do APP se o gasto for explicitamente dele
                # Gastos genéricos (sem app_id ou categoria de custo fixo como combustível) 
                # somam apenas no consolidado da empresa.
                
                # Se o evento veio com apps (join) ou app_id preenchido, ele é específico
                has_app_link = bool(ev.get("apps") or ev.get("app_id"))
                
                if has_app_link:
                    apps_data[app_name]["gastos"] += val
                
                consolidado["total_gastos"] += val
                if categoria == "não essencial" or categoria == "nao essencial":
                    consolidado["gastos_nao_essenciais"] += val
                else:
                    consolidado["gastos_essenciais"] += val
            elif tipo == "ajuste":
                consolidado["total_ajustes"] += val
            
            consolidado["km_total"] += km_val
            apps_data[app_name]["km"] += km_val

            # Cálculo de horas por evento (se houver)
            h_ini = ev.get("hora_inicio")
            h_fim = ev.get("hora_fim")
            if h_ini and h_fim:
                try:
                    # Tenta formato HH:MM
                    if ":" in str(h_ini) and len(str(h_ini)) <= 5:
                        fmt = "%H:%M"
                        t1 = datetime.datetime.strptime(h_ini, fmt)
                        t2 = datetime.datetime.strptime(h_fim, fmt)
                        diff = (t2 - t1).total_seconds()
                        if diff < 0: diff += 24 * 3600
                        apps_data[app_name]["horas"] += diff / 3600
                except:
                    pass

        # Cálculo de Horas Totais (Soma das rotas individuais para ignorar repouso)
        total_worked_hours = 0
        for app_name in apps_data:
            total_worked_hours += apps_data[app_name].get("horas", 0)
        consolidado["total_hours"] = total_worked_hours
        
        consolidado["saldo"] = consolidado["total_ganhos"] - consolidado["total_gastos"]
        if consolidado.get("total_hours", 0) > 0:
            consolidado["ganho_por_hora"] = consolidado["saldo"] / consolidado["total_hours"]
        
        if consolidado["km_total"] > 0:
            consolidado["custo_por_km"] = consolidado["total_gastos"] / consolidado["km_total"]

        return {
            "consolidado": consolidado,
            "apps": apps_data
        }

    @staticmethod
    def format_summary_3_blocks(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None):
        c = metrics["consolidado"]
        apps = metrics.get("apps") or {}
        period_label = metrics.get("period_label")

        def find_app(match_text: str):
            match_text = match_text.lower()
            for name, data in apps.items():
                if name and match_text in name.lower():
                    return name, data
            return match_text.title(), {"ganhos": 0, "gastos": 0, "km": 0, "horas": 0}

        def app_block(label: str, data: dict):
            ganhos = data.get("ganhos", 0) or 0
            km = data.get("km", 0) or 0
            horas = data.get("horas", 0) or 0
            eficiencia_km = ganhos / km if km else 0
            eficiencia_hora = ganhos / horas if horas else 0
            
            msg_block = f"\n📦 {label.upper()}\n"
            msg_block += "┌──────────────────────────\n"
            msg_block += f" 💰 Faturamento:   {LogicService.format_brl(ganhos)}\n"
            msg_block += f" 🛣️ KM Rodados:    {LogicService.format_decimal(km)} km ({LogicService.format_brl(eficiencia_km)}/km)\n"
            msg_block += f" ⏱️ Tempo Rota:    {LogicService.format_decimal(horas)}h ({LogicService.format_brl(eficiencia_hora)}/h)\n"
            msg_block += "└──────────────────────────\n"
            return msg_block

        shopee_name, shopee_data = find_app("shopee")
        correios_name, correios_data = find_app("correio")

        km_total = c.get("km_total", 0) or 0
        total_hours = c.get("total_hours", 0) or 0
        ganho_hora = c.get("ganho_por_hora", 0) or 0
        eficiencia = (c.get("saldo", 0) or 0) / km_total if km_total else 0

        msg = "╔════════════════════════════╗\n"
        msg += f" {title}\n"
        msg += "╚════════════════════════════╝\n"
        if period_label:
            msg += f"\n 📅 Período: {period_label}\n"
        msg += app_block(shopee_name, shopee_data)
        msg += app_block(correios_name, correios_data)

        msg += "\n 🏢 CONSOLIDADO DA OPERAÇÃO\n"
        msg += "┌──────────────────────────\n"
        msg += f" 💰 Saldo Líquido: {LogicService.format_brl(c.get('saldo', 0))}\n"
        msg += f" 📈 Ganhos Totais: {LogicService.format_brl(c.get('total_ganhos', 0))}\n"
        msg += f" 📉 Gastos Essenciais: {LogicService.format_brl(c.get('gastos_essenciais', 0))}\n"
        msg += f" 🍔 Gastos Não Essenciais: {LogicService.format_brl(c.get('gastos_nao_essenciais', 0))}\n"
        msg += f" 🛣️ KM Total:      {LogicService.format_decimal(km_total)} km\n"
        msg += f" ⏱️ Tempo Total:   {LogicService.format_decimal(total_hours)}h\n"
        msg += f" 💸 Ganho/Hora:    {LogicService.format_brl(ganho_hora)}/h\n"
        msg += f" 📊 Eficiência:    {LogicService.format_brl(eficiencia)}/km\n"
        msg += "└──────────────────────────\n"

        if analyst_insight:
            msg += "\n 🤵 VISÃO DO ANALISTA ESTRATÉGICO\n\n"
            msg += analyst_insight

        return msg

    @staticmethod
    def calculate_metrics(events: list, operations: list = None):
        # Versão simplificada para compatibilidade
        return LogicService.calculate_metrics_grouped(events, operations)

    @staticmethod
    def format_summary(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None):
        return LogicService.format_summary_3_blocks(metrics, title, analyst_insight)
