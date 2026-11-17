// Service worker dell'app installabile (spec 009). Non salva niente sul dispositivo: nessuna cache di pagine
// o dati, perché il monitoraggio contiene dati personali. Serve solo a rendere l'app installabile e a mostrare
// un messaggio chiaro quando manca la rete.
const SENZA_RETE = `<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Serve la connessione</title><style>body{font-family:system-ui,sans-serif;background:#f3f4f6;color:#1b2230;margin:0;padding:48px 16px}
main{max-width:480px;margin:0 auto;background:#fff;border:1px solid #e3e6eb;border-radius:10px;padding:24px}
button{margin-top:12px;padding:9px 16px;border:0;border-radius:6px;background:#1f3a5f;color:#fff;font-size:1rem;cursor:pointer}</style></head>
<body><main><h1 style="font-size:1.3rem;margin-top:0">Serve la connessione</h1>
<p>Il monitoraggio funziona solo online: controlla la rete (o la VPN) e riprova.</p>
<button onclick="location.reload()">Riprova</button></main></body></html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (evento) => {
  // toglie eventuali cache lasciate da versioni precedenti, per sicurezza
  evento.waitUntil(caches.keys().then((nomi) => Promise.all(nomi.map((n) => caches.delete(n)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (evento) => {
  if (evento.request.mode !== "navigate") return;  // tutto il resto va in rete come sempre
  evento.respondWith(fetch(evento.request).catch(() => new Response(SENZA_RETE, {
    status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } })));
});
