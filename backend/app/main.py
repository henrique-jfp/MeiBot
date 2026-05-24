from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from .ai_service import AIService
from .corrections import enrich_interpreted_payload, normalize_user_text
from .db import DBService
from .logic import LogicService
from .routes_claim.router import router as routes_claim_router
import base64
import datetime
import traceback
import json
import asyncio
from collections import defaultdict

app = FastAPI()
app.include_router(routes_claim_router)
db = DBService()
ai = AIService()
DEFAULT_IMAGE_MIME_TYPE = "image/jpeg"

# Lock management
user_locks = {}
def get_user_lock(user_id):
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

# Business Logic Handlers
def override_data_ref_from_text(content: str, data_ref: str):
    text = (content or "").lower()
    today = datetime.date.today()
    if "anteontem" in text: return (today - datetime.timedelta(days=2)).isoformat()
    if "ontem" in text: return (today - datetime.timedelta(days=1)).isoformat()
    if "hoje" in text: return today.isoformat()
    return data_ref

def to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default

async def build_operation_summary(operation: dict, title: str):
    operation_id = operation.get("id") if operation else None
    if not operation_id:
        return "Não encontrei uma operação válida para resumir."

    events = db.get_operation_summary(operation_id) or []
    if not events:
        return "Ainda não há eventos registrados para essa operação."

    metrics = LogicService.calculate_metrics_grouped(events, [operation])
    insight = await ai.generate_daily_insight(metrics.get("consolidado", {}))
    return LogicService.format_summary(metrics, title, insight)

def build_period_summary(events: list, operations: list, title: str):
    if not events:
        return None
    metrics = LogicService.calculate_metrics_grouped(events, operations or [])
    return LogicService.format_summary(metrics, title)

def get_porteiro_info(interpreted: dict):
    info = interpreted.get("porteiro_info") or {}
    return {
        "rua": str(info.get("rua") or "").strip(),
        "numero": str(info.get("numero") or "").strip(),
        "nome": str(info.get("nome") or "").strip(),
        "turno": str(info.get("turno") or "").strip(),
        "notas": str(info.get("notas") or "").strip(),
        "nome_antigo": str(info.get("nome_antigo") or "").strip(),
    }

def format_porteiro_endereco(rua: str, numero: str):
    if rua and numero:
        return f"{rua}, {numero}"
    return rua or numero or "endereço não informado"

def format_porteiro_item(porteiro: dict):
    extras = []
    if porteiro.get("turno"):
        extras.append(f"turno: {porteiro['turno']}")
    if porteiro.get("notas_predio"):
        extras.append(f"notas: {porteiro['notas_predio']}")
    extras_texto = f" ({' | '.join(extras)})" if extras else ""
    endereco = format_porteiro_endereco(porteiro.get("rua"), porteiro.get("numero"))
    nome = porteiro.get("nome_porteiro") or "Porteiro não informado"
    return f"- {endereco}: {nome}{extras_texto}"

def format_porteiro_listagem(porteiros: list, titulo: str):
    linhas = [titulo]
    linhas.extend(format_porteiro_item(porteiro) for porteiro in porteiros)
    return "\n".join(linhas)

