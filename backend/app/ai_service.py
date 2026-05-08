import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
from google.cloud import vision
from google.oauth2 import service_account

load_dotenv()

class AIService:
    def __init__(self):
        # Gemini Config
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        # Usando o modelo solicitado (versão 2.5 Flash)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Google Vision Config
        creds_json = os.getenv("GOOGLE_VISION_CREDENTIALS_JSON")
        if creds_json:
            try:
                creds_dict = json.loads(creds_json)
                if "private_key" in creds_dict:
                    pk = creds_dict["private_key"]
                    # Replace literal \n and then remove any other backslashes that might be escaping things incorrectly
                    pk = pk.replace("\\n", "\n").replace("\\", "")
                    creds_dict["private_key"] = pk
                
                credentials = service_account.Credentials.from_service_account_info(creds_dict)
                self.vision_client = vision.ImageAnnotatorClient(credentials=credentials)
            except Exception as e:
                # Silently fail if Vision is not configured correctly to not break the whole backend
                print(f"Vision Client initialization skipped: {e}")
                self.vision_client = None
        else:
            self.vision_client = None

    async def interpret_message(self, text: str):
        prompt = f"""
        Você é um assistente de logística para entregadores. Interprete a mensagem e retorne um JSON.
        
        Intenções Válidas:
        - 'iniciar': Quando o entregador quer começar o dia ou a operação.
        - 'encerrar': Quando o entregador quer fechar o dia ou a operação.
        - 'registro': Para registrar ganhos, gastos, rotas, pacotes, KM, ou tempos de espera.
        - 'resumo_diario': Para ver o que foi feito hoje ou em uma data específica.
        - 'resumo_semanal': Para ver o resumo dos últimos 7 dias.
        - 'resumo_mensal': Para ver o resumo dos últimos 30 dias.
        - 'pergunta': Quando o entregador faz uma pergunta sobre seus ganhos ou dados históricos.
        - 'cadastrar_entregador': Para cadastrar um novo entregador (nome, valor diária).
        - 'listar_porteiros': Para listar os porteiros mapeados.
        - 'consultar_porteiro': Para buscar porteiros de um endereço específico.
        - 'cadastrar_porteiro': Para mapear um novo porteiro em um endereço.
        - 'corrigir_porteiro': Para atualizar informações de um porteiro já cadastrado.

        Campos do JSON:
        - intencao: Uma das intenções acima.
        - data_referencia: YYYY-MM-DD (se o usuário falar "ontem", "anteontem", "dia 05", etc).
        - pergunta: O texto da pergunta (se intencao for 'pergunta').
        - entregador_info: {{'nome': str, 'valor_diaria': float}}
        - porteiro_info: {{'rua': str, 'numero': str, 'nome': str, 'nome_antigo': str, 'turno': str, 'notas': str}}
        - eventos: lista de objetos {{'app': str, 'tipo': 'ganho'|'gasto'|'ajuste', 'valor': float, 'km': float, 'pacotes': int, 'km_deslocamento': float, 'km_rota': float, 'hora_chegada_galpao': str, 'hora_inicio_rota': str, 'hora_fim_operacao': str, 'valor_extra': float, 'categoria': str, 'descricao': str}}
        
        Exemplos:
        "fiz uma rota hoje na loggi 150 reais 40km 30 pacotes" -> intencao: 'registro', eventos: [{{'app': 'Loggi', 'tipo': 'ganho', 'valor': 150, 'km_rota': 40, 'pacotes': 30}}]
        "quanto ganhei na semana?" -> intencao: 'resumo_semanal'
        "resumo da semana" -> intencao: 'resumo_semanal'
        "resumo de ontem" -> intencao: 'resumo_diario', data_referencia: 'YYYY-MM-DD' (data de ontem)
        
        Texto do usuário: "{text}"
        """
        response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)

    async def answer_question(self, context: str, question: str):
        prompt = f"""
        Com base nos dados abaixo:
        {context}
        
        Responda à pergunta do entregador de forma direta e amigável:
        "{question}"
        """
        response = self.model.generate_content(prompt)
        return response.text

    async def process_image(self, image_bytes: bytes, mime_type: str):
        # 1. OCR com Google Vision (Mais preciso para rotas e comprovantes)
        ocr_text = ""
        if self.vision_client:
            image = vision.Image(content=image_bytes)
            response = self.vision_client.text_detection(image=image)
            texts = response.text_annotations
            if texts:
                ocr_text = texts[0].description
        
        # 2. Interpretação do texto OCR pelo Gemini
        prompt = f"""
        Analise o texto extraído de um comprovante ou tela de app de entrega via OCR.
        Retorne um JSON com a intenção 'registro' e a lista de 'eventos' encontrados.
        Identifique: App, Valor, KM, Quantidade de Pacotes, etc.
        
        Texto OCR:
        {ocr_text}
        """
        response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)

    async def transcribe_audio(self, audio_bytes: bytes):
        prompt = "Transcreva este áudio de um entregador descrevendo seu dia ou fazendo uma pergunta."
        response = self.model.generate_content([
            prompt,
            {'mime_type': 'audio/ogg', 'data': audio_bytes}
        ])
        return response.text

    async def generate_analyst_insight(self, current_metrics: dict, previous_metrics: dict = None, period_type: str = "Semana"):
        curr = {
            "ganho": current_metrics.get("total_ganhos", 0),
            "gasto": current_metrics.get("total_gastos", 0),
            "saldo": current_metrics.get("saldo", 0),
            "km": current_metrics.get("km_total", 0),
            "horas": current_metrics.get("total_hours", 0),
            "rs_hora": current_metrics.get("ganho_por_hora", 0)
        }
        
        prev_str = "N/A"
        if previous_metrics:
            prev = {
                "ganho": previous_metrics.get("total_ganhos", 0),
                "km": previous_metrics.get("km_total", 0),
                "rs_hora": previous_metrics.get("ganho_por_hora", 0)
            }
            prev_str = f"Ganho: R$ {prev['ganho']:.2f}, KM: {prev['km']:.1f}, R$/Hora: R$ {prev['rs_hora']:.2f}"

        prompt = f"""
        Você é o ANALISTA ESTRATÉGICO SÊNIOR do MeiBot.
        Sua missão é dar uma consultoria de negócios detalhada para o entregador.
        
        DADOS ATUAIS ({period_type}):
        - Ganho Total: R$ {curr['ganho']:.2f}
        - Saldo Líquido: R$ {curr['saldo']:.2f}
        - KM Total: {curr['km']:.1f}
        - Horas: {curr['horas']:.1f}h
        - R$/Hora: R$ {curr['rs_hora']:.2f}
        
        COMPARAÇÃO ANTERIOR:
        {prev_str}
        
        Sua resposta deve ter no mínimo 3 parágrafos curtos:
        1. Análise de Performance: Comente sobre o ganho por hora e o custo por KM. Diga se ele está sendo eficiente ou se está "pagando para trabalhar".
        2. Comparação: Se houver dados anteriores, compare se ele melhorou ou piorou e o porquê provável.
        3. Dica de Ouro: Dê uma estratégia real para ele ganhar mais dinheiro (ex: escolher melhor os horários, focar em apps que pagam mais por km, reduzir gastos supérfluos).
        
        Use gírias de entregador (pista, meta, foguete, parceiro) mas mantenha a seriedade financeira.
        """
        response = self.model.generate_content(prompt)
        return response.text
