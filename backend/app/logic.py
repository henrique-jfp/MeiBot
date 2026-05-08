import datetime

class LogicService:
    @staticmethod
    def calculate_metrics_grouped(events: list, operations: list = None):
        apps_data = {}
        
        # Consolidados da Empresa
        consolidado = {
            "total_ganho": 0,
            "total_gastos_essenciais": 0,
            "total_gastos_nao_essenciais": 0,
            "total_km": 0,
            "total_pacotes": 0,
            "total_horas_brutas": 0,
            "tempo_espera_horas": 0
        }

        # Agrupar eventos por App
        for event in events:
            app_name = event.get('apps', {}).get('nome', 'Geral')
            if app_name not in apps_data:
                apps_data[app_name] = {
                    "total_ganho": 0,
                    "total_km": 0,
                    "total_pacotes": 0,
                    "tempo_espera_horas": 0,
                    "total_minutos_rota": 0
                }
            
            val = event.get('valor', 0)
            km = event.get('km', 0)
            pacotes = event.get('pacotes', 0)
            
            if event['tipo'] in ['corrida', 'rota']:
                apps_data[app_name]["total_ganho"] += val
                apps_data[app_name]["total_km"] += km
                apps_data[app_name]["total_pacotes"] += pacotes
                consolidado["total_ganho"] += val
                consolidado["total_km"] += km
                consolidado["total_pacotes"] += pacotes
                
                # Cálculo de duração se houver timestamps
                if event.get("hora_inicio") and event.get("hora_fim"):
                    try:
                        inicio = datetime.datetime.fromisoformat(event["hora_inicio"].replace('Z', '+00:00'))
                        fim = datetime.datetime.fromisoformat(event["hora_fim"].replace('Z', '+00:00'))
                        diff = (fim - inicio).total_seconds() / 3600
                        if diff > 0: apps_data[app_name]["total_minutos_rota"] += diff * 60
                    except: pass

            elif event['tipo'] == 'gasto':
                if event.get('categoria') == 'Essencial':
                    consolidado["total_gastos_essenciais"] += val
                else:
                    consolidado["total_gastos_nao_essenciais"] += val
            elif event['tipo'] == 'ajuste':
                apps_data[app_name]["total_ganho"] += val
                consolidado["total_ganho"] += val
            
            if event.get('sub_tipo') == 'espera_galpao':
                espera = event.get('tempo_minutos', 0) / 60
                apps_data[app_name]["tempo_espera_horas"] += espera
                consolidado["tempo_espera_horas"] += espera

        # Horas Brutas totais pelas operações
        if operations:
            for op in operations:
                if op.get("hora_inicio") and op.get("hora_fim"):
                    try:
                        inicio = datetime.datetime.fromisoformat(op["hora_inicio"].replace('Z', '+00:00'))
                        fim = datetime.datetime.fromisoformat(op["hora_fim"].replace('Z', '+00:00'))
                        diff = (fim - inicio).total_seconds() / 3600
                        if diff > 0: consolidado["total_horas_brutas"] += diff
                    except: continue

        # Finalizar métricas de cada App
        for app in apps_data:
            d = apps_data[app]
            d["horas_produtivas"] = (d["total_minutos_rota"] / 60) if d["total_minutos_rota"] > 0 else 0
            d["rs_km"] = d["total_ganho"] / d["total_km"] if d["total_km"] > 0 else 0
            d["rs_hora"] = d["total_ganho"] / d["horas_produtivas"] if d["horas_produtivas"] > 0 else 0

        # Finalizar métricas do Consolidado
        consolidado["lucro_liquido"] = consolidado["total_ganho"] - (consolidado["total_gastos_essenciais"] + consolidado["total_gastos_nao_essenciais"])
        consolidado["horas_produtivas"] = max(0, consolidado["total_horas_brutas"] - consolidado["tempo_espera_horas"])
        consolidado["rs_km"] = consolidado["total_ganho"] / consolidado["total_km"] if consolidado["total_km"] > 0 else 0
        consolidado["rs_hora"] = consolidado["total_ganho"] / consolidado["horas_produtivas"] if consolidado["horas_produtivas"] > 0 else 0
        consolidado["percentual_nao_essenciais"] = (consolidado["total_gastos_nao_essenciais"] / consolidado["total_ganho"] * 100) if consolidado["total_ganho"] > 0 else 0

        return {"apps": apps_data, "consolidado": consolidado}

    @staticmethod
    def format_summary_3_blocks(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None):
        resumo = f"📊 *{title.upper()}*\n\n"
        
        # Bloco de Apps
        for app_name, m in metrics["apps"].items():
            if app_name == "Geral" and m["total_ganho"] == 0: continue
            resumo += f"🏢 *OPERAÇÃO {app_name.upper()}*\n"
            resumo += f"💰 Ganho: R$ {m['total_ganho']:.2f}\n"
            resumo += f"🛣️ KM: {m['total_km']:.1f} | 📦 Pcts: {m['total_pacotes']}\n"
            resumo += f"⏱️ Rota: {m['horas_produtivas']:.1f}h | ⏳ Galpão: {m['tempo_espera_horas']:.1f}h\n"
            resumo += f"📈 Eficiência: R$ {m['rs_km']:.2f}/km | R$ {m['rs_hora']:.2f}/h\n\n"

        # Bloco Consolidado Empresa
        c = metrics["consolidado"]
        resumo += f"🏢 *CONSOLIDADO DA EMPRESA*\n"
        resumo += f"💵 Lucro Líquido: R$ {c['lucro_liquido']:.2f}\n"
        resumo += f"⛽ Gastos Essenciais: R$ {c['total_gastos_essenciais']:.2f}\n"
        resumo += f"🚬 Gastos Não Essenciais: {c['percentual_nao_essenciais']:.1f}%\n"
        resumo += f"🛣️ KM Total: {c['total_km']:.1f} | ⏱️ Horas Totais: {c['total_horas_brutas']:.1f}h\n"
        resumo += f"📈 Média Geral: R$ {c['rs_km']:.2f}/km\n\n"

        if analyst_insight:
            resumo += f"🧠 *VISÃO DO ANALISTA FODA:*\n{analyst_insight}\n\n"
            
        resumo += f"Bom trabalho, Boss! 🚀"
        return resumo

    @staticmethod
    def calculate_metrics(events: list, operations: list = None):
        # Mantendo para compatibilidade ou refatorando para usar o novo
        res = LogicService.calculate_metrics_grouped(events, operations)
        return res["consolidado"]

    @staticmethod
    def format_summary(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None):
        # Redireciona para o novo formato se vier no formato agrupado
        if "consolidado" in metrics:
            return LogicService.format_summary_3_blocks(metrics, title, analyst_insight)
        
        # Fallback para o formato antigo caso receba apenas o dicionário de métricas
        resumo = (
            f"📊 *{title.upper()}*\n\n"
            f"💰 Ganho Total: R$ {metrics['total_ganho']:.2f}\n"
            f"⛽ Gastos Essenciais: R$ {metrics['total_gastos_essenciais']:.2f}\n"
            f"🚬 Gastos Não Essenciais: R$ {metrics['total_gastos_nao_essenciais']:.2f} ({metrics['percentual_nao_essenciais']:.1f}%)\n"
            f"💵 Lucro Líquido: R$ {metrics['lucro_liquido']:.2f}\n"
            f"🛣️ KM Rodados: {metrics['total_km']:.1f} km\n"
            f"📦 Pacotes: {metrics['total_pacotes']}\n"
            f"⏱️ Horas Produtivas (Rua): {metrics['horas_produtivas']:.1f}h\n"
            f"⏳ Tempo de Espera (Galpão): {metrics['tempo_espera_horas']:.1f}h\n\n"
            f"📈 Métricas de Eficiência:\n"
            f"- R$/km: R$ {metrics['rs_km']:.2f}\n"
            f"- R$/hora (Rua): R$ {metrics['rs_hora']:.2f}\n"
            f"- R$/pacote: R$ {metrics['rs_pacote']:.2f}\n\n"
        )
        
        if analyst_insight:
            resumo += f"🧠 *VISÃO DO ANALISTA FODA:*\n{analyst_insight}\n\n"
            
        resumo += f"Bom trabalho! Descansa que amanhã tem mais! 🚀"
        return resumo
