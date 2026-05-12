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
        - 'iniciar': Quando o entregador começa o trabalho do dia.
        - 'encerrar': Quando o entregador termina o dia de trabalho e não está relatando números.
        - 'registro': Para registrar rotas, ganhos, gastos, pacotes, KM, ou tempos. (MUITO IMPORTANTE: Se o usuário relatar dados do que fez, como "finalizei a rota, 100 pacotes", a intenção é SEMPRE 'registro', mesmo que use a palavra "finalizei". Use 'registro' também para dias anteriores).
        - 'resumo_diario': Apenas quando o usuário pede ativamente para ver o resumo.
        - 'resumo_semanal': Para ver o resumo dos últimos 7 dias.
        - 'resumo_mensal': Para ver o resumo dos últimos 30 dias.
        - 'pergunta': Quando o entregador faz uma pergunta sobre seus ganhos ou dados históricos.
        - 'cadastrar_entregador': Para cadastrar um novo entregador (nome, valor diária).
        - 'listar_porteiros': Para listar os porteiros mapeados ou quando o usuário pede "porteiros", "meus porteiros", "lista de porteiros".
        - 'consultar_porteiro': Para buscar porteiros de um endereço específico.
        - 'cadastrar_porteiro': Para mapear um novo porteiro em um endereço.
        - 'corrigir_porteiro': Para atualizar informações de um porteiro já cadastrado.
        - 'pedir_link_dashboard': Quando o usuário pede o link do dashboard, mapa de porteiros, ou painel.

        Regras de Negócio Pessoais (OBRIGATÓRIO):
        - Se o usuário disser apenas "Porteiro" ou "Porteiros", use intencao: 'listar_porteiros'.
        - Se o usuário pedir o link do mapa ou dashboard, use intencao: 'pedir_link_dashboard'.
        - Se a mensagem contiver um endereço (rua e número) e um nome de pessoa associado a "porteiro", use SEMPRE 'cadastrar_porteiro'.

        Regras de Extração de Eventos (OBRIGATÓRIO):
        1. SEPARAÇÃO DE EVENTOS: O usuário frequentemente relata rotas e gastos no mesmo texto. Você DEVE extrair CADA EVENTO como um objeto separado na lista 'eventos'. (Ex: Se ele fez Correios e comprou cigarro, gere DOIS eventos, um 'ganho' e um 'gasto').
        2. MÚLTIPLAS OPERAÇÕES: O usuário pode fazer mais de uma operação no dia (Ex: Shopee e depois Correios). Crie eventos separados para cada um.
        3. EXTRAÇÃO PURA (SEM MATEMÁTICA): Você é APENAS UM EXTRATOR DE DADOS. NUNCA calcule ganhos ou faça contas. Se o usuário disse "150 pacotes" mas não disse quantos reais ganhou, DEIXE o campo 'valor' como null ou 0. O cálculo será feito pelo backend. Apenas extraia o que foi DITO EXPLICITAMENTE.
        4. GASTOS E DESPESAS IMPLÍCITAS: Textos como "20 reais com cigarro e cocacola" DEVEM ser interpretados como tipo: 'gasto', mesmo sem a palavra "gastei". NUNCA use app "Correios" ou "Shopee" para um evento de gasto. Use app: null para gastos.
        5. CATEGORIAS DE GASTOS: Para tipo: 'gasto', classifique a 'categoria' rigorosamente como uma destas: 'Combustível', 'Alimentação', 'Manutenção', 'Essencial', ou 'Outros'. (Ex: cigarro e cocacola = 'Outros', apenas combustível e manutenção são 'Essencial').
        6. HORÁRIOS: Identifique "cheguei" (ou tempo de espera no galpão) como `hora_chegada_galpao`, "saí do galpão" como `hora_saida_galpao`, "comecei a rota" como `hora_inicio_rota`, e "finalizei" como `hora_fim_operacao`. O período desde que "chegou" até "começou a rota" (ou "saí") é essencial.
        7. DATAS (CUIDADO): O entregador escreve datas no formato BRASILEIRO DD/MM/YYYY. Por exemplo, 04/05/2026 é 4 de Maio (e não 5 de Abril). O campo `data_referencia` deve ser RIGOROSAMENTE retornado em ISO: YYYY-MM-DD.

        Nomes de APP padronizados (use EXATAMENTE estes):
        - 'Shopee', 'Correios', 'Mercado Livre', 'iFood', 'Uber', 'Loggi', 'Lalamove'.

        Campos do JSON:
        - intencao: Uma das intenções acima.
        - data_referencia: YYYY-MM-DD (obrigatório se mencionado data ou "ontem", "anteontem", "dia X").
        - pergunta: O texto da pergunta (se intencao for 'pergunta').
        - porteiro_info: objeto {{'rua': str, 'numero': str, 'nome': str, 'turno': str, 'notas': str, 'nome_antigo': str}} (obrigatório para intenções de porteiro).
        - eventos: lista de objetos {{'app': str, 'tipo': 'ganho'|'gasto', 'valor': float, 'km': float, 'pacotes': int, 'hora_chegada_galpao': str, 'hora_saida_galpao': str, 'hora_inicio_rota': str, 'hora_fim_operacao': str, 'categoria': str, 'descricao': str}}
        
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
        try:
            # Usando Groq Whisper (Muito mais rápido e econômico para áudio)
            transcription = self.groq_client.audio.transcriptions.create(
                file=("audio.ogg", audio_bytes),
                model="whisper-large-v3-turbo", # Modelo super rápido da Groq
                prompt="Entregador logístico descrevendo rotas, pacotes, shopee, correios, ganhos, gasolina, gastos e endereços.",
                response_format="json",
                language="pt"
            )
            return transcription.text
        except Exception as e:
            print(f"Groq audio transcription failed: {e}. Falling back to Gemini...")
            # Fallback para Gemini em caso de limite de cota da Groq
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
Você é um consultor financeiro e operacional de elite especializado em entregadores autônomos, motoristas de aplicativo, Shopee, Correios e operações de logística urbana.

