const { downloadMediaMessage } = require('@whiskeysockets/baileys');
const { ROUTES_CONFIG } = require('./config');
const { parseRouteSheet } = require('./routeApi');
const { buildCandidates, pickCandidate, normalizeText } = require('./selection');
const { state } = require('./state');

function getLocalTime() {
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: ROUTES_CONFIG.timezone,
        hour12: false,
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit'
    }).formatToParts(new Date());

    const map = Object.fromEntries(parts.map(p => [p.type, p.value]));
    return {
        weekday: map.weekday,
        hour: parseInt(map.hour, 10),
        minute: parseInt(map.minute, 10)
    };
}

function isWithinSchedule() {
    const { weekday, hour, minute } = getLocalTime();
    const minutesNow = hour * 60 + minute;
    const { startMinutes, endMinutes, weekdaysOnly } = ROUTES_CONFIG.schedule;

    if (weekdaysOnly) {
        const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
        const isWeekday = weekdays.includes(weekday);
        const isSaturdayEarly = weekday === 'Sat' && minutesNow <= endMinutes;
        if (!isWeekday && !isSaturdayEarly) {
            return false;
        }
    }

    if (startMinutes <= endMinutes) {
        return minutesNow >= startMinutes && minutesNow <= endMinutes;
    }

    return minutesNow >= startMinutes || minutesNow <= endMinutes;
}

async function getGroupName(sock, jid) {
    if (state.groupCache.has(jid)) {
        return state.groupCache.get(jid);
    }

    try {
        const meta = await sock.groupMetadata(jid);
        if (meta && meta.subject) {
            state.groupCache.set(jid, meta.subject);
            return meta.subject;
        }
    } catch (error) {
        console.log('[ROUTE-CLAIM] Failed to fetch group metadata:', error.message);
    }

    return null;
}

function isTestGroup(name) {
    return normalizeText(name) === normalizeText(ROUTES_CONFIG.testGroupName);
}

function isProdGroup(name) {
    return ROUTES_CONFIG.prodGroupNames
        .map(n => normalizeText(n))
        .includes(normalizeText(name));
}

async function handleCommand(msg, myJid) {
    const text = msg.message?.conversation || msg.message?.extendedTextMessage?.text || '';
    if (!text) return false;

    const command = normalizeText(text);
    if (command === 'reativar rotas') {
        state.locked = false;
        state.candidates = [];
        state.index = 0;
        state.lastClaimId = null;
        state.lastClaimJid = null;
        return true;
    }

    if (command === 'desativar rotas') {
        state.active = false;
        return true;
    }

    if (command === 'ativar rotas') {
        state.active = true;
        return true;
    }

    return false;
}

function isConfirmEmoji(emoji) {
    return ROUTES_CONFIG.confirmEmojis.includes(emoji);
}

function isDenyEmoji(emoji) {
    return ROUTES_CONFIG.denyEmojis.includes(emoji);
}

function hasConfirmToken(text) {
    const normalized = normalizeText(text);
    return ROUTES_CONFIG.confirmTokens.some(token => normalized.includes(token));
}

async function sendClaimMessage(sock, groupJid, candidate) {
    const claimText = `${ROUTES_CONFIG.claimTextPrefix} ${candidate.gaiola}`;
    const result = await sock.sendMessage(groupJid, { text: claimText });
    state.lastClaimId = result?.key?.id || null;
    state.lastClaimJid = groupJid;
    return result;
}

function shouldHandleGroup(name, isTest) {
    if (isTest) return true;
    return isProdGroup(name);
}

async function handleRouteImage(sock, msg, groupName, isTest) {
    if (!state.active || state.locked) return true;
    if (!isTest && ROUTES_CONFIG.schedule.enabledInProd && !isWithinSchedule()) {
        return true;
    }

    const message = msg.message;
    let mimeType = null;
    let buffer = null;

    if (message.imageMessage) {
        mimeType = message.imageMessage.mimetype || 'image/jpeg';
        buffer = await downloadMediaMessage(msg, 'buffer', {});
    } else if (message.documentMessage) {
        mimeType = message.documentMessage.mimetype || '';
        buffer = await downloadMediaMessage(msg, 'buffer', {});
    }

    if (!buffer || !mimeType || !ROUTES_CONFIG.allowedMimeTypes.includes(mimeType)) {
        return true;
    }

    const payload = {
        mime_type: mimeType,
        content_base64: buffer.toString('base64')
    };

    const parsed = await parseRouteSheet(payload);
    if (parsed.error || !parsed.routes || parsed.routes.length === 0) {
        console.log('[ROUTE-CLAIM] No routes parsed.');
        return true;
    }

    const candidates = buildCandidates(parsed.routes);
    if (candidates.length === 0) {
        console.log('[ROUTE-CLAIM] No Rocinha routes found.');
        return true;
    }

    const picked = pickCandidate(candidates);
    state.candidates = picked.ordered;
    state.index = 0;
    await sendClaimMessage(sock, msg.key.remoteJid, picked.selected);
    return true;
}

async function handleReaction(sock, reaction) {
    if (!state.lastClaimId || !state.lastClaimJid) return false;

    const messageKey = reaction.key;
    if (!messageKey || messageKey.id !== state.lastClaimId) return false;

    const emoji = reaction.reaction?.text || reaction.reaction || '';
    if (isConfirmEmoji(emoji)) {
        const myId = sock.user?.id?.split(':')[0];
        if (myId) {
            await sock.sendMessage(`${myId}@s.whatsapp.net`, {
                text: `✅ Rota confirmada: ${state.candidates[state.index]?.gaiola || 'desconhecida'}`
            });
        }
        state.locked = true;
        return true;
    }

    if (isDenyEmoji(emoji)) {
        state.index += 1;
        if (state.index < state.candidates.length) {
            await sendClaimMessage(sock, state.lastClaimJid, state.candidates[state.index]);
        } else {
            state.candidates = [];
        }
        return true;
    }

    return false;
}

async function handleTextReply(sock, msg) {
    if (!state.lastClaimId || !state.lastClaimJid) return false;

    const context = msg.message?.extendedTextMessage?.contextInfo;
    if (!context || context.stanzaId !== state.lastClaimId) return false;

    const text = msg.message?.extendedTextMessage?.text || '';
    if (!text) return false;

    if (hasConfirmToken(text)) {
        const myId = sock.user?.id?.split(':')[0];
        if (myId) {
            await sock.sendMessage(`${myId}@s.whatsapp.net`, {
                text: `✅ Rota confirmada: ${state.candidates[state.index]?.gaiola || 'desconhecida'}`
            });
        }
        state.locked = true;
        return true;
    }

    return false;
}

async function handleIncomingMessage(sock, msg) {
    const remoteJid = msg.key.remoteJid;
    const isGroup = remoteJid.endsWith('@g.us');
    const myId = sock.user?.id?.split(':')[0];

    if (!isGroup && myId) {
        const myJid = `${myId}@s.whatsapp.net`;
        if (remoteJid === myJid) {
            const handled = await handleCommand(msg, myJid);
            if (handled) return true;
        }
        return false;
    }

    if (!isGroup) return false;

    const groupName = await getGroupName(sock, remoteJid);
    if (!groupName) return false;

    const isTest = isTestGroup(groupName);
    if (!shouldHandleGroup(groupName, isTest)) return false;

    const textHandled = await handleTextReply(sock, msg);
    if (textHandled) return true;

    return handleRouteImage(sock, msg, groupName, isTest);
}

module.exports = {
    handleIncomingMessage,
    handleReaction,
    handleTextReply
};
