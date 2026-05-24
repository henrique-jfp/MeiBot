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

function parseNumber(value) {
    const parsed = parseInt(String(value ?? '').replace(/[^\d-]/g, ''), 10);
    return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Atribui um Tier e dados de prioridade para a rota.
 * Tier 1: Principal é Tabajaras
 * Tier 2: Principal é Copacabana E detalhe tem Tabajaras
 * Tier 3: Principal é Copacabana E detalhe NÃO tem Tabajaras
 * Tier 4: Principal é Botafogo/Ipanema
 */
function getTierInfo(route) {
    const principal = normalizeText(route.bairro);
    const dissecacao = route.dissecacao || {};
    const config = ROUTES_CONFIG.tierConfig;

    // Procura por Tabajaras na dissecação para regras de Tier 1 e 2
    let tabajaraCount = null;
    for (const [key, val] of Object.entries(dissecacao)) {
        if (hasAnyAlias(key, config.tier1_primary)) {
            tabajaraCount = parseNumber(val);
            break;
        }
    }

    // Tier 1: Bairro principal é Tabajaras
    if (hasAnyAlias(principal, config.tier1_primary)) {
        return { tier: 1, targetCount: tabajaraCount ?? 0 };
    }

    // Tier 2 e 3: Base Copacabana
    if (hasAnyAlias(principal, config.tier_base)) {
        if (tabajaraCount !== null) {
            return { tier: 2, targetCount: tabajaraCount };
        }
        return { tier: 3, targetCount: 0 };
    }

    // Tier 4: Fallback (Botafogo/Ipanema)
    if (hasAnyAlias(principal, config.tier4_fallback)) {
        return { tier: 4, targetCount: 0 };
    }

    return { tier: 0, targetCount: 0 };
}

function buildCandidates(routes) {
    const blocked = new Set((ROUTES_CONFIG.blockedGaiolas || []).map(normalizeGaiola));
    const candidates = [];

    for (const route of routes || []) {
        const gaiola = normalizeGaiola(route.gaiola);
        if (!gaiola || blocked.has(gaiola)) continue;

        const tierInfo = getTierInfo(route);
        if (tierInfo.tier === 0) continue;

        const pacotesTotal = parseNumber(route.pacotes_total) ?? 0;

        candidates.push({
            gaiola,
            bairro: route.bairro,
            pacotes_total: pacotesTotal,
            tier: tierInfo.tier,
            target_count: tierInfo.targetCount,
            raw: route
        });
    }

    return candidates;
}

function pickCandidate(candidates) {
    const preferred = new Set((ROUTES_CONFIG.preferredGaiolas || []).map(normalizeGaiola));
    const rankPreference = candidate => preferred.has(normalizeGaiola(candidate.gaiola)) ? 1 : 0;

    const sorted = candidates.sort((a, b) => {
        // 1. Preferência manual de gaiola (Gaiolas VIP furam qualquer Tier)
        const prefDiff = rankPreference(b) - rankPreference(a);
        if (prefDiff !== 0) return prefDiff;

        // 2. Prioridade por Tier (1 > 2 > 3 > 4)
        if (a.tier !== b.tier) return a.tier - b.tier;

        // 3. Regras específicas por Tier
        if (a.tier === 1) {
            // Tier 1: Menos Tabajaras na dissecação
            const tabajaraDiff = a.target_count - b.target_count;
            if (tabajaraDiff !== 0) return tabajaraDiff;
        }

        // 4. Critério Geral: Menos pacotes total (SPR)
        return a.pacotes_total - b.pacotes_total;
    });

    return { selected: sorted[0], ordered: sorted };
}

module.exports = { buildCandidates, pickCandidate, normalizeText };
