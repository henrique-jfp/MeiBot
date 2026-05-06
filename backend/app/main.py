from fastapi import FastAPI, Request, BackgroundTasks
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