def format_data_br(data_ref: str):
    if not data_ref:
        return "hoje"
    try:
        return datetime.date.fromisoformat(str(data_ref)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return str(data_ref)

BRT_TZ = datetime.timezone(datetime.timedelta(hours=-3))

def to_brt_date(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(BRT_TZ).date()

def month_last_day(date_obj: datetime.date):
    return (date_obj.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)

def correios_pay_date(event_date: datetime.date):
    if event_date.day <= 15:
        last_day = month_last_day(event_date)
        pay_day = 30 if last_day.day >= 30 else last_day.day
        return datetime.date(event_date.year, event_date.month, pay_day)
    next_month = (event_date.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return datetime.date(next_month.year, next_month.month, 15)

def shopee_pay_date(event_date: datetime.date):
    week_start = event_date - datetime.timedelta(days=event_date.weekday())
    return week_start + datetime.timedelta(days=10)

def calculate_next_receivables(events: list, now_date: datetime.date = None):
    if now_date is None:
        now_date = datetime.datetime.now(BRT_TZ).date()

    totals = {
        "correios": defaultdict(float),
        "shopee": defaultdict(float),
    }

    for ev in events or []:
        tipo = str(ev.get("tipo") or "").lower()
        if tipo not in {"ganho", "rota", "corrida", "faturamento"}:
            continue

        app_name = get_event_app_name(ev) or ""
        desc = ev.get("descricao") or ""
        lower = f"{app_name} {desc}".lower()
        is_correios = "correio" in lower
        is_shopee = "shopee" in lower
        if not (is_correios or is_shopee):
            continue

        event_date = to_brt_date(ev.get("timestamp")) or to_brt_date(ev.get("hora_inicio"))
        if not event_date:
            continue

        valor = to_float(ev.get("valor"))
        if is_correios:
            pay_date = correios_pay_date(event_date)
            totals["correios"][pay_date] += valor
        if is_shopee:
            pay_date = shopee_pay_date(event_date)
            totals["shopee"][pay_date] += valor

    def pick_next(bucket: dict):
        future = [d for d in bucket.keys() if d >= now_date]
        if not future:
            return None, 0.0
        next_date = min(future)
        return next_date, bucket.get(next_date, 0.0)

    correios_date, correios_total = pick_next(totals["correios"])
    shopee_date, shopee_total = pick_next(totals["shopee"])

    return {
        "correios": {
            "date": correios_date.isoformat() if correios_date else None,
            "total": round(correios_total, 2)
        },
        "shopee": {
            "date": shopee_date.isoformat() if shopee_date else None,
            "total": round(shopee_total, 2)
        }
    }

def get_event_app_name(evento: dict):
    app_info = evento.get("apps")
    if isinstance(app_info, dict) and app_info.get("nome"):
        return app_info.get("nome")
    return evento.get("app")

def select_event_for_correction(eventos: list, app_alvo: str = None, tipo_alvo: str = "ganho"):
    tipos_ganho = {"ganho", "rota", "corrida", "faturamento"}
    tipos_gasto = {"gasto", "despesa"}
    tipos_validos = tipos_gasto if tipo_alvo == "gasto" else tipos_ganho
    candidatos = [
        evento for evento in (eventos or [])
        if str(evento.get("tipo") or "").lower() in tipos_validos
        and str(evento.get("sub_tipo") or "").lower() != "espera_galpao"
    ]

    if app_alvo:
        app_alvo_norm = normalize_user_text(app_alvo)
        candidatos = [
            evento for evento in candidatos
            if normalize_user_text(get_event_app_name(evento) or "") == app_alvo_norm
        ]

    if len(candidatos) == 1:
        return candidatos[0], None
    if len(candidatos) > 1:
        return None, "MULTIPLE"

    if not app_alvo and len(eventos or []) == 1:
        return (eventos or [None])[0], None

    return None, None

def build_correction_changes(campos: dict):
    mudancas = []
    # Mapeamento amigável para o log de mudanças
    labels = {
        "hora_inicio": "horário de início",
        "hora_inicio_rota": "horário de início da rota",
        "hora_chegada_galpao": "chegada no galpão",
        "hora_saida_galpao": "saída do galpão",
        "hora_fim": "horário de fim",
        "hora_fim_operacao": "término da operação",
        "valor": "valor",
        "km": "km",
        "pacotes": "pacotes"
    }
    
    for key, label in labels.items():
        if key in campos:
            val = campos[key]
            if key == "valor":
                mudancas.append(f"{label}: {LogicService.format_brl(val)}")
            elif key == "km":
                mudancas.append(f"{label}: {LogicService.format_decimal(val)} km")
            elif key == "pacotes":
                mudancas.append(f"{label}: {int(val)}")
            else:
                mudancas.append(f"{label}: {val}")
    return mudancas

async def process_interpreted_data(user, interpreted):
    intencao = interpreted.get("intencao")
    user_id = user["id"]
    whatsapp = user["whatsapp_number"]
    data_ref = interpreted.get("data_referencia")
    if data_ref == "null": data_ref = None
    eventos_brutos = interpreted.get("eventos", [])

    if intencao == "iniciar":
        active_op = db.get_active_operation(user_id)
        if active_op and active_op.get("status") == "ativa":
            return "🚀 A operação de hoje já está ativa, parceiro!"
        db.start_operation(user_id)
        return "🚀 Operação iniciada! Boa sorte nas entregas, parceiro!"

    if intencao == "encerrar":
        active_op = db.get_active_operation(user_id)
        if not active_op or not active_op.get("id"):
            return "Não encontrei uma operação ativa para encerrar."
        ended_op = db.end_operation(active_op["id"]) or active_op
        return await build_operation_summary(ended_op, "RESUMO DA OPERAÇÃO")

    if intencao == "resumo_diario":
        active_op = db.get_active_operation(user_id)
        if not active_op or not active_op.get("id"):
            return "Ainda não encontrei dados suficientes de hoje para resumir."
        return await build_operation_summary(active_op, "RESUMO DO DIA")

    if intencao == "resumo_semanal":
        weekly_events = db.get_weekly_summary(user_id) or []
        weekly_ops = db.get_operations_for_period(user_id, 7) or []
        return build_period_summary(weekly_events, weekly_ops, "RESUMO SEMANAL") or "Ainda não há dados suficientes desta semana."

    if intencao == "resumo_mensal":
        monthly_events = db.get_monthly_summary(user_id) or []
        monthly_ops = db.get_operations_for_period(user_id, 30) or []
        return build_period_summary(monthly_events, monthly_ops, "RESUMO MENSAL") or "Ainda não há dados suficientes deste mês."

    if intencao == "pergunta":
        question = (interpreted.get("pergunta") or "").strip()
        if not question:
            return "Não consegui identificar sua pergunta no áudio. Tente novamente."
        context_events = db.get_all_time_summary(user_id) or []
        context_ops = db.get_operations_for_period(user_id, 30) or []
        metrics = LogicService.calculate_metrics_grouped(context_events, context_ops)
        context = json.dumps(metrics, ensure_ascii=False)
        return await ai.answer_question(context, question)

    if intencao == "listar_porteiros":
        porteiros = db.get_all_porteiros(user_id) or []
        if not porteiros:
            return "Ainda não há porteiros mapeados."
        return format_porteiro_listagem(porteiros, "Porteiros mapeados:")

    if intencao == "consultar_porteiro":
        porteiro_info = get_porteiro_info(interpreted)
        rua = porteiro_info["rua"]
        numero = porteiro_info["numero"]
        if not rua or not numero:
            return "Para consultar porteiro, me diga a rua e o número do prédio."
        porteiros = db.get_porteiros_by_address(user_id, rua, numero) or []
        if not porteiros:
            return f"Não encontrei porteiros mapeados em {format_porteiro_endereco(rua, numero)}."
        titulo = f"Porteiros em {format_porteiro_endereco(rua, numero)}:"
        return format_porteiro_listagem(porteiros, titulo)

    if intencao == "cadastrar_porteiro":
        porteiro_info = get_porteiro_info(interpreted)
        rua = porteiro_info["rua"]
        numero = porteiro_info["numero"]
        nome = porteiro_info["nome"]
        turno = porteiro_info["turno"] or None
        notas = porteiro_info["notas"] or None
        if not rua or not numero or not nome:
            return "Para cadastrar um porteiro, preciso da rua, número e nome."
        created = db.add_porteiro(user_id, rua, numero, nome, turno=turno, notas=notas)
        endereco = format_porteiro_endereco(rua, numero)
        if created == "DUPLICATE":
            return f"Esse porteiro já está mapeado em {endereco}."
        if not created:
            return "Não consegui salvar o porteiro agora. Tente novamente."
        detalhes = []
        if turno:
            detalhes.append(f"turno: {turno}")
        if notas:
            detalhes.append(f"notas: {notas}")
        detalhes_texto = f" ({' | '.join(detalhes)})" if detalhes else ""
        return f"Porteiro cadastrado em {endereco}: {nome}{detalhes_texto}."

    if intencao == "corrigir_porteiro":
        porteiro_info = get_porteiro_info(interpreted)
        rua = porteiro_info["rua"]
        numero = porteiro_info["numero"]
        nome_antigo = porteiro_info["nome_antigo"]
        novo_nome = porteiro_info["nome"] or None
        novo_turno = porteiro_info["turno"] or None
        novas_notas = porteiro_info["notas"] or None
        if not rua or not numero:
            return "Para corrigir um porteiro, preciso da rua e do número do prédio."
        porteiros = db.get_porteiros_by_address(user_id, rua, numero) or []
        endereco = format_porteiro_endereco(rua, numero)
        if not porteiros:
            return f"Não encontrei porteiros mapeados em {endereco}."
        if not nome_antigo:
            if len(porteiros) == 1:
                nome_antigo = porteiros[0].get("nome_porteiro")
            else:
                nomes_porteiros = ", ".join([p.get('nome_porteiro', '') for p in porteiros])
                return (f"Encontrei mais de um porteiro em {endereco}: {nomes_porteiros}. "
                        "Para corrigir, por favor, me diga o nome antigo e o novo. "
                        "Exemplo: 'Corrigir o porteiro Carlos para José na rua X, 123'.")
        if not any([novo_nome, novo_turno, novas_notas]):
            return "Não identifiquei o que você quer corrigir no cadastro do porteiro."
        updated = db.update_porteiro(
            user_id,
            rua,
            numero,
            nome_antigo,
            novo_nome=novo_nome,
            novo_turno=novo_turno,
            novas_notas=novas_notas,
        )
        if updated is None:
            return "Não consegui atualizar o porteiro agora. Tente novamente."
        if not updated:
            return f"Não encontrei o porteiro {nome_antigo} em {endereco}."
        mudancas = []
        if novo_nome:
            mudancas.append(f"nome: {novo_nome}")
        if novo_turno:
            mudancas.append(f"turno: {novo_turno}")
        if novas_notas:
            mudancas.append(f"notas: {novas_notas}")
        return f"Porteiro atualizado em {endereco}: {', '.join(mudancas)}."

    if intencao == "excluir_porteiro":
        porteiro_info = get_porteiro_info(interpreted)
        rua = porteiro_info["rua"]
        numero = porteiro_info["numero"]
        nome = porteiro_info["nome"]
        if not rua or not numero:
            return "Para excluir um porteiro ou prédio, preciso da rua e do número."
        
        deleted = db.delete_porteiro(user_id, rua, numero, nome if nome else None)
        endereco = format_porteiro_endereco(rua, numero)
        
        if deleted is None:
            return "Não consegui realizar a exclusão agora. Tente novamente."
        
        if not deleted:
            msg = f"Não encontrei registros para excluir em {endereco}"
            if nome: msg += f" com o nome {nome}"
            return msg + "."
            
        unidade = "porteiro" if nome else "prédio/endereço"
        return f"Sucesso! O {unidade} em {endereco} foi removido do seu mapeamento."

    if intencao in ("corrigir_registro", "excluir_registro"):
        correcao_info = interpreted.get("correcao_info") or {}
        campos = correcao_info.get("campos") or {}
        if intencao == "corrigir_registro" and not campos:
            return "Não identifiquei quais dados da operação você quer corrigir."

        data_alvo = data_ref or datetime.date.today().isoformat()
        operacao = db.get_operation_by_date(user_id, data_alvo)
        if not operacao and not data_ref:
            operacao = db.get_active_operation(user_id)
            if operacao and operacao.get("data"):
                data_alvo = operacao.get("data")
        if not operacao:
            return f"Não encontrei uma operação em {format_data_br(data_alvo)} para corrigir."

        app_alvo = correcao_info.get("app")
        eventos_operacao = db.get_operation_summary(operacao["id"]) or []
        evento_alvo, status_selecao = select_event_for_correction(
            eventos_operacao,
            app_alvo,
            correcao_info.get("tipo_alvo") or "ganho",
        )
        if status_selecao == "MULTIPLE":
            alvo = app_alvo or "essa operação"
            return f"Encontrei mais de um registro compatível de {alvo} em {format_data_br(data_alvo)}. Me diga qual lançamento devo corrigir."

        if not evento_alvo:
            alvo = app_alvo or "operação"
            return f"Não encontrei um registro compatível de {alvo} em {format_data_br(data_alvo)} para realizar a ação."

        if intencao == "excluir_registro":
            success = db.delete_event(evento_alvo["id"])
            if success:
                alvo = get_event_app_name(evento_alvo) or "registro"
                return f"Lançamento de {alvo} excluído com sucesso do dia {format_data_br(data_alvo)}."
            return "Não consegui excluir o registro agora. Tente novamente."

        evento_corrigido = None
        campos_evento = {
            key: value for key, value in campos.items()
            if key in {
                "hora_inicio", "hora_fim", "valor", "km", "pacotes", 
                "hora_inicio_rota", "hora_fim_operacao", 
                "hora_chegada_galpao", "hora_saida_galpao"
            }
        }
        if campos_evento and evento_alvo:
            evento_corrigido = db.update_event(evento_alvo["id"], campos_evento, data_alvo)

        operacao_corrigida = None
        if correcao_info.get("atualizar_operacao"):
            operacao_corrigida = db.update_operation_times(
                operacao["id"],
                date_str=data_alvo,
                hora_inicio=campos.get("hora_inicio"),
                hora_fim=campos.get("hora_fim"),
            )

        if not evento_corrigido and not operacao_corrigida:
            alvo = app_alvo or "operação"
            return f"Não encontrei um registro compatível de {alvo} em {format_data_br(data_alvo)} para corrigir."

        mudancas = build_correction_changes(campos)
        alvo = app_alvo or "operação"
        return f"Registro corrigido em {format_data_br(data_alvo)} ({alvo}): {', '.join(mudancas)}."

    if data_ref: active_op = db.get_or_create_operation_by_date(user_id, data_ref)
    else:
        active_op = db.get_active_operation(user_id)
        if not active_op and len(eventos_brutos) > 0: active_op = db.start_operation(user_id)
    
    eventos_processados = []
    for ev in eventos_brutos:
        app_name_raw = str(ev.get("app") or "").strip()
        app_info = db.get_app_by_name(app_name_raw) if app_name_raw and app_name_raw.lower() != "none" else None
        
        # Se for ganho e tiver App, aplica automações do banco
        if str(ev.get("tipo")).lower() == "ganho" and app_info:
            ev["app"] = app_info["nome"]
            
            # Automação de Valor e KM (Preenche se a IA não pegou nada explícito)
            val_ia = to_float(ev.get("valor"))
            pac_ia = to_float(ev.get("pacotes"))
            
            if val_ia == 0 or val_ia == pac_ia: # Se não disse valor ou confundiu valor com pacotes
                if app_info.get("tipo_remuneracao") == "rota":
                    ev["valor"] = to_float(app_info.get("valor_base"))
                elif app_info.get("tipo_remuneracao") == "pacote":
                    ev["valor"] = pac_ia * to_float(app_info.get("valor_base", 2.0))
            
            # Adiciona bônus se houver
            ev["valor"] = to_float(ev.get("valor")) + to_float(ev.get("valor_extra"))
            
            if to_float(ev.get("km")) == 0:
                # Se for Shopee e não informou KM, usa o padrão histórico (60km) ou do banco
                if "shopee" in app_info["nome"].lower():
                    ev["km"] = 60.0
                elif "correio" in app_info["nome"].lower():
                    ev["km"] = 20.0
            
            # Automação de Salário de Ajudante
            if app_info.get("entregador_padrao_id"):
                entregador = db.get_entregador_by_id(app_info["entregador_padrao_id"])
                if entregador:
                    salario_gasto = {
                        "tipo": "gasto",
                        "valor": to_float(entregador.get("valor_diaria")),
                        "categoria": "Essencial",
                        "descricao": f"Pagamento ajudante {entregador['nome']} (Auto)",
                        "app": app_info["nome"]
                    }
                    if data_ref: salario_gasto["data_referencia"] = data_ref
                    db.add_event(user_id, active_op["id"], salario_gasto)
                    eventos_processados.append(salario_gasto)

        if active_op:
            h_chegada = ev.get("hora_chegada_galpao")
            h_saida_galpao = ev.get("hora_saida_galpao")
            h_inicio_rota = ev.get("hora_inicio_rota")
            h_fim_espera = h_saida_galpao or h_inicio_rota
            if h_chegada and h_fim_espera:
                app_for_wait = ev.get("app")
                wait_event = {
                    "tipo": "registro",
                    "sub_tipo": "espera_galpao",
                    "hora_inicio": h_chegada,
                    "hora_fim": h_fim_espera,
                    "descricao": f"Espera no galpao ({app_for_wait})" if app_for_wait else "Espera no galpao",
                    "app": app_for_wait
                }
                if data_ref: wait_event["data_referencia"] = data_ref
                db.add_event(user_id, active_op["id"], wait_event)
                eventos_processados.append(wait_event)

            if data_ref: ev["data_referencia"] = data_ref
            db.add_event(user_id, active_op["id"], ev)
            eventos_processados.append(ev)
    if intencao == "registro": return LogicService.format_events_confirmation(eventos_processados, "DADOS REGISTRADOS", data_ref)
    if intencao == "pedir_link_dashboard": return f"📊 Dashboard: https://meibot.henriquedejesus.dev/dashboard/{whatsapp}"
    return f"Entendi sua mensagem como '{intencao}', mas essa ação ainda não está conectada no backend."

def decode_base64_content(content: str):
    if not content:
        raise ValueError("Recebi a mídia vazia. Tente enviar novamente.")
    try:
        return base64.b64decode(content)
    except Exception as exc:
        raise ValueError("Não consegui ler a mídia enviada. Tente reenviar.") from exc

async def build_interpreted_payload(data: dict):
    message_type = data.get("type")
    content = data.get("content")

    if message_type == "text":
        text = (content or "").strip()
        if not text:
            raise ValueError("Recebi um texto vazio. Tente enviar novamente.")
        interpreted = await ai.interpret_message(text)
        interpreted["data_referencia"] = override_data_ref_from_text(text, interpreted.get("data_referencia"))
        return enrich_interpreted_payload(text, interpreted)

    if message_type == "audio":
        audio_bytes = decode_base64_content(content)
        transcription = (await ai.transcribe_audio(audio_bytes) or "").strip()
        if not transcription:
            raise ValueError("Não consegui transcrever o áudio. Tente enviar em texto.")
        interpreted = await ai.interpret_message(transcription)
        interpreted["data_referencia"] = override_data_ref_from_text(transcription, interpreted.get("data_referencia"))
        return enrich_interpreted_payload(transcription, interpreted)

    if message_type == "image":
        image_bytes = decode_base64_content(content)
        mime_type = data.get("mime_type") or DEFAULT_IMAGE_MIME_TYPE
        return await ai.process_image(image_bytes, mime_type)

    raise ValueError("Tipo de mensagem não suportado ainda.")

# API Endpoints
@app.post("/webhook")
async def handle_webhook(request: Request):
    try:
        data = await request.json()
        whatsapp_number = data.get("from")
        user = db.get_user_by_whatsapp(whatsapp_number)
        if not user: user = db.create_user(whatsapp_number)
        lock = get_user_lock(user["id"])
        async with lock:
            interpreted = await build_interpreted_payload(data)
            print(f"[WEBHOOK] tipo={data.get('type')} intencao={interpreted.get('intencao')} eventos={len(interpreted.get('eventos', []))}")
            response_text = await process_interpreted_data(user, interpreted)
        return {"reply": response_text}
    except ValueError as e:
        return {"reply": str(e)}
    except Exception as e:
        traceback.print_exc()
        return {"reply": "⚠️ Tive uma instabilidade. Tente de novo."}

@app.get("/api/dashboard/{whatsapp_number}")
async def get_dashboard_data(whatsapp_number: str, analysis_id: str = None):
    user = db.get_user_by_whatsapp(whatsapp_number)
    if not user: return JSONResponse({"error": "User not found"}, status_code=404)
    user_id = user["id"]
    porteiros = db.get_all_porteiros(user_id)
    history = db.get_analysis_history(user_id, limit=30)

    def _calc_period_range(analysis):
        metrics = analysis.get("metrics") or {}
        start_iso = metrics.get("period_start")
        end_iso = metrics.get("period_end")
        if start_iso and end_iso:
            try:
                return datetime.date.fromisoformat(start_iso), datetime.date.fromisoformat(end_iso)
            except Exception:
                pass

        created_at = analysis.get("created_at")
        periodo_tipo = analysis.get("periodo_tipo")
        if not created_at or not periodo_tipo:
            return None, None
        try:
            created_dt = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            return None, None
        if periodo_tipo == "semanal":
            day = created_dt.weekday()
            start = (created_dt - datetime.timedelta(days=day)).date()
            end = start + datetime.timedelta(days=6)
            return start, end
        if periodo_tipo == "mensal":
            start = created_dt.replace(day=1).date()
            end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
            return start, end
        return None, None
    if analysis_id:
        res = db.supabase.table("historico_analises").select("*").eq("id", analysis_id).execute()
        if res.data:
            analysis = res.data[0]
            start_date, end_date = _calc_period_range(analysis)
            daily_list = []
            if start_date and end_date:
                start_iso = start_date.isoformat()
                end_iso = (end_date + datetime.timedelta(days=1)).isoformat()
                ev_hist = db.supabase.table("eventos").select("*")\
                    .eq("user_id", user_id)\
                    .gte("timestamp", start_iso)\
                    .lt("timestamp", end_iso)\
                    .execute().data
                daily_perf = {ev["timestamp"].split("T")[0]: 0 for ev in ev_hist if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]}
                for ev in ev_hist:
                    if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]:
                        daily_perf[ev["timestamp"].split("T")[0]] += float(ev.get("valor", 0))
                daily_list = sorted([{"date": d, "ganho": g} for d, g in daily_perf.items()], key=lambda x: x["date"])

            return {"user": user, "metrics": analysis["metrics"], "insight": analysis["insight"], "is_live": False, "created_at": analysis["created_at"], "periodo_tipo": analysis.get("periodo_tipo"), "daily_performance": daily_list, "history": history, "porteiros": porteiros, "next_receivables": None}
    today = datetime.date.today()
    start_iso, end_iso = (today.replace(day=1).isoformat(), (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1).isoformat())
    ev_live = db.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", start_iso + "T00:00:00Z").lt("timestamp", end_iso + "T00:00:00Z").execute().data
    op_live = db.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).gte("data", start_iso).lt("data", end_iso).execute().data
    metrics_live = LogicService.calculate_metrics_grouped(ev_live, op_live)
    next_receivables = calculate_next_receivables(ev_live)
    daily_perf = {ev["timestamp"].split("T")[0]: 0 for ev in ev_live if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]}
    for ev in ev_live:
        if str(ev.get("tipo", "")).lower() in ["ganho", "rota"]: daily_perf[ev["timestamp"].split("T")[0]] += float(ev.get("valor", 0))
    daily_list = sorted([{"date": d, "ganho": g} for d, g in daily_perf.items()], key=lambda x: x['date'])
    return {"user": user, "metrics": metrics_live, "daily_performance": daily_list, "is_live": True, "history": history, "created_at": datetime.datetime.now().isoformat(), "periodo_tipo": None, "porteiros": porteiros, "next_receivables": next_receivables}

