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

### Passo 1: Iniciar o Backend
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

### Passo 2: Iniciar o Bot
```bash
cd whatsapp-bot
npm start
```
*   Escaneie o QR Code que aparecerá no terminal com o seu WhatsApp.

---

## 🧪 Exemplos de Uso

Mande no WhatsApp:

1.  **Iniciar:** "iniciar operação"
2.  **Corrida:** "fiz uma corrida de 20 reais no ifood 5km"
3.  **Rota/Pacotes:** "fiz um rota pelo correios com 120 pacotes, ganhei 240 reais e rodei 20km"
4.  **Gasto:** "abasteci 50 reais"
5.  **Print:** Envie um print da tela de ganhos do seu App.
6.  **Pergunta:** "quanto ganhei hoje?" ou "qual app tá melhor esse mês?"
7.  **Encerrar:** "encerrar operação" (Você receberá um resumo detalhado).

---

## 📝 Notas para Deploy (VPS/Alfredo)
Para rodar em produção no seu servidor:
*   Use o `systemd` para manter os serviços rodando (veja o `README_SERVER.md` para exemplos).
*   Use o `cloudflared` para expor o backend se precisar de acesso externo.
