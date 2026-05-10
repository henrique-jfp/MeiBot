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
    def format_events_confirmation(eventos, title):
        if not eventos: return "Nenhum dado registrado."
        res = f"✅ *{title}*\n\n"
        for ev in eventos:
            tipo = ev.get("tipo", "evento").upper()
            app = ev.get("app", "")
            valor = ev.get("valor", 0)
            km = ev.get("km_rota", ev.get("km"))
            pacotes = ev.get("pacotes")
            h_chegada = ev.get("hora_chegada_galpao")
            h_inicio = ev.get("hora_inicio_rota") or ev.get("hora_inicio")
            h_fim = ev.get("hora_fim_operacao") or ev.get("hora_fim")

            res += f"• {tipo} ({app}): R$ {valor:.2f}"

            details = []
            if km:
                details.append(f"{float(km):.1f} km")
            if pacotes:
                details.append(f"{int(pacotes)} pacotes")
            if h_chegada:
                details.append(f"chegada {h_chegada}")
            if h_inicio:
                details.append(f"inicio {h_inicio}")
            if h_fim:
                details.append(f"fim {h_fim}")

            if h_inicio and h_fim:
                try:
                    fmt = "%H:%M"
                    t1 = datetime.datetime.strptime(h_inicio, fmt)
                    t2 = datetime.datetime.strptime(h_fim, fmt)
                    diff = (t2 - t1).total_seconds()
                    if diff < 0:
                        diff += 24 * 3600
                    horas = diff / 3600
                    details.append(f"duracao {horas:.2f}h")
                except Exception:
                    pass

            if h_chegada and h_inicio:
                try:
                    fmt = "%H:%M"
                    t1 = datetime.datetime.strptime(h_chegada, fmt)
                    t2 = datetime.datetime.strptime(h_inicio, fmt)
                    diff = (t2 - t1).total_seconds()
                    if diff < 0:
                        diff += 24 * 3600
                    espera = diff / 60
                    details.append(f"espera {int(espera)} min")
                except Exception:
                    pass

            if details:
                res += " (" + ", ".join(details) + ")"
            res += "\n"
        return res

    @staticmethod
    def calculate_metrics_grouped(events: list, operations: list = None):
        apps_data = {}
        
        # Consolidados da Empresa
        consolidado = {
            "total_ganhos": 0,
            "total_gastos": 0,
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

            if app_name not in apps_data:
                apps_data[app_name] = {"ganhos": 0, "gastos": 0, "km": 0}

            if tipo in ["ganho", "rota", "corrida", "faturamento"]:
                apps_data[app_name]["ganhos"] += val
                consolidado["total_ganhos"] += val
            elif tipo in ["gasto", "despesa", "saída"]:
                apps_data[app_name]["gastos"] += val
                consolidado["total_gastos"] += val
            elif tipo == "ajuste":
                consolidado["total_ajustes"] += val
            
            consolidado["km_total"] += km_val
            apps_data[app_name]["km"] += km_val

        # Cálculo de Horas
        if operations:
            total_sec = 0
            now = datetime.datetime.now()
            for op in operations:
                if op.get("hora_inicio"):
                    try:
                        h1 = datetime.datetime.fromisoformat(op["hora_inicio"].replace('Z', '+00:00'))
                        # Se não tem hora_fim (operação ativa), usa o 'agora'
                        if op.get("hora_fim"):
                            h2 = datetime.datetime.fromisoformat(op["hora_fim"].replace('Z', '+00:00'))
                        else:
                            # Converte 'now' para o mesmo formato/timezone se necessário
                            h2 = now.astimezone(h1.tzinfo) if h1.tzinfo else now
                        
                        diff = (h2 - h1).total_seconds()
                        if diff > 0:
                            total_sec += diff
                    except Exception as e:
                        print(f"Erro ao calcular horas da operação {op.get('id')}: {e}")
            consolidado["total_hours"] = total_sec / 3600
        
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
            return match_text.title(), {"ganhos": 0, "gastos": 0, "km": 0}

        def app_block(label: str, data: dict):
            saldo = (data.get("ganhos", 0) or 0) - (data.get("gastos", 0) or 0)
            ganhos = data.get("ganhos", 0) or 0
            gastos = data.get("gastos", 0) or 0
            km = data.get("km", 0) or 0
            eficiencia = saldo / km if km else 0
            msg_block = f"\n {label.upper()}\n"
            msg_block += "┌──────────────────────────\n"
            msg_block += f" Saldo Líquido: {LogicService.format_brl(saldo)}\n"
            msg_block += f" Ganhos:        {LogicService.format_brl(ganhos)}\n"
            msg_block += f" Gastos:        {LogicService.format_brl(gastos)}\n"
            msg_block += f" KM Rodados:    {LogicService.format_decimal(km)} km ({LogicService.format_brl(eficiencia)}/km)\n"
            msg_block += "⏱️ Tempo Total:   0h (R$ 0,00/h)\n"
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
            msg += f"\n Período: {period_label}\n"
        msg += app_block(shopee_name, shopee_data)
        msg += app_block(correios_name, correios_data)

        msg += "\n CONSOLIDADO DA OPERAÇÃO\n"
        msg += "┌──────────────────────────\n"
        msg += f" Saldo Líquido: {LogicService.format_brl(c.get('saldo', 0))}\n"
        msg += f" Ganhos Totais: {LogicService.format_brl(c.get('total_ganhos', 0))}\n"
        msg += f" Gastos Totais: {LogicService.format_brl(c.get('total_gastos', 0))}\n"
        msg += f" KM Total:      {LogicService.format_decimal(km_total)} km\n"
        msg += f"⏱️ Tempo Total:   {LogicService.format_decimal(total_hours)}h\n"
        msg += f" Ganho/Hora:    {LogicService.format_brl(ganho_hora)}/h\n"
        msg += f" Eficiência:    {LogicService.format_brl(eficiencia)}/km\n"
        msg += "└──────────────────────────\n"

        if analyst_insight:
            msg += "\n VISÃO DO ANALISTA ESTRATÉGICO\n\n"
            msg += analyst_insight

        return msg

    @staticmethod
    def calculate_metrics(events: list, operations: list = None):
        # Versão simplificada para compatibilidade
        return LogicService.calculate_metrics_grouped(events, operations)

    @staticmethod
    def format_summary(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None):
        return LogicService.format_summary_3_blocks(metrics, title, analyst_insight)
