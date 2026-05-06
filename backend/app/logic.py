import datetime

class LogicService:
    @staticmethod
    def calculate_metrics(events: list):
        total_ganho = 0
        total_gastos_essenciais = 0
        total_gastos_nao_essenciais = 0
        total_km = 0
        total_pacotes = 0
        
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

        total_gastos = total_gastos_essenciais + total_gastos_nao_essenciais
        lucro_liquido = total_ganho - total_gastos
        rs_km = total_ganho / total_km if total_km > 0 else 0
        rs_pacote = total_ganho / total_pacotes if total_pacotes > 0 else 0
        
        return {
            "total_ganho": total_ganho,
            "total_gastos_essenciais": total_gastos_essenciais,
            "total_gastos_nao_essenciais": total_gastos_nao_essenciais,
            "total_gastos": total_gastos,
            "lucro_liquido": lucro_liquido,
            "total_km": total_km,
            "total_pacotes": total_pacotes,
            "rs_km": rs_km,
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
            
            emoji = "💰" if ev.get("tipo") == "corrida" else "⛽" if ev.get("tipo") == "gasto" else "📝"
            
            card += f"{emoji} *{i}. {tipo}*\n"
            if cat: card += f"   • Categoria: {cat}\n"
            if app: card += f"   • App: {app}\n"
            if valor: card += f"   • Valor: R$ {valor:.2f}\n"
            if pacotes: card += f"   • Pacotes: {pacotes}\n"
            if km: card += f"   • KM: {km:.1f}\n"
            if desc and desc != "Print lido": card += f"   • Obs: {desc}\n"
            card += "\n"
            
        card += "🚀 Tudo salvo no seu histórico!"
        return card

    @staticmethod
    def format_summary(metrics: dict):
        return (
            f"📊 *RESUMO DA OPERAÇÃO*\n\n"
            f"💰 Ganho Total: R$ {metrics['total_ganho']:.2f}\n"
            f"⛽ Gastos Essenciais: R$ {metrics['total_gastos_essenciais']:.2f}\n"
            f"🚬 Gastos Não Essenciais: R$ {metrics['total_gastos_nao_essenciais']:.2f}\n"
            f"💵 Lucro Líquido: R$ {metrics['lucro_liquido']:.2f}\n"
            f"🛣️ KM Rodados: {metrics['total_km']:.1f} km\n"
            f"📦 Pacotes: {metrics['total_pacotes']}\n\n"
            f"📈 Métricas:\n"
            f"- R$/km: R$ {metrics['rs_km']:.2f}\n"
            f"- R$/pacote: R$ {metrics['rs_pacote']:.2f}\n\n"
            f"Bom trabalho! Descansa que amanhã tem mais! 🚀"
        )
