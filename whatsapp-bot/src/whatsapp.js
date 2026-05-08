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
            
            if (statusCode !== DisconnectReason.loggedOut) {
                setTimeout(() => connectToWhatsApp(), 10000);
            }
        } else if (connection === 'open') {
            console.log('✅ MeiBot conectado com sucesso!');
        }
    });

    sock.ev.on('messages.upsert', async (m) => {
        const msg = m.messages[0];
        if (!msg.message) return;

        const remoteJid = msg.key.remoteJid;
        const fromMe = msg.key.fromMe;
        const myId = sock.user.id.split(':')[0];
        
        // --- TRAVA DE SEGURANÇA (SELF-ONLY) ---
        // O remoteJid na conversa consigo mesmo geralmente é o seu próprio número @s.whatsapp.net
        const isMe = remoteJid.includes(myId);

        if (!isMe) {
            console.log(`[IGNORE] Mensagem de ${remoteJid} ignorada: não é a sua conversa pessoal.`);
            return;
        }

        // Se a mensagem foi enviada POR VOCÊ (no celular), processamos.
        // Se a mensagem foi enviada PELO BOT (via código), ignoramos para evitar loop.
        // O Baileys costuma marcar mensagens enviadas pelo próprio socket como fromMe: true.
        // Mas mensagens que você digita no celular também podem vir como fromMe: true na conversa consigo mesmo.
        
        // Vamos logar para entender o comportamento no seu servidor:
        console.log(`[MSG] Recebida de ${remoteJid} | fromMe: ${fromMe}`);

        // Se for uma mensagem que o BOT enviou (fromMe: true), ignore para evitar loop.
        // Identificamos mensagens do bot pelos emojis iniciais ou prefixos comuns.
        if (fromMe) {
            const text = msg.message.conversation || msg.message.extendedTextMessage?.text || "";
            
            // Trava 1: Emojis de resposta curta
            const startsWithBotEmoji = /^[✅❌📊🚀⛽📈🎙️📋🏢]/.test(text);
            
            // Trava 2: Mensagens longas do Analista ou dicas (você não digitaria comandos tão longos)
            const isLongAnalysis = text.length > 300;
            const containsBotKeywords = text.includes('Análise estratégica') || text.includes('projeto pessoal') || text.includes('Visão do Analista');

            if (startsWithBotEmoji || isLongAnalysis || containsBotKeywords) {
                // console.log(`[LOOP-PREVENT] Ignorando resposta/análise do próprio bot.`);
                return;
            }
        }

        // Se você quer que o bot responda quando você digita algo para si mesmo:
        // Na conversa consigo mesmo, as mensagens que VOCÊ envia chegam com fromMe: true.
        // Então NÃO podemos simplesmente ignorar fromMe: true.

        const from = remoteJid.split('@')[0];
        let payload = { from, type: 'text', content: '' };

        try {
            if (msg.message.conversation || msg.message.extendedTextMessage) {
                payload.content = msg.message.conversation || msg.message.extendedTextMessage.text;
                payload.type = 'text';
            } 
            else if (msg.message.imageMessage) {
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
                    await sock.sendMessage(remoteJid, { text: reply });
                }
            }
        } catch (err) {
            console.error('Erro no processamento:', err);
        }
    });
}

module.exports = connectToWhatsApp;
