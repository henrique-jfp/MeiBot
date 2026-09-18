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
 * Atribui um Tier para a rota.
 * Tier 1: Urca
 * Tier 2: Tabajara / Tabajaras
 * Tier 3: Copacabana, Copa, Copacabana 1, Copacabana 2
 * Tier 4: Ipanema
 * Tier 5: Botafogo 2, Botafogo 1
 */
function getTierInfo(route) {
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
        if (modal) {
            if (modal.includes('moto') || modal.includes('fiorino') || modal.includes('volumoso')) {
                continue;
            }
            if (!modal.includes('mista') && !modal.includes('passeio')) {
                continue;
            }
        }

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
    const preferred = new Set((ROUTES_CONFIG.preferredGaiolas || []).map(normalizeGaiola));
    const rankPreference = candidate => preferred.has(normalizeGaiola(candidate.gaiola)) ? 1 : 0;

    const sorted = candidates.sort((a, b) => {
        // 1. Preferência manual de gaiola (Gaiolas VIP furam qualquer Tier)
        const prefDiff = rankPreference(b) - rankPreference(a);
        if (prefDiff !== 0) return prefDiff;

        // 2. Prioridade por Tier (1 > 2 > 3 > 4 > 5)
        if (a.tier !== b.tier) return a.tier - b.tier;

        // 3. Modal: Passeio tem preferência sobre Rota Mista no mesmo Tier
        if (a.is_passeio !== b.is_passeio) {
            return a.is_passeio ? -1 : 1;
        }

        // 4. Litragem (menor primeiro)
        if (a.litragem !== null || b.litragem !== null) {
            const litA = a.litragem !== null ? a.litragem : Infinity;
            const litB = b.litragem !== null ? b.litragem : Infinity;
            if (litA !== litB) return litA - litB;
        }

        // 5. Critério de Desempate Geral: Menos pacotes total (SPR)
        return a.pacotes_total - b.pacotes_total;
    });

    return { selected: sorted[0], ordered: sorted };
}

module.exports = { buildCandidates, pickCandidate, normalizeText };
