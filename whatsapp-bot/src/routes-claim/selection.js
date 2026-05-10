const { ROUTES_CONFIG } = require('./config');

function normalizeText(value) {
    if (!value) return '';
    return value.toString()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .trim()
        .replace(/\s+/g, ' ');
}

function normalizeGaiola(value) {
    return normalizeText(value).toUpperCase().replace(/\s+/g, '');
}

function includesTargetNeighborhood(value) {
    const normalized = normalizeText(value);
    return ROUTES_CONFIG.targetNeighborhoodAliases.some(alias => {
        const target = normalizeText(alias);
        if (!target) return false;
        if (target.length <= 3) {
            return new RegExp(`\\b${target}\\b`).test(normalized);
        }
        return normalized.includes(target);
    });
}

function parseNumber(value) {
    const parsed = parseInt(String(value ?? '').replace(/[^\d-]/g, ''), 10);
    return Number.isNaN(parsed) ? null : parsed;
}

function buildCandidates(routes) {
    const blocked = new Set((ROUTES_CONFIG.blockedGaiolas || []).map(normalizeGaiola));
    const candidates = [];

    for (const route of routes || []) {
        const gaiola = normalizeGaiola(route.gaiola);
        if (!gaiola || blocked.has(gaiola)) continue;

        const bairro = route.bairro || '';
        const dissecacao = route.dissecacao || {};
        let hasRocinha = includesTargetNeighborhood(bairro);
        let rocinhaCount = null;

        for (const [key, val] of Object.entries(dissecacao)) {
            if (includesTargetNeighborhood(key)) {
                const parsed = parseNumber(val);
                rocinhaCount = parsed;
                hasRocinha = true;
                break;
            }
        }

        if (!hasRocinha) continue;

        const pacotesTotal = parseNumber(route.pacotes_total) ?? 0;

        candidates.push({
            gaiola,
            bairro: route.bairro,
            pacotes_total: pacotesTotal,
            rocinha_pacotes: rocinhaCount,
            raw: route
        });
    }

    return candidates;
}

function pickCandidate(candidates) {
    const preferred = new Set((ROUTES_CONFIG.preferredGaiolas || []).map(normalizeGaiola));
    const rankPreference = candidate => preferred.has(normalizeGaiola(candidate.gaiola)) ? 1 : 0;
    const sortByPreferenceAndTotal = (a, b) => {
        const prefDiff = rankPreference(b) - rankPreference(a);
        if (prefDiff !== 0) return prefDiff;
        return a.pacotes_total - b.pacotes_total;
    };

    const withDissecacao = candidates.filter(c => c.rocinha_pacotes !== null);
    if (withDissecacao.length > 0) {
        const sorted = withDissecacao.sort((a, b) => {
            const prefDiff = rankPreference(b) - rankPreference(a);
            if (prefDiff !== 0) return prefDiff;
            const rocinhaDiff = b.rocinha_pacotes - a.rocinha_pacotes;
            if (rocinhaDiff !== 0) return rocinhaDiff;
            return a.pacotes_total - b.pacotes_total;
        });
        return { selected: sorted[0], ordered: sorted };
    }

    const sorted = candidates.sort(sortByPreferenceAndTotal);
    return { selected: sorted[0], ordered: sorted };
}

module.exports = { buildCandidates, pickCandidate, normalizeText, includesTargetNeighborhood };
