import datetime

class LogicService:
    @staticmethod
    def calculate_metrics(events: list):
        total_ganho = 0
        total_gastos = 0
        total_km = 0
        total_pacotes = 0
        
        for event in events:
            if event['tipo'] == 'corrida':
                total_ganho += event.get('valor', 0)
                total_km += event.get('km', 0)
                total_pacotes += event.get('pacotes', 0)
            elif event['tipo'] == 'gasto':
                total_gastos += event.get('valor', 0)
            elif event['tipo'] == 'ajuste':
                # Can be positive or negative
                total_ganho += event.get('valor', 0)

        lucro_liquido = total_ganho - total_gastos
        rs_km = total_ganho / total_km if total_km > 0 else 0
        rs_pacote = total_ganho / total_pacotes if total_pacotes > 0 else 0
        
        return {
            "total_ganho": total_ganho,
            "total_gastos": total_gastos,
            "lucro_liquido": lucro_liquido,
            "total_km": total_km,
            "total_pacotes": total_pacotes,
            "rs_km": rs_km,
            "rs_pacote": rs_pacote
        }

    @staticmethod
    def format_summary(metrics: dict):
        return (
            f"📊 *RESUMO DA OPERAÇÃO*\n\n"
            f"💰 Ganho Total: R$ {metrics['total_ganho']:.2f}\n"
            f"⛽ Gastos: R$ {metrics['total_gastos']:.2f}\n"
            f"💵 Lucro Líquido: R$ {metrics['lucro_liquido']:.2f}\n"
            f"🛣️ KM Rodados: {metrics['total_km']:.1f} km\n"
            f"📦 Pacotes: {metrics['total_pacotes']}\n\n"
            f"📈 Métricas:\n"
            f"- R$/km: R$ {metrics['rs_km']:.2f}\n"
            f"- R$/pacote: R$ {metrics['rs_pacote']:.2f}\n\n"
            f"Bom trabalho! Descansa que amanhã tem mais! 🚀"
        )
