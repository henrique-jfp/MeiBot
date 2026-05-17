# Mapa de arquivos do MeiBot

## Visao geral (arquitetura)
- WhatsApp Bot (Node.js): recebe mensagens, valida fluxo e envia para o backend.
- Backend (FastAPI): interpreta, persiste, calcula metricas, gera insights e serve o dashboard.
- Supabase (PostgreSQL): armazenamento principal.

## Estrutura por area

### Backend (FastAPI + logica)
- [backend/app/main.py](backend/app/main.py)
  - Define a API principal (/webhook, /api/dashboard, /dashboard).
  - Monta o HTML do dashboard dentro do proprio arquivo (front embutido).
  - Contem o fluxo de intencoes (iniciar, encerrar, resumo, perguntas, porteiros).
- [backend/app/ai_service.py](backend/app/ai_service.py)
  - Interpretacao de mensagens (Groq/Gemini) em JSON.
  - OCR de imagens, transcricao de audio e geracao de insights.
- [backend/app/db.py](backend/app/db.py)
  - Acesso ao Supabase e funcoes de leitura/escrita.
  - Funcoes de operacoes, eventos, apps e porteiros.
- [backend/app/logic.py](backend/app/logic.py)
  - Calculo de metricas e formatacao do resumo.
- [backend/app/routes_claim/router.py](backend/app/routes_claim/router.py)
  - Rotas da feature de rotas/planilhas (parse de imagem/PDF).
- [backend/app/routes_claim/ai_routes.py](backend/app/routes_claim/ai_routes.py)
  - Parser de rotas (OCR + heuristicas + Gemini opcional).

### WhatsApp Bot (Node.js)
- [whatsapp-bot/src/index.js](whatsapp-bot/src/index.js)
  - Entry-point do bot.
- [whatsapp-bot/src/whatsapp.js](whatsapp-bot/src/whatsapp.js)
  - Conexao Baileys, filtros anti-loop e envio ao backend.
- [whatsapp-bot/src/api.js](whatsapp-bot/src/api.js)
  - Cliente HTTP para /webhook.
- [whatsapp-bot/src/routes-claim/handler.js](whatsapp-bot/src/routes-claim/handler.js)
  - Captura de imagens/PDF de rotas nos grupos e envio para parse.
- [whatsapp-bot/src/routes-claim/routeApi.js](whatsapp-bot/src/routes-claim/routeApi.js)
  - Chamada para /routes-claim/parse do backend.
- [whatsapp-bot/src/routes-claim/state.js](whatsapp-bot/src/routes-claim/state.js)
  - Estado da feature de rotas (locks, cache, candidatos).
- [whatsapp-bot/src/routes-claim/selection.js](whatsapp-bot/src/routes-claim/selection.js)
  - Normalizacao e selecao de rota candidata.
- [whatsapp-bot/src/routes-claim/config.js](whatsapp-bot/src/routes-claim/config.js)
  - Configuracoes de grupos, horarios e regras de claim.

### Banco de dados (SQL)
- [database/init.sql](database/init.sql)
  - Tabelas base: users, apps, operacoes_dia, eventos.
- [database/upgrade_management.sql](database/upgrade_management.sql)
  - Evolucao do schema: entregadores, campos em apps e eventos.
- [database/create_porteiros.sql](database/create_porteiros.sql)
  - Tabela mapeamento_porteiros.
- [database/add_categoria_column.sql](database/add_categoria_column.sql)
  - Coluna de categoria em eventos.
- [database/fix_rls.sql](database/fix_rls.sql)
  - Ajuste de RLS no Supabase.

### Scripts utilitarios (backend/)
- [backend/cron_reports.py](backend/cron_reports.py)
  - Gera relatorios semanais/mensais e salva historico.
- [backend/reprocess_weeks.py](backend/reprocess_weeks.py)
  - Reprocessa as duas ultimas semanas no historico.
- [backend/reprocess.py](backend/reprocess.py)
  - Reprocessa uma analise semanal antiga.
- [backend/fetch_history.py](backend/fetch_history.py)
  - Diagnostico e impressao de historico.
- [backend/backfill_espera_galpao.py](backend/backfill_espera_galpao.py)
  - Ajusta/cria eventos de espera de galpao.
- [backend/normalize_porteiros.py](backend/normalize_porteiros.py)
  - Normaliza dados de porteiros.
- [backend/cleanup_porteiros.py](backend/cleanup_porteiros.py)
  - Deduplica/limpa mapeamento de porteiros.
- [backend/diag_db.py](backend/diag_db.py)
  - Diagnostico rapido de base/usuario.
- [backend/diag_users.py](backend/diag_users.py)
  - Lista usuarios cadastrados.
- [backend/merge_users.py](backend/merge_users.py)
  - Mescla usuarios em casos de duplicidade.

### Documentacao
- [README.md](README.md)
  - Guia geral de instalacao e execucao.
- [docs/tests.md](docs/tests.md)
  - Casos de teste de funcionalidades principais.

## Onde esta o front-end
- O dashboard e totalmente renderizado dentro de [backend/app/main.py](backend/app/main.py) (HTML + Tailwind + JS embutidos no endpoint /dashboard).
- Nao ha pasta dedicada de front (SPA). O frontend e servido pelo backend.

