import os
import json
import datetime
import google.generativeai as genai
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

# Configure Groq
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

class AIService:
    @staticmethod
    async def transcribe_audio(audio_bytes: bytes):
        # Groq Whisper espera um arquivo em disco ou um objeto file-like
        temp_filename = "temp_audio.ogg"
        with open(temp_filename, "wb") as f:
            f.write(audio_bytes)
        
        with open(temp_filename, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(temp_filename, file.read()),
                model="whisper-large-v3",
                response_format="text",
                language="pt"
            )
        
        os.remove(temp_filename)
        return transcription

    @staticmethod
    async def interpret_message(text: str):
        hoje = datetime.date.today().isoformat()
        
        prompt = f"""
        Você é um assistente de um entregador. Sua tarefa é extrair dados de mensagens sobre o dia de trabalho.
        Hoje é dia {hoje}. 
        Se o usuário mencionar uma data passada (ex: "ontem", "segunda"), preencha "data_referencia" com YYYY-MM-DD.
        Se ele informar horário de trabalho (ex: "de 10h às 15h"), preencha "hora_inicio" e "hora_fim" no formato "HH:MM:SS".

        A mensagem pode conter múltiplas ações (um "resumão"). Converta a mensagem num JSON estruturado EXATAMENTE neste formato:
        {{
            "intencao": "iniciar" | "encerrar" | "pergunta" | "registro" | "resumo_semanal" | "resumo_mensal" | "cadastrar_porteiro" | "corrigir_porteiro" | "consultar_porteiro" | "listar_porteiros",
            "data_referencia": "YYYY-MM-DD" ou null,
            "hora_inicio": "HH:MM:SS" ou null,
            "hora_fim": "HH:MM:SS" ou null,
            "pergunta": "texto da pergunta" ou null,
            "porteiro_info": {{
                "rua": "Nome da rua" ou null,
                "numero": "123" ou null,
                "nome": "Nome do porteiro" ou null,
                "nome_antigo": "Nome anterior (apenas para correção/troca)" ou null,
                "turno": "manhã/tarde/noite" ou null,
                "notas": "Notas do prédio" ou null
            }},
            "eventos": [
                {{
                    "tipo": "rota" | "gasto" | "pausa" | "ajuste" | "espera",
                    "categoria": "Essencial" | "Não Essencial" | null,
                    "tempo_minutos": int,
                    "valor": float,
                    "km": float,
                    "app": "Nome do app" ou null,
                    "pacotes": int,
                    "descricao": "Detalhe" ou null
                }}
            ]
        }}
        Quando usar as intenções de resumo:
        - 'resumo_semanal': Quando o usuário pedir explicitamente o resumo da semana, dos últimos dias ou quanto ganhou na semana.
        - 'resumo_mensal': Quando o usuário pedir o resumo do mês, do mês passado ou quanto ganhou no mês.
        
        Intenções de Porteiros:
        - 'cadastrar_porteiro': Quando o usuário informar nome de porteiro e endereço para salvar.
        - 'corrigir_porteiro': Quando o usuário pedir para trocar, alterar ou corrigir um nome ou nota já existente.
        - 'consultar_porteiro': Quando o usuário perguntar quem é o porteiro de um endereço ou o que tem anotado sobre um prédio.
        - 'listar_porteiros': Quando o usuário pedir para ver o mapeamento completo, a lista de todos os nomes ou o link do mapeamento.

        Regras de Categoria para 'gasto':
        - 'Essencial': Combustível, manutenção, óleo, seguro, taxas do app.
        - 'Não Essencial': Cigarro, refrigerante, lanches, café, gastos pessoais não ligados ao trabalho.

        Regras para 'espera':
        - Use quando o usuário mencionar atraso no galpão, espera de carga ou tempo parado aguardando.
        - Exemplo: "Cheguei 13h e peguei a rota 13h40" -> GERAR UM EVENTO SEPARADO do tipo 'espera' com tempo_minutos: 40.

        Regras para 'rota':
        - Representa o tempo real de entregas/trabalho.
        - Se o usuário der os horários (ex: peguei a rota 13h40 e terminei 18h), calcule a duração apenas desse período e coloque em 'tempo_minutos'.
        
        IMPORTANTE: 'rota' e 'espera' DEVEM ser dois itens separados na lista 'eventos'. Nunca misture o tempo de espera dentro do item de rota.
        
        Se não houver valor, km, pacotes ou tempo_minutos, use 0.

        Mensagem: "{text}"

        Retorne APENAS o objeto JSON e nada mais.
        """
        
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Você é um extrator de dados JSON preciso. Retorne apenas o objeto JSON."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            response_format={ "type": "json_object" }
        )
        
        return json.loads(chat_completion.choices[0].message.content)

    @staticmethod
    async def process_image(image_bytes: bytes, mime_type: str):
        prompt = """
        Analise este print de um aplicativo de entregas.
        Extraia:
        1. Valor total ganho na imagem.
        2. Aplicativo (ex: iFood, Uber, Rappi).
        3. Quilometragem (se houver).
        4. Quantidade de entregas/corridas (se houver).

        Retorne no formato JSON:
        {
            "intencao": "registro",
            "data_referencia": null,
            "hora_inicio": null,
            "hora_fim": null,
            "pergunta": null,
            "eventos": [
                {"tipo": "corrida", "valor": 0.0, "app": "", "km": 0.0, "pacotes": 0, "descricao": "Print lido"}
            ]
        }
        """
        
        response = gemini_model.generate_content([
            prompt,
            {"mime_type": mime_type, "data": image_bytes}
        ])
        
        text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(text)

    @staticmethod
    async def answer_question(context: str, question: str):
        prompt = f"""
        Com base nos dados das entregas abaixo:
        {context}
        
        Responda à pergunta do entregador: "{question}"
        
        Seja direto, motivador e use uma linguagem natural de "parceiro de estrada".
        """
        
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile"
        )
        
        return chat_completion.choices[0].message.content

    @staticmethod
    async def generate_analyst_insight(current_metrics: dict, previous_metrics: dict, period_type: str):
        prompt = f"""
        Você é um ANALISTA DE DADOS FODA especializado em logística e delivery.
        Seu objetivo é analisar o desempenho de um entregador e dar uma visão real, nua e crua, sem enrolação.

        REGRAS DE OURO DA ANÁLISE:
        1. Ganho por KM (R$/KM): 1 (Ruim), 2 (Regular), 3 (Bom), 4 (Muito bom), 5+ (Excelente).
        2. Gastos Não Essenciais (% do Ganho Bruto): 3% (Ok), 5% (Alerta Laranja), 7%+ (Alerta Vermelho).
        3. Ganho por Hora (R$/Hora): 20 (Péssimo), 30 (Regular), 40 (Bom), 50 (Muito bom), 60+ (Excelente).

        DADOS ATUAIS ({period_type}):
        - Ganho Total: R$ {current_metrics['total_ganho']:.2f}
        - Lucro Líquido: R$ {current_metrics['lucro_liquido']:.2f}
        - R$/KM: R$ {current_metrics['rs_km']:.2f}
        - R$/Hora (Rua): R$ {current_metrics['rs_hora']:.2f}
        - Horas Produtivas (Rua): {current_metrics['horas_produtivas']:.1f}h
        - Tempo de Espera (Galpão): {current_metrics['tempo_espera_horas']:.1f}h
        - % Gastos Não Essenciais: {current_metrics['percentual_nao_essenciais']:.1f}%

        DADOS DO PERÍODO ANTERIOR:
        - Ganho Total: R$ {previous_metrics['total_ganho']:.2f}
        - R$/KM: R$ {previous_metrics['rs_km']:.2f}
        - R$/Hora (Rua): R$ {previous_metrics['rs_hora']:.2f}
        - Tempo de Espera (Galpão): {previous_metrics.get('tempo_espera_horas', 0):.1f}h

        TAREFA:
        Compare os períodos. Diga o que melhorou ou piorou. Julgue o desempenho atual baseado nas REGRAS DE OURO acima.
        Dê atenção especial ao Tempo de Espera: se for alto, critique a ineficiência do galpão.
        Seja direto, use linguagem de "parceiro de estrada" mas com a autoridade de um analista foda.
        Termine com uma "Dica de Ouro" prática para o próximo período.
        Limite o texto a no máximo 4 parágrafos curtos.
        """
        
        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Você é um analista de performance experiente e direto."},
                    {"role": "user", "content": prompt}
                ],
                model="llama-3.3-70b-versatile"
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            print(f"Error generating analyst insight: {e}")
            return "Não consegui gerar a análise agora, mas os números acima estão salvos. Mantenha o foco!"