@app.get("/dashboard/{whatsapp_number}", response_class=HTMLResponse)
async def dashboard_page(whatsapp_number: str):
    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>MeiBot - Dashboard Analítico</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Source+Sans+3:wght@400;500;600;700&display=swap');
            :root {
                --bg: #f7f5f2;
                --card: rgba(255, 255, 255, 0.92);
                --card-border: #e6e4df;
                --text: #0f172a;
                --muted: #64748b;
                --brand-teal: #0f766e;
                --brand-teal-soft: rgba(15, 118, 110, 0.12);
                --brand-rose: #e11d48;
                --shadow-soft: 0 14px 32px rgba(15, 23, 42, 0.08);
                --shadow-tight: 0 6px 18px rgba(15, 23, 42, 0.08);
            }
            body {
                font-family: 'Source Sans 3', sans-serif;
                background: var(--bg);
                color: var(--text);
                overflow-x: hidden;
            }
            body::before {
                content: '';
                position: fixed;
                inset: 0;
                z-index: -1;
                background:
                    radial-gradient(1200px 600px at 15% 0%, rgba(15, 118, 110, 0.10), transparent 60%),
                    radial-gradient(900px 600px at 80% 10%, rgba(192, 132, 29, 0.10), transparent 55%),
                    linear-gradient(180deg, rgba(255, 255, 255, 0.85), rgba(247, 245, 242, 0.95));
            }
            h1, h2, h3, h4, h5 {
                font-family: 'Space Grotesk', sans-serif;
                letter-spacing: -0.01em;
            }
            .card {
                background-color: var(--card);
                border-radius: 1rem;
                border: 1px solid var(--card-border);
                box-shadow: var(--shadow-soft);
                backdrop-filter: blur(6px);
            }
            .metric-card {
                box-shadow: var(--shadow-tight);
                transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
            }
            .metric-card:hover {
                transform: translateY(-2px);
                border-color: rgba(15, 118, 110, 0.25);
                box-shadow: 0 18px 36px rgba(15, 23, 42, 0.12);
            }
            .metric-label {
                letter-spacing: 0.08em;
            }
            .metric-value {
                font-size: clamp(1.25rem, 1.6vw, 1.75rem);
            }
            .tooltip-container { position: relative; display: inline-flex; align-items: center; gap: 4px; }
            .tooltip { display: none; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); margin-bottom: 8px; background-color: #1e293b; color: white; padding: 10px; border-radius: 8px; font-size: 11px; width: 240px; text-align: center; z-index: 100; font-weight: 500; pointer-events: none; }
            .tooltip-container:hover .tooltip { display: block; }
            .history-item { transition: all 0.2s; }
            #sidebar {
                background: rgba(255, 255, 255, 0.9);
                box-shadow: 12px 0 32px rgba(15, 23, 42, 0.06);
            }
            .brand-icon {
                background: linear-gradient(135deg, #0f766e, #0e7490);
                box-shadow: 0 10px 24px rgba(15, 118, 110, 0.25);
            }
            .surface-warm {
                background: linear-gradient(135deg, rgba(255, 244, 225, 0.9), rgba(255, 255, 255, 0.9));
                border-color: rgba(192, 132, 29, 0.18);
            }
            .app-card {
                position: relative;
                background: rgba(255, 255, 255, 0.92);
                border: 1px solid var(--card-border);
                border-radius: 16px;
                box-shadow: var(--shadow-tight);
                transition: transform 0.2s ease, border-color 0.2s ease;
            }
            .app-card::before {
                content: '';
                position: absolute;
                inset: 0 0 auto 0;
                height: 3px;
                background: var(--app-accent, var(--brand-teal));
                border-radius: 16px 16px 0 0;
            }
            .app-card:hover {
                transform: translateY(-2px);
                border-color: var(--app-accent-border, rgba(15, 118, 110, 0.25));
            }
            .app-title {
                color: var(--app-accent, var(--brand-teal));
            }
            .app-pill {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 2px 8px;
                border-radius: 999px;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                background: var(--app-accent-soft, rgba(15, 118, 110, 0.12));
                color: var(--app-accent, var(--brand-teal));
                border: 1px solid var(--app-accent-border, rgba(15, 118, 110, 0.2));
            }
            .app-pill .dot {
                width: 6px;
                height: 6px;
                border-radius: 999px;
                background: var(--app-accent-2, var(--app-accent, var(--brand-teal)));
            }
            .pay-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                gap: 16px;
            }
            .pay-card {
                position: relative;
                overflow: hidden;
                border-radius: 18px;
                padding: 20px 22px;
                background: #ffffff;
                box-shadow: var(--shadow-soft);
            }
            .pay-card::after {
                content: "";
                position: absolute;
                inset: 0;
                opacity: 0.12;
                background: radial-gradient(120% 120% at 100% 0%, currentColor 0%, transparent 60%);
                pointer-events: none;
            }
            .pay-head {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
            }
            .pay-badge {
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                padding: 6px 10px;
                border-radius: 999px;
                border: 1px solid transparent;
            }
            .pay-date {
                font-size: 11px;
                font-weight: 600;
                color: var(--muted);
            }
            .pay-value {
                font-family: 'Space Grotesk', sans-serif;
                font-size: 28px;
                font-weight: 700;
                margin-top: 12px;
            }
            .pay-sub {
                font-size: 11px;
                font-weight: 600;
                color: var(--muted);
                margin-top: 4px;
            }
            .pay-card.correios {
                color: #0047BB;
                border: 1px solid #FFE066;
                border-bottom: 4px solid #0047BB;
                background: linear-gradient(180deg, #ffffff 0%, #FFE066 100%);
            }
            .pay-card.correios .pay-badge {
                color: #ffd32c;
                background: #0047BB;
                border-color: #003388;
            }
            .pay-card.correios .pay-value {
                color: #0047BB;
            }
            .pay-card.correios .pay-date,
            .pay-card.correios .pay-sub {
                color: #0047BB;
            }
            .pay-card.shopee {
                color: #EE4D2D;
                border: 1px solid #FFE8E1;
                border-bottom: 4px solid #EE4D2D;
                background: linear-gradient(180deg, #ffffff 0%, #FFE8E1 100%);
            }
            .pay-card.shopee .pay-badge {
                color: #EE4D2D;
                background: rgba(238, 77, 45, 0.12);
                border-color: #FFD1C7;
            }
            .pay-card.shopee .pay-date,
            .pay-card.shopee .pay-sub {
                color: #EE4D2D;
            }

        </style>
    </head>
    <body class="flex flex-col lg:flex-row min-h-screen">
        <aside id="sidebar" class="w-full lg:w-80 bg-white/95 backdrop-blur border-b lg:border-r border-slate-200 p-6 flex-shrink-0 z-50 sticky top-0 lg:h-screen lg:overflow-y-auto">
            <div class="flex items-center justify-between mb-8">
                <div class="flex items-center gap-3"><div class="w-10 h-10 rounded-lg flex items-center justify-center text-white brand-icon"><i class="fa-solid fa-bolt"></i></div><div><h1 class="font-bold text-lg">MeiBot</h1><p class="text-xs text-slate-500 font-medium">Dashboard Analítico</p></div></div>
                <button id="btn-sidebar" onclick="toggleSidebar()" class="lg:hidden w-10 h-10 rounded-lg border border-slate-200 text-slate-500 flex items-center justify-center hover:bg-slate-50" aria-label="Abrir menu">
                    <i class="fa-solid fa-bars"></i>
                </button>
            </div>
            <div id="sidebar-content" class="hidden lg:block">
                <div class="mb-6"><p class="text-[11px] font-bold text-slate-400 uppercase mb-3">Navegação</p><div class="flex flex-row lg:flex-col gap-2"><button id="btn-nav-performance" onclick="showSection('performance')" class="flex items-center gap-3 p-2.5 rounded-lg bg-teal-50 text-teal-700 font-semibold text-sm border border-teal-100 w-full text-left"><i class="fa-solid fa-chart-pie w-4"></i> Performance</button><button id="btn-nav-porteiros" onclick="showSection('porteiros')" class="flex items-center gap-3 p-2.5 rounded-lg bg-transparent text-slate-600 font-medium text-sm hover:bg-slate-50 w-full text-left"><i class="fa-solid fa-map-location-dot w-4"></i> Porteiros</button></div></div>
                <p class="text-[11px] font-bold text-slate-400 uppercase mb-3">Histórico</p><nav id="history-list" class="space-y-2"></nav>
            </div>
        </aside>

        <main class="flex-grow p-5 md:p-8 space-y-6 w-full max-w-7xl mx-auto">
            <header class="border-b border-slate-200 pb-5"><h2 class="text-2xl md:text-3xl font-bold" id="main-title">Visão Geral</h2><p id="txt-periodo" class="text-slate-500 text-sm mt-1">Carregando...</p></header>

            <div id="section-performance" class="space-y-6">
                <!-- METRICS GRID -->
                <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div class="card metric-card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">Faturamento Bruto</p><p id="txt-bruto" class="font-bold metric-value">R$ 0,00</p></div>
                    <div class="card metric-card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">Saldo Líquido</p><p id="txt-saldo" class="font-bold metric-value text-teal-700">R$ 0,00</p></div>
                    <div class="card metric-card p-5"><div class="tooltip-container"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">Saldo c/ Provisão</p><i class="fa-solid fa-circle-info text-[10px] text-slate-300"></i><span class="tooltip">Seu saldo líquido menos R$ 0,20 por KM rodado para cobrir custos de manutenção futuros.</span></div><p id="txt-saldo-provisao" class="font-bold metric-value text-sky-700">R$ 0,00</p></div>
                    <div class="card metric-card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">KM Total</p><p id="txt-km-total" class="font-bold metric-value">0 km</p></div>
                    <div class="card metric-card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">Pacotes Entregues</p><p id="txt-pacotes-total" class="font-bold metric-value">0</p></div>
                    <div class="card metric-card p-5"><div class="tooltip-container"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">Pacotes / Hora (Rua)</p><i class="fa-solid fa-circle-info text-[10px] text-slate-300"></i><span class="tooltip">Quantos pacotes você entrega por hora efetivamente na rua, descontando o tempo de espera no galpão.</span></div><p id="txt-pacotes-hora-rua" class="font-bold metric-value">0/h</p></div>
                    <div class="card metric-card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">Eficiência (R$/KM)</p><p id="txt-eficiencia" class="font-bold metric-value">R$ 0,00</p></div>
                    <div class="card metric-card p-5"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">Eficiência (R$/Hora)</p><p id="txt-ganho-hora" class="font-bold metric-value">R$ 0,00</p></div>
                    <div class="card metric-card p-5"><div class="tooltip-container"><p class="text-slate-500 text-[10px] font-bold uppercase metric-label">Ganho Bruto / Hora (Rua)</p><i class="fa-solid fa-circle-info text-[10px] text-slate-300"></i><span class="tooltip">Faturamento bruto dividido apenas pelas horas em rota (descontando espera no galpão). Mostra sua produtividade real enquanto está entregando.</span></div><p id="txt-ganho-hora-rua" class="font-bold metric-value text-violet-700">R$ 0,00/h</p></div>
                </div>

                <div id="next-receivables-section" class="pay-grid" style="display:none;">
                    <article class="pay-card correios">
                        <div class="pay-head">
                            <div class="pay-badge">Correios</div>
                            <div id="txt-next-correios-date" class="pay-date">Proximo recebimento: --/--</div>
                        </div>
                        <div id="txt-next-correios-valor" class="pay-value">R$ 0,00</div>
                        <div class="pay-sub">Valor bruto previsto</div>
                    </article>
                    <article class="pay-card shopee">
                        <div class="pay-head">
                            <div class="pay-badge">Shopee</div>
                            <div id="txt-next-shopee-date" class="pay-date">Proximo recebimento: --/--</div>
                        </div>
                        <div id="txt-next-shopee-valor" class="pay-value">R$ 0,00</div>
                        <div class="pay-sub">Valor bruto previsto</div>
                    </article>
                </div>

                <!-- CHARTS & DETAILS -->
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div id="daily-chart-container" class="lg:col-span-2 card p-6"><h3 class="font-bold text-sm mb-6 uppercase">Performance Diária</h3><div class="h-[300px]"><canvas id="chartDaily"></canvas></div></div>
                    <div id="apps-chart-container" class="lg:col-span-2 card p-6" style="display:none;"><h3 class="font-bold text-sm mb-6 uppercase">Performance por Período</h3><div class="h-[300px]"><canvas id="chartApps"></canvas></div></div>
                    <div class="card p-6 flex flex-col"><h3 class="font-bold text-sm mb-6 uppercase">Distribuição de Gastos</h3><div class="h-[200px] mb-6"><canvas id="chartGastos"></canvas></div><div class="space-y-2 text-[10px] font-bold uppercase"><div class="flex justify-between"><span>Essenciais</span><span id="txt-essencial">R$ 0,00</span></div><div class="flex justify-between text-rose-600"><span>Não Essenciais</span><span id="txt-nao-essencial">R$ 0,00</span></div></div></div>
                </div>
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div class="lg:col-span-2 card p-6"><h3 class="font-bold text-sm mb-6 uppercase">Detalhamento por App</h3><div id="list-apps" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div></div>
                    <div class="card p-6 surface-warm">
                        <h3 class="font-bold text-amber-800 text-sm mb-4 uppercase">Eficiência de Galpão</h3>
                        <div class="flex items-end gap-2 mb-2">
                            <p id="txt-tempo-espera" class="text-3xl font-bold text-amber-700">0h</p>
                            <p class="text-xs text-amber-500 font-bold mb-1 uppercase">Espera Total</p>
                        </div>
                        <p id="txt-tempo-espera-avg" class="text-[10px] text-amber-600 font-semibold uppercase">Media diaria: 0h/dia</p>

                        <div class="grid grid-cols-2 gap-3 mt-4">
                            <div class="bg-white/80 border border-amber-100 rounded-lg p-3">
                                <p class="text-[10px] font-bold text-amber-500 uppercase">Shopee</p>
                                <p id="txt-tempo-espera-shopee" class="text-lg font-bold text-amber-800">0h</p>
                                <p id="txt-tempo-espera-avg-shopee" class="text-[10px] text-amber-600 font-semibold uppercase">Media: 0h/dia</p>
                            </div>
                            <div class="bg-white/80 border border-amber-100 rounded-lg p-3">
                                <p class="text-[10px] font-bold text-amber-500 uppercase">Correios</p>
                                <p id="txt-tempo-espera-correios" class="text-lg font-bold text-amber-800">0h</p>
                                <p id="txt-tempo-espera-avg-correios" class="text-[10px] text-amber-600 font-semibold uppercase">Media: 0h/dia</p>
                            </div>
                        </div>

                        <div class="w-full bg-amber-100 rounded-full h-2 my-4">
                            <div id="bar-espera" class="bg-amber-500 h-full w-0"></div>
                        </div>
                        <p id="txt-tempo-total" class="text-[10px] text-slate-500">Tempo Total: 0h</p>
                    </div>
                </div>
                <div id="insight-section" class="card hidden"><div class="bg-teal-600 px-6 py-3 text-white font-bold text-sm uppercase">Análise da IA</div><div class="p-6 prose prose-sm max-w-none" id="txt-insight"></div></div>
            </div>
            <div id="section-porteiros" class="hidden space-y-6">
                <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
                    <div>
                        <h3 class="text-xl font-bold text-slate-800 flex items-center gap-2">
                            <i class="fa-solid fa-map-location-dot text-teal-600"></i> Mapeamento de Porteiros
                        </h3>
                        <p id="porteiros-stats" class="text-slate-500 text-sm mt-1 font-medium">Carregando estatisticas...</p>
                    </div>
                    <div class="relative w-full md:w-96 group">
                        <div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                            <i class="fa-solid fa-magnifying-glass text-slate-400 group-focus-within:text-teal-600 transition-colors"></i>
                        </div>
                        <input type="text" id="search-porteiros" oninput="handleSearch(this.value)"
                            class="block w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 focus:bg-white transition-all"
                            placeholder="Buscar predio, rua ou porteiro...">
                    </div>
                </div>

                <div class="space-y-4" id="porteiros-container">
                    <p class="text-slate-400 italic text-center py-10">Carregando diretorio de porteiros...</p>
                </div>
            </div>
        </main>

        <script>
            let dailyChart, appsChart, chartGastos, dashboardData;
            const WHATSAPP_ID = '""" + whatsapp_number + """';
            const fmt = (v, p=2) => (v || 0).toLocaleString('pt-BR', {minimumFractionDigits: p});
            const fmtDate = (iso) => {
                if (!iso) return '--/--';
                const dt = new Date(iso);
                if (Number.isNaN(dt.getTime())) return '--/--';
                return dt.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
            };
            const css = getComputedStyle(document.documentElement);
            const brandTeal = css.getPropertyValue('--brand-teal').trim() || '#0f766e';
            const brandTealSoft = css.getPropertyValue('--brand-teal-soft').trim() || 'rgba(15, 118, 110, 0.12)';
            const brandRose = css.getPropertyValue('--brand-rose').trim() || '#e11d48';

            function toggleSidebar() {
                const content = document.getElementById('sidebar-content');
                const isHidden = content.classList.contains('hidden');
                content.classList.toggle('hidden', !isHidden);
                const button = document.getElementById('btn-sidebar');
                if (button) {
                    button.setAttribute('aria-label', isHidden ? 'Fechar menu' : 'Abrir menu');
                }
            }

            function closeSidebarIfMobile() {
                if (window.innerWidth < 1024) {
                    const content = document.getElementById('sidebar-content');
                    content.classList.add('hidden');
                    const button = document.getElementById('btn-sidebar');
                    if (button) button.setAttribute('aria-label', 'Abrir menu');
                }
            }

            function showSection(s) {
                document.getElementById('section-performance').classList.toggle('hidden', s !== 'performance');
                document.getElementById('section-porteiros').classList.toggle('hidden', s !== 'porteiros');
                document.getElementById('main-title').innerText = s === 'performance' ? 'Visão Geral' : 'Diretório de Porteiros';
                if (s === 'porteiros') renderPorteiros();
                closeSidebarIfMobile();
            }

            function handleSearch(query) {
                renderPorteiros(query);
            }

            function renderPorteiros(filterText = '') {
                const container = document.getElementById('porteiros-container');
                const statsEl = document.getElementById('porteiros-stats');

                if (!dashboardData || !dashboardData.porteiros || dashboardData.porteiros.length === 0) {
                    container.innerHTML = '<div class="card p-12 text-center bg-white border-dashed border-2 border-slate-200"><p class="text-slate-500 font-medium">Nenhum porteiro mapeado ainda.</p></div>';
                    statsEl.innerText = '0 predios cadastrados - 0 ruas';
                    return;
                }

                const query = (filterText || '').toLowerCase().trim();

                const normalizeStreetLabel = (value) => {
                    let text = (value || '').trim().replace(/\s+/g, ' ');
                    if (!text) return 'Sem Rua';

                    text = text.replace(/\s+\d+$/, '');

                    const upper = text.toUpperCase();
                    if (upper.includes('PAISANDU') || upper.includes('PAISSANDU') || upper.includes('PAYSANDU') || upper.includes('BAISSANDU') || upper.includes('PAISSAO')) {
                        return 'Rua Paissandu';
                    }
                    if (upper.includes('VERGUEIRO') || upper.includes('BERGUEIRO')) {
                        return 'Rua Senador Vergueiro';
                    }
                    if (upper.includes('BARATA') && upper.includes('RIBEIRO')) {
                        return 'Rua Barata Ribeiro';
                    }
                    if (upper.includes('SANTA') && upper.includes('CLARA')) {
                        return 'Rua Santa Clara';
                    }
                    if (upper.includes('COPACABANA') && (upper.includes('AV') || upper.includes('AVENIDA'))) {
                        return 'Avenida Nossa Sra. de Copacabana';
                    }

                    const smallWords = ['de', 'da', 'do', 'das', 'dos', 'e'];
                    return text.toLowerCase()
                        .replace(/\b(r|r\.|rua)\b/gi, 'Rua')
                        .replace(/\b(av|av\.|avenida)\b/gi, 'Avenida')
                        .replace(/\b\w/g, (m) => m.toUpperCase())
                        .split(' ')
                        .map(word => smallWords.includes(word.toLowerCase()) ? word.toLowerCase() : word)
                        .join(' ');
                };

                const filteredPorteiros = dashboardData.porteiros.filter(p => {
                    if (!query) return true;
                    const content = `${p.rua} ${p.numero} ${p.nome_porteiro} ${p.notas_predio || ''}`.toLowerCase();
                    return content.includes(query);
                });

                if (filteredPorteiros.length === 0) {
                    container.innerHTML = '<div class="card p-12 text-center bg-white"><p class="text-slate-500 font-medium">Nenhum resultado para sua busca.</p></div>';
                    return;
                }

                const grouped = {};
                filteredPorteiros.forEach(p => {
                    const rua = normalizeStreetLabel(p.rua);
                    if (!grouped[rua]) grouped[rua] = [];
                    grouped[rua].push(p);
                });

                const sortedStreets = Object.keys(grouped).sort();
                statsEl.innerText = `${dashboardData.porteiros.length} predios cadastrados - ${Object.keys(grouped).length} ruas`;

                container.innerHTML = '';

                sortedStreets.forEach((rua, idx) => {
                    const items = grouped[rua].sort((a, b) => {
                        const numA = parseInt(String(a.numero || '').replace(/\D/g, '')) || 0;
                        const numB = parseInt(String(b.numero || '').replace(/\D/g, '')) || 0;
                        return numA - numB;
                    });

                    const sectionId = `rua-${idx}`;
                    const accordion = document.createElement('div');
                    accordion.className = 'bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm transition-all hover:border-slate-300';

                    let cardsHtml = '';
                    items.forEach(p => {
                        const tags = [];
                        const rawNotes = String(p.notas_predio || '').trim();
                        const notes = rawNotes.toLowerCase();

                        const greenWords = ['banheiro', 'bebedouro', 'recebe pacote', 'facil', 'tranquilo', '24h', 'liberado'];
                        const yellowWords = ['troca', 'atencao', 'limite', 'horario', 'esperar'];
                        const redWords = ['nao recebe', 'dificil', 'complicado', 'ruim', 'problema', 'evitar'];
                        const tagWords = [...greenWords, ...yellowWords, ...redWords];

                        greenWords.forEach(w => { if (notes.includes(w)) tags.push({ text: w, color: 'bg-emerald-50 text-emerald-700 border-emerald-100' }); });
                        yellowWords.forEach(w => { if (notes.includes(w)) tags.push({ text: w, color: 'bg-amber-50 text-amber-700 border-amber-100' }); });
                        redWords.forEach(w => { if (notes.includes(w)) tags.push({ text: w, color: 'bg-rose-50 text-rose-700 border-rose-100' }); });

                        const tagsHtml = tags.map(t => `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold border uppercase tracking-tight ${t.color}">${t.text}</span>`).join('');
                        const removeInsensitive = (text, needle) => {
                            if (!needle) return text;
                            let result = String(text || '');
                            let lower = result.toLowerCase();
                            const needleLower = String(needle || '').toLowerCase();
                            let idx = lower.indexOf(needleLower);
                            while (idx !== -1) {
                                result = result.slice(0, idx) + ' ' + result.slice(idx + needleLower.length);
                                lower = result.toLowerCase();
                                idx = lower.indexOf(needleLower);
                            }
                            return result;
                        };
                        const cleanNote = (value) => {
                            let cleaned = value || '';
                            tagWords.forEach((word) => {
                                cleaned = removeInsensitive(cleaned, word);
                            });
                            return cleaned
                                .replace(/[,;|]+/g, ' ')
                                .replace(/\s{2,}/g, ' ')
                                .replace(/^[-–—]+/g, '')
                                .trim();
                        };
                        const notesCleaned = cleanNote(rawNotes);

                        let predioNome = 'Edificio';
                        const predioMatch = p.notas_predio ? p.notas_predio.match(/edificio\s+([^,.-]+)/i) || p.notas_predio.match(/residencial\s+([^,.-]+)/i) : null;
                        if (predioMatch) predioNome = predioMatch[0];

                        cardsHtml += `
                            <div class="bg-slate-50/50 rounded-xl p-4 border border-slate-100 flex flex-col justify-between hover:bg-white hover:border-teal-200 transition-all group">
                                <div>
                                    <div class="flex justify-between items-start mb-3">
                                        <div>
                                            <p class="text-xs font-bold text-teal-600 uppercase tracking-wider">N. ${p.numero || '-'}</p>
                                            <h5 class="font-bold text-slate-800 leading-tight">${predioNome}</h5>
                                        </div>
                                        <div class="w-8 h-8 bg-white rounded-lg border border-slate-200 flex items-center justify-center text-slate-400 group-hover:text-teal-500 group-hover:border-teal-100 transition-colors">
                                            <i class="fa-solid fa-building text-sm"></i>
                                        </div>
                                    </div>

                                    <div class="space-y-2 mb-4">
                                        <div class="flex items-center gap-2 text-slate-600">
                                            <i class="fa-solid fa-user-tie text-xs w-4"></i>
                                            <span class="text-sm font-semibold">${p.nome_porteiro || 'Nao informado'}</span>
                                        </div>
                                        ${p.turno ? `
                                            <div class="flex items-center gap-2 text-slate-500">
                                                <i class="fa-solid fa-clock text-xs w-4"></i>
                                                <span class="text-xs font-medium">${p.turno}</span>
                                            </div>
                                        ` : ''}
                                    </div>

                                    ${tagsHtml ? `
                                        <div class="flex flex-wrap gap-1.5 mb-4">
                                            ${tagsHtml}
                                        </div>
                                    ` : ''}
                                </div>

                                ${notesCleaned ? `
                                    <details class="mt-auto border-t border-slate-100 pt-3 group/details">
                                        <summary class="list-none cursor-pointer flex items-center gap-1.5 text-xs font-bold text-slate-400 hover:text-teal-600 transition-colors">
                                            <i class="fa-solid fa-note-sticky text-[10px]"></i>
                                            OBSERVACOES COMPLEMENTARES
                                            <i class="fa-solid fa-chevron-down text-[10px] ml-auto transition-transform group-open/details:rotate-180"></i>
                                        </summary>
                                        <div class="mt-2 p-3 bg-white rounded-lg border border-slate-100 shadow-inner">
                                            <p class="text-xs text-slate-600 leading-relaxed italic">"${notesCleaned}"</p>
                                        </div>
                                    </details>
                                ` : ''}
                            </div>
                        `;
                    });

                    accordion.innerHTML = `
                        <button onclick="document.getElementById('${sectionId}').classList.toggle('hidden'); this.querySelector('.chevron').classList.toggle('rotate-180')"
                            class="w-full px-6 py-4 flex items-center justify-between bg-white hover:bg-slate-50 transition-colors text-left">
                            <div class="flex items-center gap-3">
                                <div class="w-10 h-10 bg-teal-50 rounded-xl flex items-center justify-center text-teal-600 shadow-sm border border-teal-100">
                                    <i class="fa-solid fa-map-pin"></i>
                                </div>
                                <div>
                                    <h4 class="font-bold text-slate-800 uppercase tracking-tight">${rua}</h4>
                                    <p class="text-[10px] text-slate-400 font-bold uppercase">${items.length} PREDIOS CADASTRADOS</p>
                                </div>
                            </div>
                            <i class="fa-solid fa-chevron-down text-slate-300 transition-transform chevron"></i>
                        </button>
                        <div id="${sectionId}" class="px-6 pb-6 pt-2">
                            <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                                ${cardsHtml}
                            </div>
                        </div>
                    `;
                    container.appendChild(accordion);
                });
            }

            function formatPeriodRange(data) {
                const metrics = data && data.metrics ? data.metrics : {};
                if (metrics.period_label) return metrics.period_label;
                const createdAt = data && data.created_at ? new Date(data.created_at) : null;
                if (!createdAt || Number.isNaN(createdAt.getTime())) return null;
                const tipo = data.periodo_tipo;
                if (tipo === 'semanal') {
                    const day = (createdAt.getDay() + 6) % 7;
                    const start = new Date(createdAt);
                    start.setDate(createdAt.getDate() - day);
                    const end = new Date(start);
                    end.setDate(start.getDate() + 6);
                    const startStr = start.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    const endStr = end.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    return `${startStr} a ${endStr}`;
                }
                if (tipo === 'mensal') {
                    const start = new Date(createdAt.getFullYear(), createdAt.getMonth(), 1);
                    const end = new Date(createdAt.getFullYear(), createdAt.getMonth() + 1, 0);
                    const startStr = start.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    const endStr = end.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    return `${startStr} a ${endStr}`;
                }
                return createdAt.toLocaleDateString('pt-BR');
            }

            async function loadDashboard(aid = null) {
                try {
                    const res = await fetch(aid ? `/api/dashboard/${WHATSAPP_ID}?analysis_id=${aid}` : `/api/dashboard/${WHATSAPP_ID}`);
                    const data = await res.json(); dashboardData = data;
                    const c = data.metrics.consolidado, apps = data.metrics.apps;
                    
                    // Populate Header
                    const periodo = data.is_live ? 'Dados acumulados do mes' : (formatPeriodRange(data) || `Analise de ${new Date(data.created_at).toLocaleDateString('pt-BR')}`);
                    document.getElementById('txt-periodo').innerText = periodo;
                    
                    // Populate Metrics Grid
                    document.getElementById('txt-bruto').innerText = 'R$ ' + fmt(c.total_ganhos);
                    document.getElementById('txt-saldo').innerText = 'R$ ' + fmt(c.saldo);
                    document.getElementById('txt-saldo-provisao').innerText = 'R$ ' + fmt(c.saldo_com_provisao);
                    document.getElementById('txt-km-total').innerText = fmt(c.km_total, 1) + ' km';
                    document.getElementById('txt-pacotes-total').innerText = fmt(c.total_pacotes, 0);
                    document.getElementById('txt-pacotes-hora-rua').innerText = fmt(c.pacotes_por_hora_rua, 1) + '/h';
                    document.getElementById('txt-eficiencia').innerText = 'R$ ' + fmt(c.total_ganhos / (c.km_total || 1));
                    document.getElementById('txt-ganho-hora').innerText = 'R$ ' + fmt(c.ganho_por_hora);
                    document.getElementById('txt-ganho-hora-rua').innerText = 'R$ ' + fmt(c.ganho_por_hora_rua);

                    const receivables = data.next_receivables || null;
                    const receivablesSection = document.getElementById('next-receivables-section');
                    if (data.is_live && receivables) {
                        receivablesSection.style.display = '';
                        const correios = receivables.correios || {};
                        const shopee = receivables.shopee || {};
                        document.getElementById('txt-next-correios-date').innerText = 'Proximo recebimento: ' + fmtDate(correios.date);
                        document.getElementById('txt-next-correios-valor').innerText = 'R$ ' + fmt(correios.total);
                        document.getElementById('txt-next-shopee-date').innerText = 'Proximo recebimento: ' + fmtDate(shopee.date);
                        document.getElementById('txt-next-shopee-valor').innerText = 'R$ ' + fmt(shopee.total);
                    } else {
                        receivablesSection.style.display = 'none';
                    }
                    
                    // Populate Details
                    document.getElementById('txt-essencial').innerText = 'R$ ' + fmt(c.gastos_essenciais);
                    document.getElementById('txt-nao-essencial').innerText = 'R$ ' + fmt(c.gastos_nao_essenciais);
                    document.getElementById('txt-tempo-espera').innerText = fmt(c.tempo_espera_galpao, 1) + 'h';
                    const esperaMedia = (c.tempo_espera_media_diaria !== undefined && c.tempo_espera_media_diaria !== null)
                        ? c.tempo_espera_media_diaria
                        : (c.tempo_espera_galpao / (c.days_worked || 1));
                    document.getElementById('txt-tempo-espera-avg').innerText = 'Media diaria: ' + fmt(esperaMedia, 1) + 'h/dia';
                    document.getElementById('txt-tempo-total').innerText = 'Tempo Total: ' + fmt(c.total_hours, 1) + 'h';
                    document.getElementById('bar-espera').style.width = Math.min((c.tempo_espera_galpao / (c.total_hours || 1)) * 100, 100) + '%';

                    const findAppStats = (aliases) => {
                        const key = Object.keys(apps).find((name) => {
                            const lower = String(name || '').toLowerCase();
                            return aliases.some((alias) => lower.includes(alias));
                        });
                        return key ? apps[key] : null;
                    };
                    const shopee = findAppStats(['shopee']);
                    const correios = findAppStats(['correio']);
                    const shopeeAvg = shopee ? (shopee.media_diaria_espera ?? (shopee.tempo_espera / (c.days_worked || 1))) : 0;
                    const correiosAvg = correios ? (correios.media_diaria_espera ?? (correios.tempo_espera / (c.days_worked || 1))) : 0;
                    document.getElementById('txt-tempo-espera-shopee').innerText = fmt(shopee ? shopee.tempo_espera : 0, 1) + 'h';
                    document.getElementById('txt-tempo-espera-avg-shopee').innerText = 'Media: ' + fmt(shopeeAvg, 1) + 'h/dia';
                    document.getElementById('txt-tempo-espera-correios').innerText = fmt(correios ? correios.tempo_espera : 0, 1) + 'h';
                    document.getElementById('txt-tempo-espera-avg-correios').innerText = 'Media: ' + fmt(correiosAvg, 1) + 'h/dia';
                    
                    // AI Insight
                    const ins = document.getElementById('insight-section');
                    if (!data.is_live) {
                        ins.classList.remove('hidden');
                        if (data.insight) {
                            document.getElementById('txt-insight').innerHTML = marked.parse(data.insight);
                        } else {
                            document.getElementById('txt-insight').innerHTML = '<p>Analise indisponivel para este periodo. Reprocese para gerar.</p>';
                        }
                    } else { ins.classList.add('hidden'); }
                    
                    // App Details - Rich version
                    const list = document.getElementById('list-apps'); list.innerHTML = '';
                    Object.keys(apps).filter(n => apps[n].ganhos > 0).sort((a,b) => apps[b].ganhos - apps[a].ganhos).forEach(name => {
                        const app = apps[name];
                        const rkm = (app.ganhos / (app.km || 1));
                        const rhora = (app.ganhos / (app.horas || 1));
                        const percent = (app.ganhos / (c.total_ganhos || 1)) * 100;
                        const lower = String(name || '').toLowerCase();
                        
                        if (lower.includes('shopee') || lower.includes('correio')) {
                            const appClass = lower.includes('shopee') ? 'shopee' : 'correios';
                            list.innerHTML += `
                                <article class="pay-card ${appClass}">
                                    <div class="pay-head">
                                        <div class="pay-badge">${name}</div>
                                        <div class="pay-date">${fmt(app.km,1)}km • ${fmt(app.horas,1)}h</div>
                                    </div>
                                    <div class="pay-value">R$ ${fmt(app.ganhos)}</div>
                                    <div class="pay-sub">${fmt(percent,0)}% do faturamento total</div>
                                    <div class="grid grid-cols-2 gap-2 mt-4">
                                        <div class="bg-white/60 p-2 rounded-lg border border-white/40 text-center shadow-sm">
                                            <p class="text-[9px] font-bold uppercase opacity-70">R$/KM</p>
                                            <p class="text-xs font-bold">R$ ${fmt(rkm)}</p>
                                        </div>
                                        <div class="bg-white/60 p-2 rounded-lg border border-white/40 text-center shadow-sm">
                                            <p class="text-[9px] font-bold uppercase opacity-70">R$/Hora</p>
                                            <p class="text-xs font-bold">R$ ${fmt(rhora)}</p>
                                        </div>
                                    </div>
                                </article>`;
                        } else {
                            const tone = { accent: brandTeal, accentSoft: brandTealSoft, accentBorder: 'rgba(15, 118, 110, 0.2)', accent2: brandTeal };
                            list.innerHTML += `
                                <div class="app-card p-4" style="--app-accent: ${tone.accent}; --app-accent-soft: ${tone.accentSoft}; --app-accent-border: ${tone.accentBorder}; --app-accent-2: ${tone.accent2};">
                                    <div class="flex justify-between items-start mb-3">
                                        <div>
                                            <p class="font-bold text-sm uppercase app-title">${name}</p>
                                            <p class="text-[10px] text-slate-500 font-bold uppercase">${fmt(app.km,1)}km • ${fmt(app.horas,1)}h</p>
                                        </div>
                                        <div class="text-right">
                                            <p class="font-bold text-sm" style="color: ${tone.accent}">R$ ${fmt(app.ganhos)}</p>
                                            <span class="app-pill"><span class="dot"></span>${fmt(percent,0)}% do total</span>
                                        </div>
                                    </div>
                                    <div class="grid grid-cols-2 gap-2 mt-4">
                                        <div class="bg-white p-2 rounded-lg border text-center shadow-inner"><p class="text-[9px] font-bold text-slate-400 uppercase">R$/KM</p><p class="text-xs font-bold">R$ ${fmt(rkm)}</p></div>
                                        <div class="bg-white p-2 rounded-lg border text-center shadow-inner"><p class="text-[9px] font-bold text-slate-400 uppercase">R$/Hora</p><p class="text-xs font-bold">R$ ${fmt(rhora)}</p></div>
                                    </div>
                                </div>`;
                        }
                    });

                    // Charts
                    const dailyContainer = document.getElementById('daily-chart-container');
                    const appsContainer = document.getElementById('apps-chart-container');
                    const dailyPerf = Array.isArray(data.daily_performance) ? data.daily_performance : [];
                    if (dailyPerf.length > 0) {
                        dailyContainer.style.display = '';
                        appsContainer.style.display = 'none';
                        const labels = dailyPerf.map((d) => {
                            const dt = new Date(d.date);
                            return Number.isNaN(dt.getTime()) ? d.date : dt.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                        });
                        const values = dailyPerf.map((d) => d.ganho || 0);
                        if (dailyChart) dailyChart.destroy();
                        dailyChart = new Chart(document.getElementById('chartDaily').getContext('2d'), {
                            type: 'line',
                            data: { labels: labels, datasets: [{ label: 'Ganho diario', data: values, borderColor: brandTeal, backgroundColor: brandTealSoft, tension: 0.3, fill: true, pointRadius: 3 }] },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { ticks: { callback: (v) => 'R$ ' + fmt(v) } } } }
                        });
                    } else {
                        dailyContainer.style.display = 'none';
                        appsContainer.style.display = '';
                    }

                    if (chartGastos) chartGastos.destroy();
                    chartGastos = new Chart(document.getElementById('chartGastos').getContext('2d'), { type: 'doughnut', data: { labels: ['Essenciais', 'Não Essenciais'], datasets: [{ data: [c.gastos_essenciais, c.gastos_nao_essenciais], backgroundColor: [brandTeal, brandRose] }] }, options: { responsive: true, maintainAspectRatio: false, cutout: '75%', plugins: { legend: { display: false } } } });
                    
                    // History Nav
                    const hlist = document.getElementById('history-list'); hlist.innerHTML = '';
                    const live = document.createElement('a'); live.href = '#'; live.className = 'history-item block p-3 rounded-lg ' + (!aid ? 'bg-teal-50 border-teal-200 border' : 'bg-white');
                    live.innerHTML = `<span class="text-xs font-bold uppercase ${!aid ? 'text-teal-600' : 'text-slate-500'}">AO VIVO</span><span class="block text-xs font-medium ${!aid ? 'text-teal-800':'text-slate-700'}">Dashboard Atual</span>`;
                    live.onclick = (e) => { e.preventDefault(); loadDashboard(); closeSidebarIfMobile(); }; hlist.appendChild(live);
                    data.history.forEach((h, i) => {
                        const btn = document.createElement('a'); btn.href = '#'; btn.className = 'history-item block p-3 rounded-lg mt-2 ' + (aid === h.id ? 'bg-teal-50 border-teal-200 border' : 'bg-white');
                        const cti = data.history.filter((x, j) => x.periodo_tipo === h.periodo_tipo && j >= i).length;
                        const periodLabel = formatPeriodRange(h) || `Analise de ${new Date(h.created_at).toLocaleDateString('pt-BR')}`;
                        btn.innerHTML = `<span class="text-xs font-bold uppercase ${aid === h.id ? 'text-teal-600':'text-slate-500'}">${h.periodo_tipo} ${cti}</span><span class="block text-[11px] text-slate-500">${periodLabel}</span>`;
                        btn.onclick = (e) => { e.preventDefault(); loadDashboard(h.id); closeSidebarIfMobile(); }; hlist.appendChild(btn);
                    });
                    const sectionOpen = !document.getElementById('section-porteiros').classList.contains('hidden');
                    if (sectionOpen) {
                        const existingFilter = document.getElementById('search-porteiros')?.value || '';
                        renderPorteiros(existingFilter);
                    }
                } catch (e) { console.error('Dashboard load error:', e); }
            }
            loadDashboard();
        </script>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

