---
name: bot-loop-debugger
description: Use esta skill para testes end-to-end de bots com loop completo, quando o usuário pedir para testar um fluxo do bot, investigar por que o bot não respondeu, analisar falhas silenciosas em produção, depurar comunicação Telegram + backend, cruzar resposta visível ao usuário com logs do servidor ou Render e aplicar correções no código com base nos erros encontrados.
---

# bot-loop-debugger

## Objetivo
Realizar testes de integração ponta a ponta ("full-loop") disparando comandos reais para o bot, coletando a resposta final recebida pelo usuário e cruzando esse comportamento com logs de produção/servidor para identificar falhas silenciosas, regressões, timeouts e erros de integração.

## Quando usar
Use esta skill quando o usuário pedir algo como:
- "teste o fluxo X do bot"
- "verifique por que o bot não respondeu"
- "debug de produção da feature Y"
- "investigue erro de comunicação no bot"
- "veja o que aconteceu no Telegram e nos logs"

## Workflow obrigatório

### 1. Disparo da ação
- Use o MCP do Telegram para enviar uma mensagem natural ou comando real diretamente ao bot de teste ou produção.
- Simule o comportamento do usuário final com inputs realistas, como `/start` ou "gastei 50 reais no mercado".

### 2. Coleta da resposta UI
- Aguarde até 10 segundos.
- Use o MCP do Telegram para ler a última resposta recebida do bot.
- Registre:
  - se houve resposta;
  - qual foi a resposta;
  - se a formatação HTML/markup está correta;
  - se a resposta pareceu genérica, truncada, errada ou ausente.

### 3. Auditoria de logs
- Logo após a interação, acesse o MCP do Render.
- Busque os logs mais recentes do serviço Web e/ou Worker relevante.
- Procure especialmente por:
  - stack traces;
  - bloqueios por I/O síncrono ou thread bloqueada;
  - erros de SQLAlchemy;
  - falhas em Whisper, Cerebras ou Gemini;
  - timeouts, retries, exceções de rede e falhas de serialização.

### 4. Cruzamento UI x backend
Compare o que o usuário viu no Telegram com o que aconteceu no backend.

Cenários comuns:
- Silent failure: o bot responde algo genérico, mas o log mostra o erro real.
- Timeout: o bot não responde, e os logs indicam bloqueio da thread principal ou operação síncrona longa.
- Regressão funcional: o fluxo antes funcionava e agora quebra em etapa diferente da UI.
- Erro de formatação: a lógica executa, mas a resposta enviada ao Telegram vem inválida ou mal formatada.

### 5. Correção automática
- Identifique o arquivo e o trecho de código com falha.
- Corrija seguindo os padrões do projeto.
- Exemplos:
  - mover operações bloqueantes para `run_in_executor`;
  - corrigir queries ORM/SQLAlchemy;
  - tratar exceções de integrações externas;
  - ajustar serialização, parsing ou HTML da resposta.
- Depois da correção, explique claramente:
  - (A) o erro real encontrado nos logs;
  - (B) o que o usuário viu no Telegram;
  - (C) a correção aplicada no código.

## Regras
- Sempre priorize evidência observável em Telegram + logs, não suposição.
- Sempre registrar se houve ou não resposta visível ao usuário.
- Sempre cruzar horário/evento da interação com os logs correspondentes.
- Não concluir diagnóstico apenas com base na UI.
- Se faltar acesso a MCPs ou logs, informe exatamente o bloqueio.

## Referências
- Leia `references/telegram-debug-checklist.md`
- Leia `references/render-log-triage.md`
- Leia `references/common-failures.md`