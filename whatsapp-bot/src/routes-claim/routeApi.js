const axios = require('axios');
require('dotenv').config();

const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000/webhook';

const api = axios.create({
    baseURL: backendUrl.replace('/webhook', ''),
    timeout: 45000,
});

async function parseRouteSheet(payload) {
    try {
        const response = await api.post('/routes-claim/parse', payload);
        return response.data;
    } catch (error) {
        console.error('Route parser error:', error.message);
        return { error: 'route_parser_failed' };
    }
}

module.exports = { parseRouteSheet };
