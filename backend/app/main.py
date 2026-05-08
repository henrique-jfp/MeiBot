from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from .ai_service import AIService
from .db import DBService
from .logic import LogicService
import base64
import datetime

app = FastAPI()
db = DBService()
ai = AIService()

@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        whatsapp_number = data.get("from")
        message_type = data.get("type") # 'text', 'image', 'audio'
        content = data.get("content")
        
        user = db.get_user_by_whatsapp(whatsapp_number)
        if not user:
            user = db.create_user(whatsapp_number)
        
        if not user.get("id"):
            return {"reply": "❌ Erro ao acessar o banco de dados. As tabelas foram criadas no Supabase?"}

        response_text = ""
        
        if message_type == "text":
            interpreted = await ai.interpret_message(content)
            print(f"DEBUG: AI Interpreted: {interpreted}")
            response_text = await process_interpreted_data(user, interpreted)
            
        elif message_type == "image":
            image_bytes = base64.b64decode(content)
            interpreted = await ai.process_image(image_bytes, "image/jpeg")
            print(f"DEBUG: Image AI Interpreted: {interpreted}")
            response_text = await process_interpreted_data(user, interpreted)
            
        elif message_type == "audio":
            audio_bytes = base64.b64decode(content)
            transcription = await ai.transcribe_audio(audio_bytes)
            print(f"DEBUG: Audio Transcription: {transcription}")
            interpreted = await ai.interpret_message(transcription)
            print(f"DEBUG: Audio AI Interpreted: {interpreted}")
            response_text = await process_interpreted_data(user, interpreted)
            response_text = f"🎙️ *Transcrição:* \"{transcription}\"\n\n{response_text}"

        return {"reply": response_text}
    except Exception as e:
        print(f"CRITICAL ERROR in handle_webhook: {e}")
        import traceback
        traceback.print_exc()
        return {"reply": f"❌ Ops! Tive um erro interno: {str(e)}"}

