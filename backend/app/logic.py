import datetime

class LogicService:
    @staticmethod
    def calculate_metrics(events: list, operations: list = None):
        total_ganho = 0
        total_gastos_essenciais = 0
        total_gastos_nao_essenciais = 0
        total_km = 0
        total_pacotes = 0
        total_minutos_espera = 0
        
        for event in events:
            if event['tipo'] == 'corrida':
                total_ganho += event.get('valor', 0)
                total_km += event.get('km', 0)
                total_pacotes += event.get('pacotes', 0)
            elif event['tipo'] == 'gasto':
                if event.get('categoria') == 'Essencial':
                    total_gastos_essenciais += event.get('valor', 0)
                else:
                    total_gastos_nao_essenciais += event.get('valor', 0)
            elif event['tipo'] == 'ajuste':
                total_ganho += event.get('valor', 0)
            elif event['tipo'] == 'espera':
                total_minutos_espera += event.get('tempo_minutos', 0)

        total_gastos = total_gastos_essenciais + total_gastos_nao_essenciais
        lucro_liquido = total_ganho - total_gastos
        rs_km = total_ganho / total_km if total_km > 0 else 0
        
        # Cálculo de horas trabalhadas totais
        total_horas_brutas = 0
        if operations:
            for op in operations:
                if op.get("hora_inicio") and op.get("hora_fim"):
                    try:
                        inicio = datetime.datetime.fromisoformat(op["hora_inicio"].replace('Z', '+00:00'))
                        fim = datetime.datetime.fromisoformat(op["hora_fim"].replace('Z', '+00:00'))
                        diff = (fim - inicio).total_seconds() / 3600
                        if diff > 0: total_horas_brutas += diff
                    except:
                        continue
        
        tempo_espera_horas = total_minutos_espera / 60
        horas_produtivas = max(0, total_horas_brutas - tempo_espera_horas)
        
        rs_hora = total_ganho / horas_produtivas if horas_produtivas > 0 else 0
        rs_pacote = total_ganho / total_pacotes if total_pacotes > 0 else 0
        percentual_nao_essenciais = (total_gastos_nao_essenciais / total_ganho * 100) if total_ganho > 0 else 0
        
        return {
            "total_ganho": total_ganho,
            "total_gastos_essenciais": total_gastos_essenciais,
            "total_gastos_nao_essenciais": total_gastos_nao_essenciais,
            "percentual_nao_essenciais": percentual_nao_essenciais,
            "total_gastos": total_gastos,
            "lucro_liquido": lucro_liquido,
            "total_km": total_km,
            "total_pacotes": total_pacotes,
            "total_horas_brutas": total_horas_brutas,
            "tempo_espera_horas": tempo_espera_horas,
            "horas_produtivas": horas_produtivas,
            "rs_km": rs_km,
            "rs_hora": rs_hora,
            "rs_pacote": rs_pacote
        }

    @staticmethod
    def format_events_confirmation(events: list, title: str = "DADOS REGISTRADOS"):
        if not events:
            return "Nenhum dado encontrado para registrar."
            
        card = f"✅ *{title}*\n\n"
        
        for i, ev in enumerate(events, 1):
            tipo = ev.get("tipo", "evento").upper()
            valor = ev.get("valor", 0)
            app = ev.get("app")
            km = ev.get("km", 0)
            pacotes = ev.get("pacotes", 0)
            desc = ev.get("descricao")
            cat = ev.get("categoria")
            tempo = ev.get("tempo_minutos", 0)
            
            # Emojis inteligentes baseados no tipo e categoria
            if ev.get("tipo") == "corrida":
                emoji = "💰"
            elif ev.get("tipo") == "espera":
                emoji = "⏳"
            elif ev.get("tipo") == "gasto":
                emoji = "⛽" if cat == "Essencial" else "🚬"
            else:
                emoji = "📝"
            
            card += f"{emoji} *{i}. {tipo}*\n"
            if cat: card += f"   • Categoria: {cat}\n"
            if tempo: card += f"   • Duração: {tempo} min\n"
            if app: card += f"   • App: {app}\n"
            if valor: card += f"   • Valor: R$ {valor:.2f}\n"
            if pacotes: card += f"   • Pacotes: {pacotes}\n"
            if km: card += f"   • KM: {km:.1f}\n"
            if desc and desc != "Print lido": card += f"   • Obs: {desc}\n"
            card += "\n"
            
        card += "🚀 Tudo salvo no seu histórico!"
        return card

    @staticmethod
    def format_summary(metrics: dict, title: str = "RESUMO DA OPERAÇÃO", analyst_insight: str = None):
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
