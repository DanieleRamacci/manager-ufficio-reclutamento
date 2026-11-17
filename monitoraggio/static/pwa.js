// App installabile (spec 009): collega manifest e icone alla pagina e registra il service worker.
// Incluso da menu.js e dalle pagine senza menu (accesso, area referenti).
(function () {
  const testa = document.head;
  const aggiungi = (tag, attributi) => {
    if (document.querySelector(`${tag}[${Object.keys(attributi)[0]}="${Object.values(attributi)[0]}"]`)) return;
    const el = document.createElement(tag);
    Object.entries(attributi).forEach(([k, v]) => el.setAttribute(k, v));
    testa.appendChild(el);
  };
  aggiungi("link", { rel: "manifest", href: "/manifest.webmanifest" });
  aggiungi("meta", { name: "theme-color", content: "#1f3a5f" });
  aggiungi("link", { rel: "apple-touch-icon", href: "/icona-apple.png" });
  aggiungi("link", { rel: "icon", href: "/icona-192.png", type: "image/png" });
  aggiungi("meta", { name: "apple-mobile-web-app-title", content: "Monitoraggio" });
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  }
})();
