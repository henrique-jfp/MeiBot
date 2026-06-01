# 🧪 Exemplos de Teste (Entrada e Saída Esperada)

Este documento lista exemplos de como o MeiBot deve reagir a diferentes entradas.

---

## 1. Comandos de Fluxo

### Início de Operação
*   **Entrada:** "iniciar operação"
*   **Ação Interna:** Cria registro em `operacoes_dia` com `status='ativa'`.
*   **Resposta:** "🚀 Operação iniciada! Boa sorte nas entregas, parceiro!"

### Fim de Operação
*   **Entrada:** "encerrar dia" ou "encerrar operação"
*   **Ação Interna:** Atualiza `operacoes_dia` para `encerrada` e calcula métricas.
*   **Resposta:**
    📊 *RESUMO DA OPERAÇÃO*
    💰 Ganho Total: R$ 260.00
    ⛽ Gastos: R$ 50.00
    💵 Lucro Líquido: R$ 210.00
    🛣️ KM Rodados: 25.0 km
    📦 Pacotes: 120
    ...

---

## 2. Registro de Dados

### Corrida Simples
*   **Entrada:** "fiz uma de 15 no uber 3km"
*   **IA Interpreta:** `{"tipo": "corrida", "valor": 15, "app": "Uber", "km": 3}`
*   **Resposta:** "✅ Boa! Uber: R$ 15.0 registrado."

### Rota com Pacotes
*   **Entrada:** "rota correios 120 pacotes 240 reais 20km"
*   **IA Interpreta:** `{"tipo": "corrida", "valor": 240, "app": "Correios", "pacotes": 120, "km": 20}`
*   **Resposta:** "✅ Boa! Correios: R$ 240.0 registrado."

### Gasto
*   **Entrada:** "abasteci 50 reais de gasolina"
*   **IA Interpreta:** `{"tipo": "gasto", "valor": 50}`
*   **Resposta:** "⛽ Gasto de R$ 50.0 anotado."

---

## 3. Consultas por IA

### Pergunta sobre Ganhos
*   **Entrada:** "quanto eu já ganhei hoje?"
*   **IA Ação:** Consulta eventos do dia no banco e gera resposta natural.
*   **Resposta:** "Até agora você já faturou R$ 260,00, parceiro! O dia tá rendendo bem!"

---

## 4. Imagens (OCR)
*   **Entrada:** [Envia Print do App iFood com valor R$ 45,50]
*   **IA Interpreta (Gemini Vision):** `{"tipo": "corrida", "valor": 45.50, "app": "iFood"}`
*   **Resposta:** "✅ Boa! iFood: R$ 45.5 registrado."

---

## 5. Áudio

### Áudio com Registro de Operação
*   **Entrada:** [Áudio] "fiz correios, 154 pacotes, finalizei 18:45 e gastei 23 reais"
*   **Ação Interna:** Bot envia `type="audio"` para o backend, backend transcreve o áudio e interpreta o texto resultante.
*   **Resposta:** Confirmação de registro com os eventos extraídos do áudio.

### Áudio com Registro de Correios sem Valor Explícito
*   **Entrada:** [Áudio] "fiz correios, 154 pacotes"
*   **Ação Interna:** Backend precisa aceitar `valor=null` vindo da IA sem quebrar ao normalizar o evento.
*   **Resposta:** Confirmação de registro usando o cálculo padrão de Correios.

### Áudio sem Transcrição Útil
*   **Entrada:** [Áudio com ruído ou vazio]
*   **Ação Interna:** Backend tenta transcrever antes de interpretar.
*   **Resposta:** "Não consegui transcrever o áudio. Tente enviar em texto."

### Áudio com Comando de Fluxo
*   **Entrada:** [Áudio] "iniciar operação", "encerrar operação", "resumo da semana" ou "quanto ganhei hoje?"
*   **Ação Interna:** Backend transcreve o áudio e trata a intenção retornada pela IA sem cair no fallback genérico `Processado.`.
*   **Resposta:** Mensagem específica da ação pedida.

---

## 6. Imagem sem Legenda

### Print do App sem Texto
*   **Entrada:** [Imagem sem legenda com comprovante/print do app]
*   **Ação Interna:** Bot envia `type="image"` e `mime_type`, backend roda OCR e interpreta os dados detectados.
*   **Resposta:** Confirmação de registro dos eventos encontrados na imagem ou resposta padrão de processamento.

---

## 7. Porteiros

### Cadastro de Porteiro por Áudio
*   **Entrada:** [Áudio] "cadastra o porteiro João na Rua das Flores 123 no turno da noite"
*   **Ação Interna:** Backend transcreve o áudio, interpreta `cadastrar_porteiro` e persiste o cadastro em `mapeamento_porteiros`.
*   **Resposta:** Confirmação de cadastro com endereço e dados extraídos.

### Consulta de Porteiro por Endereço
*   **Entrada:** "quem é o porteiro da Rua das Flores 123?"
*   **Ação Interna:** Backend interpreta `consultar_porteiro` e busca o endereço no banco.
*   **Resposta:** Lista dos porteiros cadastrados naquele prédio ou mensagem de ausência.

### Listagem de Porteiros
*   **Entrada:** "porteiros" ou "meus porteiros"
*   **Ação Interna:** Backend interpreta `listar_porteiros` e retorna todos os registros do usuário.
*   **Resposta:** Lista formatada de porteiros ou aviso de que ainda não há mapeamento.

### Correção de Porteiro sem Nome Atual
*   **Entrada:** "Corrigir nome do porteiro da Rua Senador Vergueiro, 85. O nome correto é Joyce Cerqueira"
*   **Ação Interna:** Backend interpreta `corrigir_porteiro`, busca o endereço e, se houver apenas um cadastro naquele prédio, corrige o nome mesmo sem o usuário informar o nome antigo.
*   **Resposta:** Confirmação da atualização do porteiro com o nome corrigido.

### Correção de Horário de Operação
*   **Entrada:** "Corrigir horário de início da operação dos Correios de hoje, o horário correto é 15:20"
*   **Ação Interna:** Backend interpreta `corrigir_registro`, identifica a operação do dia e atualiza o horário do registro compatível, além do horário da operação quando aplicável.
*   **Resposta:** Confirmação da correção com o campo ajustado.

---

## 8. Relatórios Automáticos

### Fechamento Semanal
*   **Entrada:** `python cron_reports.py semanal --reference-date 2026-05-31`
*   **Ação Interna:** Gera análise fechada de segunda a sábado, com `period_start=2026-05-25` e `period_end=2026-05-30`.
*   **Resposta Esperada:** Registro em `historico_analises` com `periodo_tipo='semanal'`, sem depender do dashboard ao vivo.

### Fechamento Mensal no Dia 1
*   **Entrada:** `python cron_reports.py mensal --reference-date 2026-06-01`
*   **Ação Interna:** Gera análise do mês anterior, com `period_start=2026-05-01` e `period_end=2026-05-31`.
*   **Resposta Esperada:** Registro em `historico_analises` com `periodo_tipo='mensal'`, mesmo com o dashboard ao vivo já zerado para junho.

### Reprocessamento Idempotente
*   **Entrada:** `python cron_reports.py mensal 2026-05-01 2026-05-31 --no-notify`
*   **Ação Interna:** Busca análise existente pelo mesmo `user_id`, `periodo_tipo` e `metrics.period_start`.
*   **Resposta Esperada:** Atualiza a análise existente quando houver uma; cria uma nova apenas se o período ainda não existir.