async def process_interpreted_data(user, interpreted):
    intencao = interpreted.get("intencao")
    user_id = user["id"]
    data_ref = interpreted.get("data_referencia")
    hora_inicio = interpreted.get("hora_inicio")
    hora_fim = interpreted.get("hora_fim")
    eventos = interpreted.get("eventos", [])
    
    # Lógica para lançamento retroativo ("Resumão combo")
    if data_ref:
        op = db.get_or_create_operation_by_date(user_id, data_ref, hora_inicio, hora_fim)
        for ev in eventos:
            db.add_event(user_id, op["id"], ev)
            
        if len(eventos) > 0:
            return LogicService.format_events_confirmation(eventos, f"RESUMO RETROATIVO: {data_ref}")
        else:
            return f"Entendi a data {data_ref}, mas não encontrei informações de gastos ou ganhos na mensagem."

    if intencao == "listar_porteiros":
        url = f"https://meibot.henriquedejesus.dev/porteiros/{user['whatsapp_number']}"
        return f"📋 Aqui está o seu mapeamento completo de porteiros: {url}"

    if intencao == "consultar_porteiro":
        info = interpreted.get("porteiro_info", {})
        res = db.get_porteiros_by_address(user_id, info.get("rua"), info.get("numero"))
        if not res:
            return f"Não encontrei nenhum porteiro mapeado para {info.get('rua')}, {info.get('numero')}."
        
        texto = f"🏢 *Porteiros em {info.get('rua')}, {info.get('numero')}:*\n"
        for p in res:
            texto += f"• {p['nome_porteiro']}"
            if p.get('turno'): texto += f" ({p['turno']})"
            if p.get('notas_predio'): texto += f"\n  📝 Nota: {p['notas_predio']}"
            texto += "\n"
        return texto

    if intencao == "cadastrar_porteiro":
        info = interpreted.get("porteiro_info", {})
        res = db.add_porteiro(user_id, info.get("rua"), info.get("numero"), info.get("nome"), info.get("turno"), info.get("notas"))
        if res == "DUPLICATE":
            return f"⚠️ O porteiro *{info.get('nome')}* já está mapeado para esse endereço."
        elif res:
            return f"✅ Porteiro *{info.get('nome')}* cadastrado com sucesso em {info.get('rua')}, {info.get('numero')}!"
        return "❌ Tive um erro ao cadastrar o porteiro. Tente novamente."

    if intencao == "corrigir_porteiro":
        info = interpreted.get("porteiro_info", {})
        rua = info.get("rua")
        numero = info.get("numero")
        nome_novo = info.get("nome")
        nome_busca = info.get("nome_antigo")
        
        # 1. Tenta achar pelo endereço exato se só tiver um lá
        if not nome_busca:
            existentes = db.get_porteiros_by_address(user_id, rua, numero)
            if len(existentes) == 1:
                nome_busca = existentes[0]["nome_porteiro"]
        
        # 2. Se falhar, tenta achar o registro original pelo NOME do porteiro (caso o endereço esteja errado)
        if not nome_busca and nome_novo:
            # Busca no banco qualquer registro desse porteiro para este usuário
            try:
                res_nome = db.supabase.table("mapeamento_porteiros").select("*").eq("user_id", user_id).ilike("nome_porteiro", f"%{nome_novo}%").execute()
                if res_nome.data:
                    # Usa o endereço e nome do registro encontrado como base para a correção
                    p_orig = res_nome.data[0]
                    res = db.update_porteiro(user_id, p_orig["rua"], p_orig["numero"], p_orig["nome_porteiro"], nome_novo, info.get("turno"), info.get("notas"))
                    # Se mandou rua/numero novos na correção, atualiza também
                    if rua or numero:
                        update_end = {}
                        if rua: update_end["rua"] = rua
                        if numero: update_end["numero"] = numero
                        db.supabase.table("mapeamento_porteiros").update(update_end).eq("id", p_orig["id"]).execute()
                    return f"✅ Cadastro de *{nome_novo}* corrigido e atualizado!"
            except:
                pass

        res = db.update_porteiro(user_id, rua, numero, nome_busca or nome_novo, nome_novo, info.get("turno"), info.get("notas"))
        if res:
            return f"✅ Cadastro de porteiros em {rua}, {numero} atualizado!"
        return f"❌ Não consegui localizar o porteiro para corrigir. Dica: Diga o nome que foi cadastrado errado."

    active_op = db.get_active_operation(user_id)
    
    if intencao == "resumo_semanal":
        events_curr = db.get_weekly_summary(user_id)
        ops_curr = db.get_operations_for_period(user_id, 7)
        metrics_curr = LogicService.calculate_metrics(events_curr, ops_curr)
        
        events_prev = db.get_previous_weekly_summary(user_id)
        metrics_prev = LogicService.calculate_metrics(events_prev, None)
        
        insight = await ai.generate_analyst_insight(metrics_curr, metrics_prev, "Semana Atual")
        return LogicService.format_summary(metrics_curr, "RESUMO SEMANAL SOLICITADO", insight)

    if intencao == "resumo_mensal":
        events_curr = db.get_monthly_summary(user_id)
        ops_curr = db.get_operations_for_period(user_id, 30)
        metrics_curr = LogicService.calculate_metrics(events_curr, ops_curr)
        
        events_prev = db.get_previous_monthly_summary(user_id)
        metrics_prev = LogicService.calculate_metrics(events_prev, None)
        
        insight = await ai.generate_analyst_insight(metrics_curr, metrics_prev, "Mês Atual")
        return LogicService.format_summary(metrics_curr, "RESUMO MENSAL SOLICITADO", insight)

    if intencao == "iniciar":
        if active_op:
            return "Você já tem uma operação ativa! Vamos trabalhar!"
        db.start_operation(user_id)
        return "🚀 Operação iniciada! Boa sorte nas entregas, parceiro!"
        
    if intencao == "encerrar":
        if not active_op:
            return "Nenhuma operação ativa encontrada."
        db.end_operation(active_op["id"])
        
        today = datetime.date.today()
        # Verifica se amanhã muda o mês (último dia do mês)
        is_last_day_of_month = (today + datetime.timedelta(days=1)).month != today.month
        is_first_day_of_month = today.day == 1
        is_saturday = today.weekday() == 5

        if is_last_day_of_month or is_first_day_of_month:
            events_curr = db.get_monthly_summary(user_id)
            ops_curr = db.get_operations_for_period(user_id, 30)
            metrics_curr = LogicService.calculate_metrics(events_curr, ops_curr)
            events_prev = db.get_previous_monthly_summary(user_id)
            metrics_prev = LogicService.calculate_metrics(events_prev, None)
            
            insight = await ai.generate_analyst_insight(metrics_curr, metrics_prev, "Mês")
            title = "RESUMO MENSAL ACUMULADO" if is_last_day_of_month else "RESUMO DO MÊS ENCERRADO"
            return LogicService.format_summary(metrics_curr, title, insight)
            
        elif is_saturday:
            events_curr = db.get_weekly_summary(user_id)
            ops_curr = db.get_operations_for_period(user_id, 7)
            metrics_curr = LogicService.calculate_metrics(events_curr, ops_curr)
            events_prev = db.get_previous_weekly_summary(user_id)
            metrics_prev = LogicService.calculate_metrics(events_prev, None)
            
            insight = await ai.generate_analyst_insight(metrics_curr, metrics_prev, "Semana")
            return LogicService.format_summary(metrics_curr, "RESUMO SEMANAL ACUMULADO", insight)
        else:
            return "🚀 Operação encerrada com sucesso! Bom descanso, parceiro. No sábado te envio o resumão da semana completa! 👊"
        
    if intencao == "pergunta":
        events_db = db.get_all_time_summary(user_id)
        context = str(events_db)
        return await ai.answer_question(context, interpreted.get("pergunta", ""))

    # intencao == "registro" para o dia atual
    if not active_op:
        if len(eventos) > 0:
            active_op = db.start_operation(user_id)
            for ev in eventos:
                db.add_event(user_id, active_op["id"], ev)
            return LogicService.format_events_confirmation(eventos, "OPERAÇÃO INICIADA")
        else:
            return "Hmm, não entendi. Você quer iniciar uma operação ou registrar algum ganho/gasto?"
    
    for ev in eventos:
        db.add_event(user_id, active_op["id"], ev)
    
    if len(eventos) > 0:
        return LogicService.format_events_confirmation(eventos, "DADOS REGISTRADOS")
    else:
        return "Hmm, não entendi o que era pra registrar."

