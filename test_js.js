const data = {
    history: [
        { id: '11maio', periodo_tipo: 'semanal', created_at: '2026-05-15', metrics: { period_start: '2026-05-11' } },
        { id: '18maio', periodo_tipo: 'semanal', created_at: '2026-05-10', metrics: { period_start: '2026-05-18' } },
        { id: '04maio', periodo_tipo: 'semanal', created_at: '2026-05-10', metrics: { period_start: '2026-05-04' } }
    ]
};

data.history.sort((a, b) => {
    const getRefDate = (h) => h.metrics && h.metrics.period_start ? h.metrics.period_start : h.created_at;
    return getRefDate(b).localeCompare(getRefDate(a));
});

let weekCounters = {};
[...data.history].reverse().forEach(h => {
    if (h.periodo_tipo === 'semanal') {
        let dateStr = h.metrics && h.metrics.period_start ? h.metrics.period_start : h.created_at;
        if (dateStr && dateStr.length === 10) dateStr += 'T12:00:00';
        const d = new Date(dateStr);
        if (!Number.isNaN(d.getTime())) {
            const monthKey = d.getFullYear() + '-' + d.getMonth();
            if (!weekCounters[monthKey]) weekCounters[monthKey] = 0;
            weekCounters[monthKey]++;
            h._week_num = weekCounters[monthKey];
        }
    }
});

data.history.forEach((h, i) => {
    let cti = h._week_num;
    console.log(`h.id=${h.id}, cti=${cti}, period_start=${h.metrics.period_start}`);
});
