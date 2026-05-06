const axios = require('axios');
require('dotenv').config();

// Se não achar a URL no .env, usa o localhost como padrão para evitar erro de 'replace'
const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000/webhook';

const api = axios.create({
    baseURL: backendUrl.replace('/webhook', ''),
    timeout: 30000,
});

async function sendToBackend(payload) {
    try {
        const response = await api.post('/webhook', payload);
        return response.data.reply;
    } catch (error) {
        console.error('Error calling backend:', error.message);
        return '❌ Ops! Tive um problema para processar sua mensagem agora. O backend está rodando?';
    }
}

module.exports = { sendToBackend };
