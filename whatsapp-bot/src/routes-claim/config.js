require('dotenv').config();

const ROUTES_CONFIG = {
    testGroupName: 'Documentos',
    prodGroupNames: ['SPX Motorista'],
    // Identificador estável do grupo de produção; evita falhas quando o nome
    // do grupo recebe emoji, sufixo ou outra variação visual.
    prodGroupIds: ['120363413438458968@g.us'],
    minConfidence: 0.75,
    tierConfig: {
        tier1: ['urca'],
        tier2: ['tabajara', 'tabajaras'],
        tier3: ['copacabana', 'copa', 'copacabana 1', 'copacabana 2'],
        tier4: ['ipanema'],
        tier5: ['botafogo 2', 'botafogo 1']
    },
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
