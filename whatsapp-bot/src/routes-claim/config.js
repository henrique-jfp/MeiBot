require('dotenv').config();

const ROUTES_CONFIG = {
    testGroupName: 'SPX Motorista',
    prodGroupNames: [],
    timezone: 'America/Sao_Paulo',
    schedule: {
        enabledInProd: true,
        startMinutes: 14 * 60 + 30,
        endMinutes: 16 * 60,
        weekdaysOnly: false
    },
    minConfidence: 0.75,
    targetNeighborhoodAliases: ['rocinha', 'roc'],
    preferredGaiolas: [],
    blockedGaiolas: [],
    authorizedSenders: [],
    confirmTokens: ['valeu', 'confirmado', 'ok', 'fechado'],
    confirmEmojis: ['✅', '✔️', '👍', '💚'],
    denyEmojis: ['❌', '✖️', '✕', 'X'],
    claimTextPrefix: 'Henrique de Jesus Freitas Pereira 2554974',
    allowedMimeTypes: [
        'image/jpeg',
        'image/png',
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel'
    ]
};

module.exports = { ROUTES_CONFIG };
