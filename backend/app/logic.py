import datetime

class LogicService:
    @staticmethod
    def format_events_confirmation(eventos, title):
        if not eventos: return "Nenhum dado registrado."
        res = f"✅ *{title}*\n\n"
        for ev in eventos:
            tipo = ev.get("tipo", "evento").upper()
            app = ev.get("app", "")
            valor = ev.get("valor", 0)
            res += f"• {tipo} ({app}): R$ {valor:.2f}\n"
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
            "total_horas": 0,
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
        
        msg = f"📊 *{title}*\n"
        msg += "--------------------------\n"
        msg += f"💰 *Saldo Líquido:* R$ {c['saldo']:.2f}\n"
        msg += f"📈 *Ganhos:* R$ {c['total_ganhos']:.2f}\n"
        msg += f"📉 *Gastos:* R$ {c['total_gastos']:.2f}\n"
        msg += "--------------------------\n"
        msg += f"🛣️ *KM Total:* {c['km_total']:.1f} km\n"
        
        if c.get("total_hours"):
            msg += f"⏱️ *Tempo Total:* {c['total_hours']:.1f}h\n"
            msg += f"🕒 *Ganho/Hora:* R$ {c.get('ganho_por_hora', 0):.2f}/h\n"

        if analyst_insight:
            msg += "\n\n🧐 *Visão do Analista:*\n"
            msg += f"_{analyst_insight}_"
            
        return msg

    @staticmethod
    def calculate_metrics(events: list, operations: list = None):
        # Versão simplificada para compatibilidade
        return LogicService.calculate_metrics_grouped(events, operations)

    @staticmethod
    def format_summary(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None):
        return LogicService.format_summary_3_blocks(metrics, title, analyst_insight)
