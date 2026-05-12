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

// Inicia o monitor de horários para captura de rotas
routeClaim.startScheduleMonitor();

// Cache para evitar processamento de mensagens duplicadas (loops e LID/JID duplication)
const processedMessages = new Set();
const CACHE_LIMIT = 100;

// Trava absoluta de tempo de Boot. Rejeita QUALQUER MENSAGEM nos primeiros 15s de vida do Bot.
let BOOT_TIME = Date.now();
const BOOT_LOCK_WINDOW_MS = 15000;

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
            BOOT_TIME = Date.now(); // Reseta a trava no momento exato em que a conexão é estabelecida
        }
    });

    // Cache de textos para evitar loops de conteúdo idêntico
    const processedTexts = new Set();
    const TEXT_CACHE_LIMIT = 50;

    sock.ev.on('messages.upsert', async (m) => {
        // --- TRAVA ABSOLUTA DE BOOT ---
        // Se o bot acabou de ligar (menos de 15 segundos atrás), IGNORA COMPLETAMENTE.
        // Isso mata pela raiz qualquer tentativa do Baileys de cuspir mensagens pendentes ou offline.
        if (Date.now() - BOOT_TIME < BOOT_LOCK_WINDOW_MS) {
            return;
        }

        // --- FILTRO DE MENSAGENS AO VIVO ---
        // 'notify' significa que é uma mensagem nova chegando. 
        // 'append' significa que o Baileys está carregando o histórico do banco local ao reiniciar.
        if (m.type !== 'notify') {
            return;
        }

        const msg = m.messages[0];
        if (!msg.message) return;

        const remoteJid = msg.key.remoteJid;
        const fromMe = msg.key.fromMe;
        const myId = sock.user?.id?.split(':')[0];
        const myLid = sock.user?.lid?.split(':')[0];

        console.log(`[DEBUG-UPSERT] Nova mensagem de ${remoteJid} | fromMe: ${fromMe} | myId: ${myId}`);

        if (!remoteJid || !myId) {
            console.log('[DEBUG-UPSERT] Cancelado: remoteJid ou myId ausentes.');
            return;
        }

        // --- PRIORIDADE 1: COMANDOS (Sempre processar, ignora filtros de tempo) ---
        try {
            const handledRouteControl = await routeClaim.handleIncomingMessage(sock, msg);
            if (handledRouteControl) {
                console.log(`[ROUTE-CLAIM] Comando ou imagem processada: ${remoteJid}`);
                return;
            }
        } catch (err) {
            console.error('[ROUTE-CLAIM] Error:', err.message);
        }

        // --- FILTRO DE MENSAGENS ANTIGAS (EVITA LOOPS DE HISTÓRICO) ---
        const messageTimestamp = Number(msg.messageTimestamp || 0);
        const now = Math.floor(Date.now() / 1000);
        if (messageTimestamp && (now - messageTimestamp) > 60) {
            console.log(`[DEBUG-UPSERT] Ignorado: Mensagem antiga (${now - messageTimestamp}s).`);
            return;
        }

        // --- GATEWAY DE GRUPOS ---
        if (remoteJid.endsWith('@g.us')) {
            console.log(`[DEBUG-UPSERT] Ignorado: Gateway de grupos barrou ${remoteJid}`);
            return;
        }
        
        // --- TRAVA DE SEGURANÇA ESTRITA (SOMENTE Chat Próprio) ---
        const isSelfChat = remoteJid.includes(myId) || (myLid && remoteJid.includes(myLid));
        console.log(`[DEBUG-UPSERT] isSelfChat: ${isSelfChat} | myId: ${myId} | myLid: ${myLid}`);

        if (!isSelfChat) {
            console.log(`[DEBUG-UPSERT] Ignorado: Não é SelfChat.`);
            return;
        }

        // --- EXTRAÇÃO DE TEXTO PARA DEDUPLICAÇÃO ---
        const text = msg.message.conversation || 
                     msg.message.extendedTextMessage?.text || 
                     msg.message.ephemeralMessage?.message?.extendedTextMessage?.text ||
                     msg.message.ephemeralMessage?.message?.conversation ||
                     "";

        // --- TRAVA DE DUPLICIDADE (ID e TEXTO) ---
        const messageId = msg.key.id;
        const textHash = text.trim().substring(0, 100);
        
        if (processedMessages.has(messageId)) {
            console.log(`[DEBUG-UPSERT] Ignorado: ID duplicado (${messageId}).`);
            return;
        }
        if (textHash && processedTexts.has(textHash)) {
            console.log(`[DEBUG-UPSERT] Ignorado: Texto duplicado.`);
            return;
        }
        
        processedMessages.add(messageId);
        if (textHash) processedTexts.add(textHash);

        if (processedMessages.size > CACHE_LIMIT) {
            const firstItem = processedMessages.values().next().value;
            processedMessages.delete(firstItem);
        }
        if (processedTexts.size > TEXT_CACHE_LIMIT) {
            const firstItem = processedTexts.values().next().value;
            processedTexts.delete(firstItem);
        }

        console.log(`[MSG] Iniciando processamento IA: ${remoteJid}`);

        // --- TRAVA DE LOOP (Detecção de respostas do Bot ou do Próprio Usuário) ---
        const startsWithBotEmoji = /^[✅❌⚠️📊🔄🚀⛽📈🎙️📋🏢╔┌]/.test(text.trim());
        const isBotMessage = text.includes('Análise estratégica') || 
                             text.includes('Visão do Analista') || 
                             text.includes('VISÃO DO ANALISTA') ||
                             text.includes('Saldo Líquido') || 
                             text.includes('SALDO LÍQUIDO') ||
                             text.includes('RESUMO SEMANAL') ||
                             text.includes('CONSOLIDADO DA OPERAÇÃO') ||
                             text.includes('Rota confirmada:') ||
                             text.includes('Sistema de rotas');

        if (startsWithBotEmoji || isBotMessage || text.length > 500) {
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
