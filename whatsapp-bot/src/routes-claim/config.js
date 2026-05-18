require('dotenv').config();

const ROUTES_CONFIG = {
    testGroupName: 'Documento',
    prodGroupNames: ['ROTAS E DISTRIBUIÇÃO ILHA - 2026', 'SPX Motorista'],
    timezone: 'America/Sao_Paulo',
    schedule: {
        enabledInProd: true,
        startMinutes: 23 * 60,
        endMinutes: 4 * 60 + 30,
        weekdaysOnly: true
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
