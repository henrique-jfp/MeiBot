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

data.history.forEach((h, i) => {
    let cti = '';
    if (h.periodo_tipo === 'semanal') {
        let dateStr = h.metrics && h.metrics.period_start ? h.metrics.period_start : h.created_at;
        if (dateStr && dateStr.length === 10) dateStr += 'T12:00:00';
        const d = new Date(dateStr);
        if (!Number.isNaN(d.getTime())) {
            cti = Math.ceil(d.getDate() / 7);
        } else {
            cti = '?';
        }
    }
    console.log(`h.id=${h.id}, cti=${cti}, period_start=${h.metrics.period_start}`);
});
