const data = {
    history: [
        {
            id: '30b3435a',
            periodo_tipo: 'semanal',
            created_at: '2026-05-15T12:12:54.706456+00:00',
            metrics: { period_start: '2026-05-11' }
        },
        {
            id: '1e5a6af4',
            periodo_tipo: 'semanal',
            created_at: '2026-05-10T23:59:59+00:00',
            metrics: { period_start: '2026-05-18' }
        }
    ]
};

let weekCounters = {};
const weeklyAnalyses = data.history.filter(h => h.periodo_tipo === 'semanal').sort((a, b) => {
    const dateA = a.metrics && a.metrics.period_start ? a.metrics.period_start : a.created_at;
    const dateB = b.metrics && b.metrics.period_start ? b.metrics.period_start : b.created_at;
    return dateA.localeCompare(dateB);
});

weeklyAnalyses.forEach(h => {
    let dateStr = h.metrics && h.metrics.period_start ? h.metrics.period_start : h.created_at;
    if (dateStr && dateStr.length === 10) dateStr += 'T12:00:00';
    const d = new Date(dateStr);
    if (!Number.isNaN(d.getTime())) {
        const monthKey = d.getFullYear() + '-' + d.getMonth();
        if (!weekCounters[monthKey]) weekCounters[monthKey] = 0;
        weekCounters[monthKey]++;
        h._week_num = weekCounters[monthKey];
    }
});

data.history.forEach((h, i) => {
    let cti = '';
    if (h.periodo_tipo === 'semanal') {
        cti = h._week_num || '';
    } else {
        cti = data.history.filter((x, j) => x.periodo_tipo === h.periodo_tipo && j >= i).length;
    }
    console.log(`h.id=${h.id}, cti=${cti}, period_start=${h.metrics.period_start}`);
});