@app.get("/porteiros/{whatsapp_number}", response_class=HTMLResponse)
async def list_porteiros_page(whatsapp_number: str):
    user = db.get_user_by_whatsapp(whatsapp_number)
    if not user:
        return "<h1>Usuário não encontrado</h1>"
    
    porteiros = db.get_all_porteiros(user["id"])
    
    # Agrupar por rua
    ruas = {}
    for p in porteiros:
        rua = p["rua"]
        if rua not in ruas:
            ruas[rua] = []
        ruas[rua].append(p)

    html_content = f"""
    <html>
        <head>
            <title>MeiBot - Mapeamento de Porteiros</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: sans-serif; background: #f4f4f9; color: #333; padding: 20px; }}
                h1 {{ color: #25D366; text-align: center; }}
                .rua-container {{ background: #fff; margin-bottom: 20px; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .rua-nome {{ font-weight: bold; font-size: 1.2em; border-bottom: 2px solid #25D366; margin-bottom: 10px; color: #128C7E; }}
                .item {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
                .item:last-child {{ border-bottom: none; }}
                .numero {{ font-weight: bold; color: #444; }}
                .nome {{ color: #128C7E; }}
                .nota {{ font-size: 0.9em; color: #666; font-style: italic; margin-top: 4px; }}
                .turno {{ font-size: 0.8em; background: #e1f5fe; color: #01579b; padding: 2px 6px; border-radius: 4px; margin-left: 5px; }}
            </style>
        </head>
        <body>
            <h1>📋 Meu Mapeamento</h1>
    """

    if not ruas:
        html_content += "<p style='text-align:center'>Nenhum porteiro cadastrado ainda.</p>"
    else:
        for rua in sorted(ruas.keys()):
            html_content += f"<div class='rua-container'><div class='rua-nome'>📍 {rua}</div>"
            # Ordena por número (convertendo para int se possível para ordem numérica correta)
            sorted_items = sorted(ruas[rua], key=lambda x: int(''.join(filter(str.isdigit, x['numero']))) if any(c.isdigit() for x in x['numero']) else x['numero'])
            
            for p in sorted_items:
                html_content += f"""
                <div class='item'>
                    <span class='numero'>nº {p['numero']}</span>: 
                    <span class='nome'>{p['nome_porteiro']}</span>
                    {f"<span class='turno'>{p['turno']}</span>" if p['turno'] else ""}
                    {f"<div class='nota'>📝 {p['notas_predio']}</div>" if p['notas_predio'] else ""}
                </div>
                """
            html_content += "</div>"

    html_content += "</body></html>"
    return html_content

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
