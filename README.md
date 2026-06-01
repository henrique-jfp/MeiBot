# 🚀 MeiBot - Sistema de Controle para Entregadores

Este projeto é um assistente inteligente via WhatsApp para entregadores gerenciarem suas operações diárias (ganhos, gastos, km, pacotes) usando IA (Gemini e Groq).

## 🛠️ Arquitetura

1.  **whatsapp-bot (Node.js):** Gerencia a conexão com o WhatsApp usando a biblioteca Baileys.
2.  **backend (Python/FastAPI):** Processa as mensagens, usa IA para extrair dados e salva no Supabase.
3.  **Supabase:** Banco de dados PostgreSQL na nuvem.

---

## 📋 Pré-requisitos

*   Node.js 18+
*   Python 3.11+
*   Conta no [Supabase](https://supabase.com/)
*   API Key do [Google Gemini](https://aistudio.google.com/)
*   API Key do [Groq](https://console.groq.com/)

---

## ⚙️ Instalação e Configuração

### 1. Banco de Dados (Supabase)
*   Crie um novo projeto no Supabase.
*   Vá em **SQL Editor** e execute o conteúdo do arquivo `database/init.sql`.

### 2. Backend (FastAPI)
```bash
cd backend
python -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```
*   Preencha o `.env` com suas chaves do Supabase, Gemini e Groq.

### 3. WhatsApp Bot (Node.js)
```bash
cd whatsapp-bot
npm install
cp .env.example .env
```
*   Ajuste o `BACKEND_URL` se necessário.

---

## 🚀 Como Rodar

### Modo Desenvolvimento (Local)

1.  **Iniciar o Backend:**
    ```bash
    cd backend
    uvicorn app.main:app --reload --port 8000
    ```

2.  **Iniciar o Bot:**
    ```bash
    cd whatsapp-bot
    npm start
    ```
    *Escaneie o QR Code que aparecerá no terminal.*

---

## 🖥️ Gerenciamento no Servidor (Produção)

No servidor, os processos são gerenciados pelo `systemd`. Use os comandos abaixo para controlar o sistema:

### Comandos de Status
```bash
# Ver status de tudo
sudo systemctl status meibot-backend
sudo systemctl status meibot-bot

# Ver logs em tempo real
journalctl -u meibot-backend -f
journalctl -u meibot-bot -f
```

### Reiniciar ou Parar Serviços
```bash
# Reiniciar o sistema completo
sudo systemctl restart meibot-backend meibot-bot

# Parar o sistema
sudo systemctl stop meibot-backend meibot-bot

# Iniciar o sistema
sudo systemctl start meibot-backend meibot-bot
```

### Relatórios Automáticos
Os relatórios fechados são gerados por timers `systemd` versionados em `deploy/systemd/`.

```bash
# Ver próximos disparos
systemctl list-timers 'meibot-report-*'

# Ver logs dos jobs
journalctl -u meibot-report-weekly -n 80 --no-pager
journalctl -u meibot-report-monthly -n 80 --no-pager
```

Regras de período:
*   **Semanal:** fecha segunda a sábado e roda no domingo às 00:10.
*   **Mensal:** fecha o mês anterior e roda no dia 1 às 00:20.
*   **Backfill manual:** `cd backend && python cron_reports.py mensal 2026-05-01 2026-05-31 --no-notify`.

---

## ⚠️ Resolução de Problemas (QR Code)

Se o bot desconectar ou você precisar trocar o WhatsApp vinculado, siga este procedimento:

1.  **Pare o serviço do bot:**
    ```bash
    sudo systemctl stop meibot-bot
    ```

2.  **Limpe a sessão antiga:**
    ```bash
    cd ~/MeiBot/whatsapp-bot
    rm -rf auth_info_baileys
    ```

3.  **Gere o novo QR Code manualmente:**
    ```bash
    npm start
    ```
    *Escaneie o código que aparecerá no terminal. Após confirmar a conexão no celular, aperte `Ctrl+C` no terminal.*

4.  **Volte o serviço para o modo automático:**
    ```bash
    sudo systemctl start meibot-bot
    ```

---

## 🧪 Exemplos de Uso

Mande no WhatsApp:

1.  **Iniciar:** "iniciar operação"
2.  **Corrida:** "fiz uma corrida de 20 reais no ifood 5km"
3.  **Rota/Pacotes:** "fiz um rota pelo correios com 120 pacotes, ganhei 240 reais e rodei 20km"
4.  **Gasto:** "abasteci 50 reais"
5.  **Print:** Envie um print da tela de ganhos do seu App.
6.  **Pergunta:** "quanto ganhei hoje?" ou "qual app tá melhor esse mês?"
7.  **Correções:** "Corrigir horário de início da operação dos Correios de hoje, o horário correto é 15:20" ou "Corrigir nome do porteiro da Rua Senador Vergueiro, 85. O nome correto é Joyce Cerqueira"
8.  **Encerrar:** "encerrar operação" (Você receberá um resumo detalhado).

---

## 📝 Notas para Deploy (VPS/Alfredo)
Para rodar em produção no seu servidor:
*   Use o `systemd` para manter os serviços rodando (veja o `README_SERVER.md` para exemplos).
*   Use o `cloudflared` para expor o backend se precisar de acesso externo.
