const state = {
    active: true,
    locked: false,
    lastClaimId: null,
    lastClaimJid: null,
    candidates: [],
    index: 0,
    groupCache: new Map()
};

module.exports = { state };
