const connectToWhatsApp = require('./whatsapp');

console.log('--- MeiBot WhatsApp Starter ---');

connectToWhatsApp().catch(err => {
    console.error('Failed to start WhatsApp Bot:', err);
});
