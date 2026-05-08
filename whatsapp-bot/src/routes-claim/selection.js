function normalizeText(value) {
    if (!value) return '';
    return value.toString().toLowerCase().trim().replace(/\s+/g, ' ');
}

function buildCandidates(routes) {
    const candidates = [];
    for (const route of routes || []) {
        const bairro = normalizeText(route.bairro);
        const dissecacao = route.dissecacao || {};
        let hasRocinha = bairro.includes('rocinha');
        let rocinhaCount = null;

        for (const [key, val] of Object.entries(dissecacao)) {
            if (normalizeText(key).includes('rocinha')) {
                const parsed = parseInt(val, 10);
                rocinhaCount = Number.isNaN(parsed) ? null : parsed;
                hasRocinha = true;
                break;
            }
        }

        if (!hasRocinha) continue;

        const totalParsed = parseInt(route.pacotes_total, 10);
        const pacotesTotal = Number.isNaN(totalParsed) ? 0 : totalParsed;

        candidates.push({
            gaiola: route.gaiola,
            bairro: route.bairro,
            pacotes_total: pacotesTotal,
            rocinha_pacotes: rocinhaCount,
            raw: route
        });
    }

    return candidates;
}

function pickCandidate(candidates) {
    const withDissecacao = candidates.filter(c => c.rocinha_pacotes !== null);
    if (withDissecacao.length > 0) {
        const sorted = withDissecacao.sort((a, b) => b.rocinha_pacotes - a.rocinha_pacotes);
        return { selected: sorted[0], ordered: sorted };
    }

    const sorted = candidates.sort((a, b) => a.pacotes_total - b.pacotes_total);
    return { selected: sorted[0], ordered: sorted };
}

module.exports = { buildCandidates, pickCandidate, normalizeText };
