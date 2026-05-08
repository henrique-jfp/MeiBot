const { 
    default: makeWASocket, 
    useMultiFileAuthState, 
    DisconnectReason, 
    downloadMediaMessage,
    Browsers,
    fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcode = require('qrcode-terminal');
const pino = require('pino');
const { sendToBackend } = require('./api');
const routeClaim = require('./routes-claim/handler');

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('auth_info_baileys');
    
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log('--- MeiBot WhatsApp Starter ---');

    const sock = makeWASocket({
        version,
        auth: state,
        printQRInTerminal: false,
        logger: pino({ level: 'error' }),
        browser: Browsers.macOS('Desktop'),
        syncFullHistory: false,
        connectTimeoutMs: 60000,
        defaultQueryTimeoutMs: 60000,
        keepAliveIntervalMs: 30000,
        markOnlineOnConnect: true,
        generateHighQualityLinkPreview: false,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        if (qr) {
            console.log('\n--- ESCANEIE O QR CODE ---');
            qrcode.generate(qr, { small: true });
            console.log('--------------------------\n');
        }

        if (connection === 'close') {
            const statusCode = (lastDisconnect.error instanceof Boom) 
                ? lastDisconnect.error.output.statusCode 
                : 0;
            const reason = lastDisconnect.error?.message || 'unknown';
            console.log(`[CONN] Conexão fechada. Motivo: ${reason}, Código: ${statusCode}`);
            
            if (statusCode !== DisconnectReason.loggedOut) {
                console.log('[CONN] Tentando reconectar em 10s...');
                setTimeout(() => connectToWhatsApp(), 10000);
            }
        } else if (connection === 'open') {
            console.log('✅ MeiBot conectado com sucesso!');
            console.log('Usuário:', sock.user);
        }
    });

    sock.ev.on('messages.upsert', async (m) => {
        const msg = m.messages[0];
        if (!msg.message) return;

        const remoteJid = msg.key.remoteJid;
        const fromMe = msg.key.fromMe;
        const myId = sock.user?.id?.split(':')[0];

        if (!remoteJid || !myId) {
            return;
        }

        // LOG DE ENTRADA (Apenas para depuração interna)
        console.log(`[RAW-MSG] From: ${remoteJid} | fromMe: ${fromMe}`);

        // --- GATEWAY DE GRUPOS E COMANDOS DE ROTA ---
        if (remoteJid.endsWith('@g.us')) {
            try {
                await routeClaim.handleIncomingMessage(sock, msg);
            } catch (err) {
                console.error('[ROUTE-CLAIM] Error:', err.message);
            }
            // INDEPENDENTE do resultado, se é grupo, o bot morre aqui.
            // Nunca deixa passar para o processamento de IA geral.
            return;
        }
        
        // --- TRAVA DE SEGURANÇA ESTRITA (SELF-ONLY) ---
        // Só processa se o remoteJid contiver o seu próprio ID.
        // Isso garante que se você mandar mensagem para outra pessoa, o bot não responda.
        const isSelfChat = remoteJid.includes(myId);
        
        // Só responde se for no chat comigo mesmo E se a mensagem veio de MIM (para evitar loops)
        if (!isSelfChat || !fromMe) {
            return;
        }

        console.log(`[MSG] Processando: ${remoteJid} | fromMe: ${fromMe}`);

        // --- TRAVA DE LOOP INTELIGENTE ---
        const text = msg.message.conversation || 
                     msg.message.extendedTextMessage?.text || 
                     msg.message.ephemeralMessage?.message?.extendedTextMessage?.text ||
                     msg.message.ephemeralMessage?.message?.conversation ||
                     "";

        // Se a mensagem for uma resposta do próprio bot, ignora
        const startsWithBotEmoji = /^[✅❌📊🚀⛽📈🎙️📋🏢]/.test(text);
        const isLongAnalysis = text.length > 400;
        const containsBotKeywords = text.includes('Análise estratégica') || text.includes('Visão do Analista') || text.includes('Saldo Líquido');

        if (startsWithBotEmoji || isLongAnalysis || containsBotKeywords) {
            return;
        }

        const from = remoteJid.split('@')[0];
        let payload = { from, type: 'text', content: '' };

        try {
            // Captura de conteúdo
            const messageContent = msg.message.conversation || 
                                 msg.message.extendedTextMessage?.text || 
                                 msg.message.imageMessage?.caption ||
                                 msg.message.videoMessage?.caption ||
                                 msg.message.ephemeralMessage?.message?.extendedTextMessage?.text ||
                                 msg.message.ephemeralMessage?.message?.conversation ||
                                 msg.message.ephemeralMessage?.message?.imageMessage?.caption ||
                                 msg.message.viewOnceMessageV2?.message?.imageMessage?.caption ||
                                 msg.message.viewOnceMessageV2?.message?.conversation ||
                                 "";

            if (messageContent) {
                payload.content = messageContent;
                payload.type = 'text';
            } 
            else if (msg.message.imageMessage || msg.message.ephemeralMessage?.message?.imageMessage || msg.message.viewOnceMessageV2?.message?.imageMessage) {
                const buffer = await downloadMediaMessage(msg, 'buffer', {});
                payload.content = buffer.toString('base64');
                payload.type = 'image';
            }
            else if (msg.message.audioMessage) {
                const buffer = await downloadMediaMessage(msg, 'buffer', {});
                payload.content = buffer.toString('base64');
                payload.type = 'audio';
            }

            if (payload.content) {
                console.log(`[PROCESS] Enviando para o backend: "${payload.content.substring(0, 20)}..."`);
                const reply = await sendToBackend(payload);
                
                if (reply) {
                    // SILÊNCIO TOTAL em erros de cota ou erros internos
                    if (reply.includes('Quota exceeded') || reply.includes('429') || reply.includes('erro interno')) {
                        console.log('[WARN] Erro detectado (Cota ou Interno). Bot ficará silencioso conforme configurado.');
                        return;
                    }
                    await sock.sendMessage(remoteJid, { text: reply });
                }
            }
        } catch (err) {
            console.error('Erro no processamento:', err);
        }
    });

    sock.ev.on('messages.reaction', async (reactions) => {
        for (const reaction of reactions) {
            try {
                const handled = await routeClaim.handleReaction(sock, reaction);
                if (handled) return;
            } catch (err) {
                console.error('[ROUTE-CLAIM] Reaction error:', err.message);
            }
        }
    });
}

module.exports = connectToWhatsApp;
