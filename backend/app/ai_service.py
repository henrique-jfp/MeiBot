import datetime
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
from google.cloud import vision
from google.oauth2 import service_account
from groq import Groq

load_dotenv()

class AIService:
    def __init__(self):
        # Gemini Config (Keeping for specialized tasks like audio/image fallback)
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self.gemini_model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Groq Config (Main engine for text and logic)
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.groq_model_smart = "llama-3.3-70b-versatile" # Análise estratégica (mais pesado)
        self.groq_model_fast = "llama-3.1-8b-instant"     # Trabalho braçal de JSON (ultra rápido e econômico)

        # Google Vision Config
        creds_json = os.getenv("GOOGLE_VISION_CREDENTIALS_JSON")
        if creds_json:
            try:
                creds_dict = json.loads(creds_json)
                if "private_key" in creds_dict:
                    pk = creds_dict["private_key"]
                    pk = pk.replace("\\n", "\n").replace("\\", "")
                    creds_dict["private_key"] = pk
                
                credentials = service_account.Credentials.from_service_account_info(creds_dict)
                self.vision_client = vision.ImageAnnotatorClient(credentials=credentials)
            except Exception as e:
                print(f"Vision Client initialization skipped: {e}")
                self.vision_client = None
        else:
            self.vision_client = None

    async def interpret_message(self, text: str):
        today = datetime.date.today().isoformat()
        prompt = f"""
        Você é um assistente de logística para entregadores. Interprete a mensagem e retorne EXCLUSIVAMENTE um JSON.
        Data atual: {today}
        
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
        - cadastrar_porteiro: Para mapear um novo porteiro em um endereço.
        - corrigir_porteiro: Para atualizar informações de um porteiro já cadastrado.

        Regras de Negócio Pessoais (OBRIGATÓRIO):
        - Se o app for 'Shopee': Valor bruto = 305.00, KM = 60. Gere também um evento de gasto: {{"app": "Shopee", "tipo": "gasto", "categoria": "Essencial", "valor": 130.00, "descricao": "Salário ajudante Shopee"}}.
        - Se o app for 'Correios': KM = 20. Valor bruto = pacotes * 2.00.
        
        Nomes de APP padronizados (use EXATAMENTE estes):
        - 'Shopee', 'Correios', 'Mercado Livre', 'iFood', 'Uber', 'Loggi', 'Lalamove'.
        - Para gastos, use: 'Combustível', 'Manutenção', 'Alimentação', 'Outros'.

        Campos do JSON:
        - intencao: Uma das intenções acima.
        - data_referencia: YYYY-MM-DD (obrigatório se mencionado data ou "ontem", "anteontem", "dia X").
        - pergunta: O texto da pergunta (se intencao for 'pergunta').
        - eventos: lista de objetos {{'app': str, 'tipo': 'ganho'|'gasto'|'ajuste', 'valor': float, 'km': float, 'pacotes': int, 'hora_chegada_galpao': str, 'hora_inicio_rota': str, 'hora_fim_operacao': str, 'categoria': str, 'descricao': str}}
        
        Texto do usuário: "{text}"
        """
        
        try:
            completion = self.groq_client.chat.completions.create(
                model=self.groq_model_fast,
                messages=[
                    {"role": "system", "content": "Você é um parser de JSON especializado em logística. Responda apenas com o JSON bruto, sem explicações."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            print(f"Groq interpret failed: {e}. Falling back to Gemini...")
            # Fallback para Gemini em caso de erro no Groq
            response = self.gemini_model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)

    async def answer_question(self, context: str, question: str):
        prompt = f"""
        Com base nos dados abaixo:
        {context}
        
        Responda à pergunta do entregador de forma direta e amigável:
        "{question}"
        """
        try:
            completion = self.groq_client.chat.completions.create(
                model=self.groq_model_fast,
                messages=[{"role": "user", "content": prompt}]
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"Groq answer failed: {e}. Falling back to Gemini...")
            response = self.gemini_model.generate_content(prompt)
            return response.text

    async def process_image(self, image_bytes: bytes, mime_type: str):
        ocr_text = ""
        if self.vision_client:
            image = vision.Image(content=image_bytes)
            response = self.vision_client.text_detection(image=image)
            texts = response.text_annotations
            if texts:
                ocr_text = texts[0].description
        
        prompt = f"""
        Analise o texto extraído de um comprovante ou tela de app de entrega via OCR.
        Retorne um JSON com a intenção 'registro' e a lista de 'eventos' encontrados.
        Identifique: App, Valor, KM, Quantidade de Pacotes, etc.
        
        Texto OCR:
        {ocr_text}
        """
        try:
            completion = self.groq_client.chat.completions.create(
                model=self.groq_model_fast,
                messages=[
                    {"role": "system", "content": "Responda apenas com JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            print(f"Groq image interpret failed: {e}. Falling back to Gemini...")
            response = self.gemini_model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)

    async def transcribe_audio(self, audio_bytes: bytes):
        # Gemini ainda é melhor para processamento nativo de áudio multimodal
        prompt = "Transcreva este áudio de um entregador descrevendo seu dia ou fazendo uma pergunta."
        response = self.gemini_model.generate_content([
            prompt,
            {'mime_type': 'audio/ogg', 'data': audio_bytes}
        ])
        return response.text

    async def generate_daily_insight(self, current_metrics: dict, previous_metrics: dict = None):
        curr = {
            "ganho": current_metrics.get("total_ganhos", 0),
            "km": current_metrics.get("km_total", 0),
            "rs_km": (current_metrics.get("total_ganhos", 0) / current_metrics.get("km_total")) if current_metrics.get("km_total", 0) > 0 else 0
        }

        prev_str = "Sem dados de ontem."
        if previous_metrics:
            p_c = previous_metrics.get("consolidado", {})
            prev = {
                "rs_km": (p_c.get("total_ganhos", 0) / p_c.get("km_total")) if p_c.get("km_total", 0) > 0 else 0
            }
            prev_str = f"Ontem a eficiência foi de R$ {prev['rs_km']:.2f}/km."

        prompt = f"""
        Você é o parceiro de operação do entregador. 
        Sua missão é dar um feedback CURTO (MÁXIMO 2 LINHAS) sobre o dia dele.
        SEM markdown, SEM tabelas, apenas um parágrafo amigável.

        DADOS DE HOJE:
        - Faturamento: R$ {curr['ganho']:.2f}
        - KM: {curr['km']:.1f}
        - Eficiência: R$ {curr['rs_km']:.2f}/km

        COMPARAÇÃO COM ONTEM:
        {prev_str}

        INSTRUÇÕES:
        - Fale como se estivesse no banco do carona.
        - Elogie se o R$/km for alto (acima de R$ 3/km).
        - Se não tiver KM registrado, foque apenas no faturamento.
        - Finalize com uma mensagem positiva de fim de dia.

        Exemplo do tom desejado: "Fechamos o dia com R$ 250! A eficiência de R$ 3,20/km foi melhor que ontem. Bom descanso, parceiro!"
        """
        try:
            completion = self.groq_client.chat.completions.create(
                model=self.groq_model_fast,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=150
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"Groq daily insight failed: {e}. Falling back to Gemini...")
            response = self.gemini_model.generate_content(prompt)
            return response.text

    async def generate_analyst_insight(self, current_metrics: dict, previous_metrics: dict = None, period_type: str = "Semana", app_metrics: dict = None):
        curr = {
            "ganho": current_metrics.get("total_ganhos", 0),
            "gasto_essencial": current_metrics.get("gastos_essenciais", 0),
            "gasto_nao_essencial": current_metrics.get("gastos_nao_essenciais", 0),
            "saldo": current_metrics.get("saldo", 0),
            "km": current_metrics.get("km_total", 0),
            "horas": current_metrics.get("total_hours", 0),
            "rs_hora": current_metrics.get("ganho_por_hora", 0),
            "rs_km": (current_metrics.get("total_ganhos", 0) / current_metrics.get("km_total")) if current_metrics.get("km_total", 0) > 0 else 0
        }
        
        perc_nao_essencial = (curr["gasto_nao_essencial"] / curr["ganho"] * 100) if curr["ganho"] > 0 else 0

        prev_str = "Nenhum dado anterior disponível para comparação."
        if previous_metrics:
            prev = {
                "ganho": previous_metrics.get("total_ganhos", 0),
                "km": previous_metrics.get("km_total", 0),
                "rs_hora": previous_metrics.get("ganho_por_hora", 0)
            }
            prev_str = f"Anteriormente: Ganho R$ {prev['ganho']:.2f}, KM {prev['km']:.1f}, Eficiência R$ {prev['rs_hora']:.2f}/h."

        apps_info = []
        if app_metrics:
            for name, data in app_metrics.items():
                g = float(data.get("ganhos", 0) or 0)
                k = float(data.get("km", 0) or 0)
                h = float(data.get("horas", 0) or 0)
                r_km = g / k if k > 0 else 0
                r_h = g / h if h > 0 else 0
                apps_info.append(f"- {name}: Ganho R$ {g:.2f}, KM {k:.1f} (R$ {r_km:.2f}/km), Tempo {h:.1f}h (R$ {r_h:.2f}/h)")
        
        apps_str = "\n".join(apps_info) if apps_info else "Sem dados detalhados por plataforma."

        prompt = f"""
        Você é um consultor financeiro de elite para frotas e entregadores autônomos. 
        Sua análise deve ser RIGOROSA, CRÍTICA e soar como um parceiro de negócios humano, não como um robô.

        TABELA DE PARÂMETROS (VOCÊ DEVE USAR ESTES TERMOS EXATOS PARA DAR A NOTA):
        1. Ganho por KM:
           - R$ 1/km: Ruim | R$ 2/km: Regular | R$ 3/km: Bom | R$ 4/km: Muito bom | >= R$ 5/km: Excelente
        2. Gastos Não Essenciais (sobre ganho bruto):
           - <= 3%: Ok | <= 5%: Alerta Laranja | > 7%: Alerta Vermelho
        3. Ganhos por Hora:
           - <= R$ 20/h: Péssimo | R$ 30/h: Regular | R$ 40/h: Bom | R$ 50/h: Muito bom | >= R$ 60/h: Excelente

        DADOS DA OPERAÇÃO ({period_type}):
        - Ganho Bruto Total: R$ {curr['ganho']:.2f}
        - Saldo Líquido (Lucro): R$ {curr['saldo']:.2f}
        - Gastos: Essenciais R$ {curr['gasto_essencial']:.2f} | Não Essenciais R$ {curr['gasto_nao_essencial']:.2f} ({perc_nao_essencial:.1f}%)
        - Eficiência Geral: {curr['km']:.1f} km rodados (R$ {curr['rs_km']:.2f}/km) | {curr['horas']:.1f}h trabalhadas (R$ {curr['rs_hora']:.2f}/h)
        
        PERFORMANCE POR APP:
        {apps_str}

        COMPARAÇÃO:
        {prev_str}

        INSTRUÇÕES:
        - Na "Análise da Shopee" e "Análise dos Correios", use os parâmetros acima para dizer se a performance daquele app específico foi Boa, Excelente, Ruim, etc., baseando-se no R$/km e R$/h dele.
        - Na "Análise Geral", dê o veredito final da empresa. Se os gastos não essenciais baterem Alerta Vermelho (>7%), seja enfático.
        - Use uma linguagem de "quem entende do trecho". Evite "Com base nos dados...", prefira "A Shopee essa semana entregou uma margem...".
        - Se o R$/km estiver excelente mas o R$/h estiver péssimo, aponte que houve muita espera no galpão ou trânsito.

        Responda EXATAMENTE neste formato (sem markdown):

        Análise da Shopee
        [Texto crítico e humano usando os parâmetros]

        Análise da Operação dos Correios
        [Texto crítico e humano usando os parâmetros]

        Análise Geral da Empresa
        [Texto crítico e humano consolidando as notas de KM, Hora e Gastos]

        Recomendações Estratégicas
        • [Uma recomendação direta e prática para aumentar o lucro]
        """
        
        try:
            completion = self.groq_client.chat.completions.create(
                model=self.groq_model_smart,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7, # Aumentado para soar mais natural e variado
                max_tokens=800
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"Groq insight failed: {e}. Falling back to Gemini...")
            response = self.gemini_model.generate_content(prompt)
            return response.text
