const express = require('express');

let currentSock = null;
let serverStarted = false;

/**
 * Atualiza a instância do socket utilizada pelo servidor.
 * @param {import('@whiskeysockets/baileys').WASocket} sock
 */
function updateSocket(sock) {
    currentSock = sock;
}

/**
 * Inicializa o servidor HTTP para o WhatsApp Bot.
 */
function startServer() {
    if (serverStarted) return;
    
    const app = express();
    app.use(express.json());

    const PORT = process.env.BOT_PORT || 3000;

    app.post('/send-message', async (req, res) => {
        const { to, text } = req.body;

        if (!to || !text) {
            return res.status(400).json({ error: 'Campos "to" e "text" são obrigatórios.' });
        }

        if (!currentSock) {
            return res.status(503).json({ error: 'WhatsApp não está conectado ainda.' });
        }

        try {
            // Formata o JID se necessário (número@s.whatsapp.net ou número@lid)
            const jid = to.includes('@') ? to : `${to.split(':')[0]}@s.whatsapp.net`;
            
            console.log(`[HTTP-SERVER] Enviando mensagem externa para ${jid}`);
            
            await currentSock.sendMessage(jid, { text });
            
            return res.json({ success: true, message: 'Mensagem enviada com sucesso.' });
        } catch (error) {
            console.error('[HTTP-SERVER] Erro ao enviar mensagem externa:', error.message);
            return res.status(500).json({ error: 'Falha ao enviar mensagem via WhatsApp.' });
        }
    });

    app.listen(PORT, () => {
        console.log(`[HTTP-SERVER] Servidor rodando na porta ${PORT}`);
        serverStarted = true;
    });
}

module.exports = { startServer, updateSocket };
