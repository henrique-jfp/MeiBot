const { downloadMediaMessage } = require('@whiskeysockets/baileys');
const { ROUTES_CONFIG } = require('./config');
const { parseRouteSheet } = require('./routeApi');
const { buildCandidates, pickCandidate, normalizeText } = require('./selection');
const { state, getGroupState } = require('./state');

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
        state.groups.clear();
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
    const groupState = getGroupState(groupJid);
    groupState.lastClaimId = result?.key?.id || null;
    return result;
}

function shouldHandleGroup(name, isTest) {
    if (isTest) return true;
    return isProdGroup(name);
}

function isAuthorizedSender(msg) {
    const authorized = ROUTES_CONFIG.authorizedSenders || [];
    if (authorized.length === 0) return true;

    const sender = msg.key.participant || msg.key.remoteJid || '';
    const normalizedSender = normalizeText(sender.split('@')[0]);
    return authorized.some(item => normalizedSender === normalizeText(item).split('@')[0]);
}

async function handleRouteImage(sock, msg, groupName, isTest) {
    const groupJid = msg.key.remoteJid;
    const groupState = getGroupState(groupJid);

    if (!state.active || groupState.locked) return true;
    if (groupState.lastClaimId) return true;
    if (!isAuthorizedSender(msg)) return true;
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
    if (
        parsed.error ||
        !parsed.routes ||
        parsed.routes.length === 0 ||
        (typeof parsed.confidence === 'number' && parsed.confidence < ROUTES_CONFIG.minConfidence)
    ) {
        console.log('[ROUTE-CLAIM] No confident routes parsed.');
        return true;
    }

    const candidates = buildCandidates(parsed.routes);
    if (candidates.length === 0) {
        console.log('[ROUTE-CLAIM] No Rocinha routes found.');
        return true;
    }

    const picked = pickCandidate(candidates);
    groupState.candidates = picked.ordered;
    groupState.index = 0;
    console.log(
        `[ROUTE-CLAIM] Claiming route gaiola=${picked.selected.gaiola} ` +
        `rocinha=${picked.selected.rocinha_pacotes ?? 'n/a'} total=${picked.selected.pacotes_total}`
    );
    await sendClaimMessage(sock, groupJid, picked.selected);
    return true;
}

function findGroupStateByClaim(messageKey) {
    const remoteJid = messageKey?.remoteJid;
    if (remoteJid && state.groups.has(remoteJid)) {
        const groupState = getGroupState(remoteJid);
        if (messageKey.id === groupState.lastClaimId) {
            return { groupJid: remoteJid, groupState };
        }
    }

    for (const [groupJid, groupState] of state.groups.entries()) {
        if (messageKey?.id === groupState.lastClaimId) {
            return { groupJid, groupState };
        }
    }

    return null;
}

async function handleReaction(sock, reaction) {
    const messageKey = reaction.key;
    const claim = findGroupStateByClaim(messageKey);
    if (!claim) return false;

    const { groupJid, groupState } = claim;

    const emoji = reaction.reaction?.text || reaction.reaction || '';
    if (isConfirmEmoji(emoji)) {
        groupState.locked = true;
        return true;
    }

    if (isDenyEmoji(emoji)) {
        groupState.index += 1;
        if (groupState.index < groupState.candidates.length) {
            await sendClaimMessage(sock, groupJid, groupState.candidates[groupState.index]);
        } else {
            groupState.candidates = [];
            groupState.lastClaimId = null;
        }
        return true;
    }

    return false;
}

async function handleTextReply(sock, msg) {
    const groupJid = msg.key.remoteJid;
    const groupState = getGroupState(groupJid);
    if (!groupState.lastClaimId) return false;

    const context = msg.message?.extendedTextMessage?.contextInfo;
    if (!context || context.stanzaId !== groupState.lastClaimId) return false;

    const text = msg.message?.extendedTextMessage?.text || '';
    if (!text) return false;

    if (hasConfirmToken(text)) {
        groupState.locked = true;
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
    handleTextReply,
    getGroupName
};