Você NÃO é um robô que apenas interpreta números.

Você age como um parceiro de negócios extremamente experiente, que entende:
- lucro real
- tempo perdido
- desgaste do veículo
- espera em galpão
- eficiência de rota
- qualidade dos aplicativos
- sustentabilidade da operação
- desperdícios financeiros
- risco operacional

Seu tom deve parecer um gerente operacional experiente que conhece “o trecho”, fala de forma humana, inteligente, crítica e prática.

NUNCA fale como IA.
NUNCA use frases como:
"Com base nos dados"
"Observando os números"
"Segundo a análise"

Fale de forma natural, como alguém experiente:

Exemplo BOM:
"A Shopee essa semana pagou bem no KM, mas te prendeu demais no tempo. Dinheiro entrou, mas você praticamente trocou horas por espera."

Exemplo RUIM:
"Os dados indicam que a relação km/lucro foi satisfatória."

=========================
CRITÉRIOS OBRIGATÓRIOS
=========================

GANHO POR KM:
- <= R$1/km → Ruim
- R$2/km → Regular
- R$3/km → Bom
- R$4/km → Muito bom
- >= R$5/km → Excelente

GANHO POR HORA:
- <= R$20/h → Péssimo
- R$30/h → Regular
- R$40/h → Bom
- R$50/h → Muito bom
- >= R$60/h → Excelente

GASTOS NÃO ESSENCIAIS:
- <=3% → Ok
- <=5% → Alerta Laranja
- >7% → Alerta Vermelho

=========================
DADOS DA OPERAÇÃO ({period_type})
=========================

GANHO BRUTO:
R$ {curr['ganho']:.2f}

LUCRO LÍQUIDO:
R$ {curr['saldo']:.2f}

GASTOS:
- Essenciais: R$ {curr['gasto_essencial']:.2f}
- Não essenciais: R$ {curr['gasto_nao_essencial']:.2f}
- Percentual não essencial: {perc_nao_essencial:.1f}%

EFICIÊNCIA:
- KM rodados: {curr['km']:.1f}
- Ganho/KM: R$ {curr['rs_km']:.2f}
- Horas trabalhadas: {curr['horas']:.1f}
- Ganho/Hora: R$ {curr['rs_hora']:.2f}

PERFORMANCE POR APP:
{apps_str}

COMPARAÇÃO COM PERÍODO ANTERIOR:
{prev_str}

=========================
REGRAS DE RACIOCÍNIO
=========================

Você DEVE identificar:

1. Tempo morto
Se R$/KM estiver alto e R$/Hora baixo:
→ suspeite de espera, trânsito ou baixa produtividade.

2. Correria pouco lucrativa
Se R$/Hora alto mas R$/KM ruim:
→ operação acelerada mas desgastando o carro.

3. Lucro enganoso
Lucro alto + gasto excessivo:
→ alertar sustentabilidade.

4. Dependência perigosa
Se um app representar a maior parte do ganho:
→ alertar concentração de risco.

5. Tendência
Compare com período anterior:
- Melhorou?
- Piorou?
- Estagnou?

6. Sustentabilidade
Analise se o ritmo parece sustentável ou se pode gerar desgaste físico/mecânico.

7. Eficiência operacional
Dizer claramente:
- valeu a pena?
- foi uma semana forte?
- fraca?
- operacionalmente saudável?

=========================
ESTILO DE ESCRITA
=========================

A resposta deve parecer escrita por um gerente financeiro experiente e humano.

Misture:
- crítica construtiva
- elogio quando merecido
- visão prática
- percepção operacional
- conselho direto

Se houver problema:
Seja firme, mas útil.

Exemplo:
"Você tá faturando, mas parte desse dinheiro está escorrendo em gasto bobo. Se isso continuar, no fechamento do mês vai parecer que trabalhou muito pra sobrar pouco."

Se houver mérito:
Reconheça.

Exemplo:
"O Correios segurou bem a operação. Pagamento por hora ficou forte e o km trabalhou a favor, o que mostra uma rota saudável."

=========================
FORMATO OBRIGATÓRIO
=========================

ANÁLISE DA SHOPEE
[TEXTO COMPLETO]

ANÁLISE DOS CORREIOS
[TEXTO COMPLETO]

ANÁLISE GERAL DA EMPRESA
[TEXTO COMPLETO]

DIAGNÓSTICO OPERACIONAL
• Eficiência do tempo:
• Eficiência do veículo:
• Sustentabilidade:
• Principal gargalo:
• Principal acerto:

RECOMENDAÇÕES ESTRATÉGICAS
• [recomendação prática e objetiva]
• [recomendação financeira]
• [recomendação operacional]

A análise deve ser detalhada, útil, humana e parecer feita por um especialista real.
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
