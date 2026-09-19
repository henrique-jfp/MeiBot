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

function hasAnyAlias(value, aliases) {
    const normalized = normalizeText(value);
    return aliases.some(alias => {
        const target = normalizeText(alias);
        if (!target) return false;
        if (target.length <= 3) {
            return new RegExp(`\\b${target}\\b`).test(normalized);
        }
        return normalized.includes(target);
    });
}

function isAllowedModal(modal) {
    const normalized = normalizeText(modal);
    if (!normalized) return false;
    if (normalized.includes('moto') || normalized.includes('fiorino') || normalized.includes('volumoso')) {
        return false;
    }
    return normalized.includes('mista') || normalized.includes('passeio') || normalized.includes('carro passeio');
}

function parseNumber(value) {
    const parsed = parseInt(String(value ?? '').replace(/[^\d-]/g, ''), 10);
    return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Atribui um Tier para a rota.
 * Tier 1: Urca
 * Tier 2: Tabajara / Tabajaras
 * Tier 3: Copacabana, Copa, Copacabana 1, Copacabana 2
 * Tier 4: Ipanema
 * Tier 5: Botafogo 2, Botafogo 1
 */
function getTierInfo(route) {
    // Quando presente, a classificação calculada pelo backend é a fonte de
    // verdade: ela também considera os bairros da dissecação da rota.
    if (Number.isInteger(route.tier) && route.tier >= 1 && route.tier <= 5) {
        return { tier: route.tier };
    }

    const principal = normalizeText(route.bairro);
    const config = ROUTES_CONFIG.tierConfig;

    if (hasAnyAlias(principal, config.tier1)) return { tier: 1 };
    if (hasAnyAlias(principal, config.tier2)) return { tier: 2 };
    if (hasAnyAlias(principal, config.tier3)) return { tier: 3 };
    if (hasAnyAlias(principal, config.tier4)) return { tier: 4 };
    if (hasAnyAlias(principal, config.tier5)) return { tier: 5 };

    return { tier: 0 };
}

function buildCandidates(routes) {
    const blocked = new Set((ROUTES_CONFIG.blockedGaiolas || []).map(normalizeGaiola));
    const candidates = [];

    for (const route of routes || []) {
        const gaiola = normalizeGaiola(route.gaiola);
        if (!gaiola || blocked.has(gaiola)) continue;

        const tierInfo = getTierInfo(route);
        if (tierInfo.tier === 0) continue;

        const modal = normalizeText(route.modal || '');
        if (!isAllowedModal(modal)) continue;

        const pacotesTotal = parseNumber(route.pacotes_total) ?? 0;
        let litragem = null;
        if (route.litragem !== undefined && route.litragem !== null) {
            litragem = parseFloat(route.litragem);
            if (isNaN(litragem)) litragem = null;
        }

        candidates.push({
            gaiola,
            bairro: route.bairro,
            pacotes_total: pacotesTotal,
            litragem: litragem,
            is_passeio: modal.includes('passeio'),
            tier: tierInfo.tier,
            raw: route
        });
    }

    return candidates;
}

function pickCandidate(candidates) {
    const sorted = candidates.sort((a, b) => {
        // 1. Prioridade por bairro (1 > 2 > 3 > 4 > 5)
        if (a.tier !== b.tier) return a.tier - b.tier;

        // 2. Litragem: menor primeiro quando informada
        if (a.litragem !== null || b.litragem !== null) {
            const litA = a.litragem !== null ? a.litragem : Infinity;
            const litB = b.litragem !== null ? b.litragem : Infinity;
            if (litA !== litB) return litA - litB;
        }

        // 3. Menos pacotes quando a litragem não desempatar
        if (a.pacotes_total !== b.pacotes_total) {
            return a.pacotes_total - b.pacotes_total;
        }

        // 4. Passeio vence apenas no empate completo
        if (a.is_passeio !== b.is_passeio) return a.is_passeio ? -1 : 1;
        return 0;
    });

    return { selected: sorted[0], ordered: sorted };
}

module.exports = { buildCandidates, pickCandidate, normalizeText };
