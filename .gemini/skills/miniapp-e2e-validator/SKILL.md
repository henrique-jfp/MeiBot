---
name: miniapp-e2e-validator
description: Use esta skill para testar o MiniApp hospedado ponta a ponta quando o usuário pedir para testar o miniapp, validar a interface, revisar o visual do dashboard, verificar renderização frontend, checar performance de carregamento, analisar quebras de UI, inspecionar templates Flask, arquivos static, Tailwind, Chart.js ou rotas Flask após mudanças no frontend ou deploy.
---

# miniapp-e2e-validator

## Objetivo
Testar o carregamento, a renderização e o layout visual do frontend do MiniApp (Flask + Tailwind + Chart.js) diretamente no ambiente hospedado, garantindo boa performance, renderização correta e ausência de quebras visuais ou erros de console.

## Quando usar
Use esta skill quando o usuário pedir algo como:
- "testa o miniapp"
- "valida a interface"
- "olha o dashboard"
- "vê se o frontend quebrou"
- "confere o visual depois do deploy"
- "verifica mudanças em templates, static ou rotas Flask"

Também use após alterações em:
- `templates/`
- `static/`
- rotas Flask que impactem renderização
- componentes visuais do dashboard
- Chart.js, Tailwind ou autenticação do Telegram WebApp

## Workflow obrigatório

### 1. Verificação de deploy
- Use o MCP do Render para confirmar se o último deploy foi concluído com sucesso.
- Recupere a URL pública da aplicação correspondente ao deploy mais recente.

### 2. Acesso e injeção de sessão
- Use MCP Browser ou Playwright para abrir a URL do MiniApp.
- Simule a autenticação do Telegram WebApp com token HMAC válido ou de teste.
- Quando aplicável, injete a sessão por query parameters, headers, cookies ou armazenamento/local state compatível com o fluxo real do app.

### 3. Validação estrutural e de performance
- Meça o tempo de carregamento e verifique se a página principal carrega em menos de 2 segundos.
- Inspecione o DOM para confirmar que os elementos essenciais foram renderizados.
- Verifique a presença e execução correta de:
  - containers principais do Tailwind;
  - canvas ou elementos esperados do Chart.js;
  - dados injetados pelo backend Flask;
  - ausência de erros no console;
  - ausência de falhas de network relevantes.

### 4. Validação visual
- Gere screenshot da página renderizada.
- Analise a captura para identificar:
  - layout quebrado ou desalinhado;
  - gráficos ausentes ou renderizados incorretamente;
  - cores erradas;
  - sobreposição de texto;
  - problemas de spacing;
  - cortes de conteúdo;
  - problemas em viewport móvel.

### 5. Tratamento de falhas e relatório
- Se houver erro 500 ou falha backend, cruzar imediatamente com os logs do Render.
- Se houver falha visual, identificar a div, classe, template ou asset responsável.
- Entregar um relatório curto com:
  - tempo de carregamento;
  - status do deploy;
  - erros de console;
  - erros de backend/logs;
  - problemas visuais encontrados;
  - feedback estético e de coesão visual.

## Regras
- Sempre validar ambiente hospedado, não apenas ambiente local, quando a task pedir comportamento real de deploy.
- Sempre cruzar falhas visuais com DOM, console e logs antes de concluir.
- Sempre analisar versão desktop e, quando relevante, viewport móvel.
- Sempre apontar o elemento exato afetado quando identificar quebra visual.
- Se faltar acesso ao Render, Browser/Playwright ou autenticação do Telegram WebApp, informar claramente a limitação.