const state = {
    active: false,
    groups: new Map(),
    groupCache: new Map()
};

function getGroupState(groupJid) {
    if (!state.groups.has(groupJid)) {
        state.groups.set(groupJid, {
            locked: false,
            lastClaimId: null,
            lastClaimSignature: null,
            lastClaimAt: 0,
            inFlight: false,
            processedMessageIds: new Set(),
            candidates: [],
            index: 0,
            recentClaims: new Map()
        });
    }

    return state.groups.get(groupJid);
}

module.exports = { state, getGroupState };
