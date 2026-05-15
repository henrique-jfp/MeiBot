# Plano de Implementação: Dissecação de Cartões (Modo Deus)

Este plano visa restaurar a visibilidade dos cartões de crédito e aprofundar a análise de evolução de gastos na aba "Contas".

## 1. Backend (`analytics/dashboard_app.py`)

### 1.1. Fallback de Evolução de Faturas
- Alterar a query de `f_evol` para que, caso não existam pelo menos 2 faturas fechadas históricas, o sistema realize uma query na tabela `Lancamento`.
- A query de fallback filtrará lançamentos negativos em contas do tipo 'Cartão de Crédito' nos últimos 6 meses, agrupando por mês e ano.
- Isso garante que o gráfico nunca fique vazio para usuários novos ou com poucos dados de Open Finance.

### 1.2. Injeção da Lista de Cartões (`result['cartoes']`)
- Iterar sobre todas as contas do tipo 'Cartão de Crédito' do usuário.
- Para cada conta, buscar o snapshot de saldo mais recente (`SaldoConta`).
- Extrair:
    - `valor_total`: O `saldo` do snapshot (representa o gasto atual da fatura).
    - `limite_disponivel`: O `saldo_disponivel` do snapshot.
    - `limite_cartao`: O limite cadastrado na conta ou no snapshot.
- Projetar a `data_vencimento` baseada no `dia_vencimento` da conta.
- Definir o status dinamicamente ('aberta', 'fechada', 'zerada').

## 2. Frontend (`static/js/miniapp/app.js`)

### 2.1. Renderização de `mdCartoesList`
- Validar se o código de renderização está tratando corretamente os novos campos.
- Garantir que a barra de progresso reflita o uso do limite: `(valor_total / limite_cartao) * 100`.
- Aplicar cores dinâmicas: Verde (< 50%), Amarelo (50-80%), Vermelho (> 80%).

## 3. Validação
- Verificar se o gráfico `mdFaturasChart` exibe as colunas corretamente.
- Confirmar se a lista de "Faturas Ativas" aparece logo abaixo do gráfico com os valores reais de limite e uso.

---
**Status:** Aguardando aprovação para execução.
