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
        - 'corrigir_registro': Para corrigir dados já lançados de uma operação ou registro existente, como horário, valor, km, pacotes ou gasto lançado errado.
        - 'excluir_registro': Para apagar, remover, deletar ou cancelar um lançamento de ganho ou gasto já feito de uma OPERAÇÃO.
        - 'excluir_porteiro': Para apagar ou remover um porteiro ou prédio cadastrado no mapeamento de endereços.
        - 'pedir_link_dashboard': Quando o usuário pede o link do dashboard, mapa de porteiros, ou painel.

        Regras de Negócio Pessoais (OBRIGATÓRIO):
        - EXCLUSÃO: Se o usuário quiser apagar um "porteiro", "prédio" ou "endereço", use 'excluir_porteiro'. Se quiser apagar um "gasto", "ganho", "corrida" ou "operação", use 'excluir_registro'.
        - NOMES DE PORTEIROS: Capture o nome completo mencionado (ex: "Allan Kardec" não deve virar "Lan Kardec").
        - TURNO VS NOTAS: O campo 'turno' deve conter apenas períodos simples (ex: "Manhã", "Noite", "12h às 18h"). Se o usuário descrever horários complexos, saídas para almoço, ou comportamentos ("sai meio dia", "volta tal hora", "não recebe pacote"), coloque TUDO isso no campo 'notas'. 
        - NOTAS: Ignore frases de comando como "adicionaram uma nota" ou "anota aí". Capture apenas o CONTEÚDO da observação.
        - Se o usuário disser "apagar", "remover", "excluir" ou "deletar" um registro, use intencao: 'excluir_registro'.
        - Se o usuário disser apenas "Porteiro" ou "Porteiros", use intencao: 'listar_porteiros'.
        - Se o usuário pedir o link do mapa ou dashboard, use intencao: 'pedir_link_dashboard'.
        - Se a mensagem contiver um endereço (rua e número) e um nome de pessoa associado a "porteiro", e NÃO for um pedido de correção, use SEMPRE 'cadastrar_porteiro'.
        - Se o usuário pedir para corrigir ou ajustar um porteiro já existente, use SEMPRE 'corrigir_porteiro'. Esta intenção é EXCLUSIVA para endereços e nomes de pessoas.
        - Se o usuário pedir para corrigir ou ajustar um registro já lançado de uma OPERAÇÃO (Correios, Shopee, etc), como horário, valor, KM, pacotes ou gasto, use SEMPRE 'corrigir_registro'. NUNCA use 'corrigir_porteiro' para correções de operação.
        - Exemplo de confusão a EVITAR: "corrigir horário da operação" é 'corrigir_registro', NUNCA 'corrigir_porteiro'.

        Regras de Extração de Eventos (OBRIGATÓRIO):
        1. SEPARAÇÃO DE EVENTOS: O usuário frequentemente relata rotas e gastos no mesmo texto. Você DEVE extrair CADA EVENTO como um objeto separado na lista 'eventos'. (Ex: Se ele fez Correios e comprou cigarro, gere DOIS eventos, um 'ganho' e um 'gasto').
        2. MÚLTIPLAS OPERAÇÕES: O usuário pode fazer mais de uma operação no dia (Ex: Shopee e depois Correios). Crie eventos separados para cada um.
        3. EXTRAÇÃO PURA (SEM MATEMÁTICA): Você é APENAS UM EXTRATOR DE DADOS. NUNCA calcule ganhos ou faça contas. Se o usuário disse "150 pacotes" mas não disse quantos reais ganhou, DEIXE o campo 'valor' como null ou 0. O cálculo será feito pelo backend. Apenas extraia o que foi DITO EXPLICITAMENTE.
        4. GASTOS E DESPESAS IMPLÍCITAS: Textos como "20 reais com cigarro" DEVEM ser interpretados como tipo: 'gasto'. (MUITO IMPORTANTE: Tempos de espera no galpão como "cheguei às 5:00" NUNCA devem ser interpretados como tipo: 'gasto', use apenas os campos de horário no evento de 'ganho').
        5. CATEGORIAS DE GASTOS: Para tipo: 'gasto', classifique a 'categoria' rigorosamente como uma destas: 'Combustível', 'Alimentação', 'Manutenção', 'Essencial', ou 'Outros'.
        6. HORÁRIOS: Identifique os 3 momentos chave da operação e mapeie para os seguintes campos. Ignore o campo legado `hora_saida_galpao`:
           - **`hora_chegada_galpao`**: Use para "cheguei", "cheguei no galpão", "na base às".
           - **`hora_inicio_rota`**: Use para "saí pra rota", "comecei a rota", "sai com a rota", "saí do galpão".
           - **`hora_fim_operacao`**: Use para "finalizei", "terminei a rota", "terminei".
           Retorne TODOS os horários EXCLUSIVAMENTE no formato militar 24h: 'HH:MM'.
        7. DATAS (CUIDADO): O entregador escreve datas no formato BRASILEIRO DD/MM/YYYY. Por exemplo, 04/05/2026 é 4 de Maio (e não 5 de Abril). O campo `data_referencia` deve ser RIGOROSAMENTE retornado em ISO: YYYY-MM-DD.

        Nomes de APP padronizados (use EXATAMENTE estes):
        - 'Shopee', 'Correios', 'Mercado Livre', 'iFood', 'Uber', 'Loggi', 'Lalamove'.

        Campos do JSON:
        7. CONTEXTO GEOGRÁFICO (RIO DE JANEIRO): Se o texto parecer um endereço mas estiver confuso, prefira nomes comuns da região como: "Rua Paissandu", "Rua Barata Ribeiro", "Rua Santa Clara", "Rua Senador Vergueiro", "Avenida Nossa Sra. de Copacabana", "Rua Barão de Ipanema". Corrija erros de transcrição óbvios (ex: "Pais Sandu" -> "Paissandu").

        - intencao: Uma das intenções acima.
        - data_referencia: YYYY-MM-DD (obrigatório se mencionado data ou "ontem", "anteontem", "dia X").
        - pergunta: O texto da pergunta (se intencao for 'pergunta').
        - porteiro_info: objeto {{'rua': 'str', 'numero': 'str', 'nome': 'str', 'turno': 'str', 'notas': 'str', 'nome_antigo': 'str'}} (obrigatório para intenções de porteiro).
        - eventos: lista de objetos {{'app': 'str', 'tipo': 'ganho'|'gasto', 'valor': float, 'km': float, 'pacotes': int, 'hora_chegada_galpao': 'str', 'hora_saida_galpao': 'str', 'hora_inicio_rota': 'str', 'hora_fim_operacao': 'str', 'categoria': 'str', 'descricao': 'str'}}. Em 'corrigir_registro', devolva APENAS os campos que o usuário pediu para corrigir. NÃO preencha campos não mencionados. Em 'excluir_registro', devolva o 'app' e o 'tipo' do registro que deve ser apagado.
        
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
        c = current_metrics or {}
        curr = {
            "ganho": c.get("total_ganhos", 0),
            "gasto_essencial": c.get("gastos_essenciais", 0),
            "gasto_nao_essencial": c.get("gastos_nao_essenciais", 0),
            "saldo": c.get("saldo", 0),
            "km": c.get("km_total", 0),
            "horas": c.get("total_hours", 0),
            "rs_hora": c.get("ganho_por_hora", 0),
            "rs_km": (c.get("total_ganhos", 0) / c.get("km_total")) if c.get("km_total", 0) > 0 else 0
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
                p = int(data.get("pacotes", 0) or 0)
                espera = float(data.get("tempo_espera", 0) or 0)
                dias_espera = int(data.get("dias_espera", 0) or 0)
                h_rua = max(h - espera, 0)
                r_km = g / k if k > 0 else 0
                r_h_total = g / h if h > 0 else 0
                r_h_rua = g / h_rua if h_rua > 0 else 0
                p_h_rua = p / h_rua if h_rua > 0 else 0
                espera_str = (
                    f", Espera galpão: {espera:.1f}h total "
                    f"({espera/dias_espera:.1f}h/dia média em {dias_espera} dias)"
                ) if dias_espera > 0 else ", Sem dados de espera registrados"
                apps_info.append(
                    f"- {name}: Ganho R$ {g:.2f} | {p} pacotes | {k:.0f}km\n"
                    f"  Tempo total: {h:.1f}h (R$ {r_h_total:.2f}/h) | "
                    f"Tempo rota: {h_rua:.1f}h (R$ {r_h_rua:.2f}/h, {p_h_rua:.1f} pac/h){espera_str}"
                )
        
        apps_str = "\n".join(apps_info) if apps_info else "Sem dados detalhados por plataforma."

        prompt = f"""
Você é um consultor financeiro e operacional de elite especializado em logística urbana e entregas (Shopee, Correios, etc).

Você age como um parceiro de negócios experiente que entende de lucro real, tempo morto e desgaste de veículo.

=========================
DADOS DA OPERAÇÃO ({period_type})
=========================
PERÍODO: {period_type}
GANHO BRUTO: R$ {curr['ganho']:.2f}
LUCRO LÍQUIDO: R$ {curr['saldo']:.2f}
KM TOTAL: {curr['km']:.1f} | EFICIÊNCIA: R$ {curr['rs_km']:.2f}/km
HORAS TRABALHADAS: {curr['horas']:.1f} | GANHO/HORA: R$ {curr['rs_hora']:.2f}/h
GASTOS: Essenciais R$ {curr['gasto_essencial']:.2f} | Não essenciais R$ {curr['gasto_nao_essencial']:.2f} ({perc_nao_essencial:.1f}%)
PAC/HORA (RUA): {c.get('pacotes_por_hora_rua', 0):.1f}
DIAS TRABALHADOS: {c.get('days_worked', 1)}

PERFORMANCE POR APP:
{apps_str}

COMPARAÇÃO ANTERIOR:
{prev_str}

=========================
DIRETRIZES DE ESCRITA (CRÍTICO)
=========================
1. NÃO INVENTE NÚMEROS. Use APENAS os dados fornecidos acima. Se um dado não existir (como "horas totais possíveis"), não mencione ou estime.
2. FOCO NO PERÍODO:
   - Se SEMANAL: Foco em tática, rotas da semana, flutuações de apps e ajustes imediatos.
   - Se MENSAL: Foco em estratégia, lucro acumulado, sustentabilidade do negócio e tendências de longo prazo.
3. SEM REPETIÇÃO: Não repita o mesmo conselho várias vezes. Seja direto. Se o app for excelente, elogie e passe para o próximo.
4. ESTILO: Fale como um humano experiente. Use frases curtas e impactantes. NUNCA use "é importante notar que" ou "com base nos dados".

=========================
FORMATO OBRIGATÓRIO
=========================
[ANÁLISE POR APP]
Uma análise concisa para cada app que teve faturamento. Compare a eficiência (R$/KM e R$/Hora) entre eles. Aponte onde o tempo foi perdido (espera).

[OPERAÇÃO GERAL]
Visão consolidada do período. O lucro diário (R$/dia) vale o esforço? O ritmo de gastos está sob controle?

[DIAGNÓSTICO]
- Eficiência do Tempo: [avaliação baseada em R$/Hora]
- Eficiência do Veículo: [avaliação baseada em R$/KM]
- Sustentabilidade: [foco no saldo líquido e gastos não essenciais]
- Gargalo Principal: [o que mais tirou dinheiro/tempo]

[RECOMENDAÇÃO]
Uma única ação prática, curta e direta para o próximo período.
"""
        
        try:
            completion = self.groq_client.chat.completions.create(
                model=self.groq_model_smart,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=1000
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"Groq insight    ailed: {e}. Falling back to Gemini...")
            response = self.gemini_model.generate_content(prompt)
            return response.text