## Conexoes entre arquivos (fluxo principal)

1) WhatsApp -> Backend
- [whatsapp-bot/src/whatsapp.js](whatsapp-bot/src/whatsapp.js) recebe mensagem e envia payload para
- [whatsapp-bot/src/api.js](whatsapp-bot/src/api.js) -> POST /webhook
- [backend/app/main.py](backend/app/main.py) processa a intencao e persiste via
- [backend/app/db.py](backend/app/db.py)

2) Interpretacao e IA
- [backend/app/main.py](backend/app/main.py) chama
- [backend/app/ai_service.py](backend/app/ai_service.py) para interpretar texto, audio e imagem
- Os dados extraidos viram eventos persistidos em [backend/app/db.py](backend/app/db.py)

3) Calculo e resumo
- [backend/app/logic.py](backend/app/logic.py) calcula metricas
- [backend/app/logic.py](backend/app/logic.py) monta o texto do resumo
- [backend/app/ai_service.py](backend/app/ai_service.py) gera insights (semanais/mensais)

4) Dashboard
- [backend/app/main.py](backend/app/main.py) expõe /api/dashboard e /dashboard
- JS do dashboard consome /api/dashboard e renderiza cards/graficos

5) Rotas/Planilhas (routes-claim)
- [whatsapp-bot/src/routes-claim/handler.js](whatsapp-bot/src/routes-claim/handler.js) detecta imagens/planilhas
- [whatsapp-bot/src/routes-claim/routeApi.js](whatsapp-bot/src/routes-claim/routeApi.js) chama /routes-claim/parse
- [backend/app/routes_claim/router.py](backend/app/routes_claim/router.py) recebe
- [backend/app/routes_claim/ai_routes.py](backend/app/routes_claim/ai_routes.py) faz OCR e parse

## Mapa por feature (o que faz cada funcionalidade funcionar)

### Registro de ganhos/gastos/rotas (texto)
- Entrada: [whatsapp-bot/src/whatsapp.js](whatsapp-bot/src/whatsapp.js)
- Interpretacao: [backend/app/ai_service.py](backend/app/ai_service.py)
- Persistencia: [backend/app/db.py](backend/app/db.py)
- Logica adicional de evento/espera: [backend/app/main.py](backend/app/main.py)

### Registro por imagem (OCR)
- Captura no WhatsApp: [whatsapp-bot/src/whatsapp.js](whatsapp-bot/src/whatsapp.js)
- OCR/interpretacao: [backend/app/ai_service.py](backend/app/ai_service.py)
- Persistencia: [backend/app/db.py](backend/app/db.py)

### Registro por audio (transcricao)
- Captura no WhatsApp: [whatsapp-bot/src/whatsapp.js](whatsapp-bot/src/whatsapp.js)
- Transcricao: [backend/app/ai_service.py](backend/app/ai_service.py)
- Interpretacao e persistencia: [backend/app/main.py](backend/app/main.py) + [backend/app/db.py](backend/app/db.py)

### Resumo diario
- Intencao e gatilho: [backend/app/main.py](backend/app/main.py)
- Calculo e texto: [backend/app/logic.py](backend/app/logic.py)
- Insight curto: [backend/app/ai_service.py](backend/app/ai_service.py)

### Resumo semanal/mensal
- Intencao e gatilho: [backend/app/main.py](backend/app/main.py)
- Busca de eventos por periodo: [backend/app/db.py](backend/app/db.py)
- Calculo: [backend/app/logic.py](backend/app/logic.py)
- Insight estrategico: [backend/app/ai_service.py](backend/app/ai_service.py)
- Reprocessamento manual: [backend/reprocess_weeks.py](backend/reprocess_weeks.py)

### Dashboard (visual)
- Backend HTML/JS: [backend/app/main.py](backend/app/main.py)
- Dados via API: [backend/app/main.py](backend/app/main.py)
- Calculo de metricas: [backend/app/logic.py](backend/app/logic.py)

### Porteiros (cadastro/consulta)
- Intencoes e respostas: [backend/app/main.py](backend/app/main.py)
- Persistencia e consultas: [backend/app/db.py](backend/app/db.py)
- Schema: [database/create_porteiros.sql](database/create_porteiros.sql)

### Relatorios automaticos
- Agendamento/geracao: [backend/cron_reports.py](backend/cron_reports.py)
- Persistencia historico: [backend/app/db.py](backend/app/db.py)

### Rotas/Planilhas (claim em grupos)
- Captura e controle: [whatsapp-bot/src/routes-claim/handler.js](whatsapp-bot/src/routes-claim/handler.js)
- Estado e selecao: [whatsapp-bot/src/routes-claim/state.js](whatsapp-bot/src/routes-claim/state.js) + [whatsapp-bot/src/routes-claim/selection.js](whatsapp-bot/src/routes-claim/selection.js)
- Parser no backend: [backend/app/routes_claim/ai_routes.py](backend/app/routes_claim/ai_routes.py)

## Observacoes
- O front do dashboard nao e separado em pasta: fica embutido no backend.
- O bot do WhatsApp usa um numero fixo no envio para o backend; isso pode impactar multiusuario.
