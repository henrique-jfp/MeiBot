require('dotenv').config();

const ROUTES_CONFIG = {
    testGroupName: 'SPX Motorista',
    prodGroupNames: [],
    timezone: 'America/Sao_Paulo',
    schedule: {
        enabledInProd: true,
        startMinutes: 23 * 60,
        endMinutes: 4 * 60 + 30,
        weekdaysOnly: true
    },
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