@app.get("/admin/fix-wait-events")
async def fix_wait_events():
    """
    Endpoint temporário para associar eventos de 'espera_galpao' sem app_id ao app correto.
    """
    print("--- Iniciando backfill via endpoint para associar apps a eventos de espera ---")
    
    wait_events_res = db.supabase.table("eventos").select("id, operacao_id, timestamp").eq("sub_tipo", "espera_galpao").is_("app_id", "null").execute()
    wait_events = wait_events_res.data
    
    if not wait_events:
        return {"message": "Nenhum evento de espera sem app para corrigir. Tudo certo!"}

    print(f"Encontrados {len(wait_events)} eventos de espera para processar.")
    
    events_by_op = defaultdict(list)
    for ev in wait_events:
        if ev.get("operacao_id"):
            events_by_op[ev["operacao_id"]].append(ev)

    updated_count = 0
    skipped_count = 0
    logs = []

    for op_id, wait_evs in events_by_op.items():
        gain_events_res = db.supabase.table("eventos").select("app_id, timestamp").eq("operacao_id", op_id).eq("tipo", "ganho").not_.is_("app_id", "null").execute()
        gain_events = gain_events_res.data

        if not gain_events:
            logs.append(f"Operação {op_id}: Nenhum evento de ganho com app_id. Pulando {len(wait_evs)} eventos de espera.")
            skipped_count += len(wait_evs)
            continue
            
        apps_per_day = defaultdict(set)
        for g_ev in gain_events:
            day = g_ev["timestamp"][:10]
            apps_per_day[day].add(g_ev["app_id"])

        for w_ev in wait_evs:
            wait_day = w_ev["timestamp"][:10]
            candidate_apps = apps_per_day.get(wait_day)
            
            if candidate_apps and len(candidate_apps) == 1:
                app_id_to_set = list(candidate_apps)[0]
                logs.append(f"Operação {op_id}: Atualizando evento {w_ev['id']} com app_id {app_id_to_set}")
                db.supabase.table("eventos").update({"app_id": app_id_to_set}).eq("id", w_ev["id"]).execute()
                updated_count += 1
            else:
                logs.append(f"Operação {op_id}: Ambiguidade para evento {w_ev['id']} no dia {wait_day}. Apps candidatos: {candidate_apps}. Pulando.")
                skipped_count += 1

    summary = {
        "message": "Backfill concluído",
        "updated": updated_count,
        "skipped": skipped_count,
        "logs": logs
    }
    print(summary)
    return summary
