// Barra superiore comune a tutte le pagine (specifiche grafiche, sezione 2). Le voci di "Altro" arrivano da /api/menu.
(function () {
  const STILE = `
    .mm-barra { position: sticky; top: 0; z-index: 1000; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 4px;
      padding: 7px 18px; background: #1f3a5f; color: #fff; font: 14px/1.4 "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif; }
    .mm-barra a { color: inherit; text-decoration: none; }
    .mm-titolo { font-weight: 700; margin-right: 14px; white-space: nowrap; }
    .mm-voce, .mm-gruppo > button { opacity: .78; padding: 5px 10px; border-radius: 6px; font: inherit; color: inherit; background: transparent; border: 0; cursor: pointer; min-height: 0; display: inline-flex; gap: 6px; align-items: center; }
    .mm-voce:hover, .mm-gruppo > button:hover { opacity: 1; background: rgba(255,255,255,.1); }
    .mm-voce.mm-attiva, .mm-gruppo.mm-corrente > button { opacity: 1; background: rgba(255,255,255,.16); }
    .mm-numero { background: #d6453a; color: #fff; border-radius: 999px; font-size: 11px; font-weight: 600; padding: 0 6px; }
    .mm-gruppo { position: relative; }
    .mm-voci { display: none; position: absolute; top: 100%; left: 0; min-width: 220px; margin-top: 4px; padding: 4px 0; background: #fff; color: #1b2230; border: 1px solid #e3e6eb; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.18); }
    .mm-gruppo.mm-aperto .mm-voci { display: block; }
    .mm-voci a { display: block; padding: 6px 14px; white-space: nowrap; color: #1b2230; }
    .mm-voci a:hover { background: #f3f4f6; }
    .mm-voci a.mm-attiva { font-weight: 600; background: #eef4fd; }
    .mm-destra { margin-left: auto; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 14px; font-size: 12px; }
    .mm-fonte { white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; }
    .mm-pallino { width: 7px; height: 7px; border-radius: 50%; background: #5fd08e; }
    .mm-pallino.spento { background: #e9a23b; }
    .mm-destra u, .mm-destra a { text-decoration: underline; }
    .sola-lettura .solo-admin { display: none !important; }`;

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const percorso = location.pathname.replace(/\/$/, "") || "/";
  const PRINCIPALI = [
    { titolo: "Stato complessivo", url: "/monitoraggio", esatta: true },
    { titolo: "Monitoraggi", url: "/monitoraggio/mensili", numero: true },
    { titolo: "Comunicazioni", url: "/monitoraggio/comunicazioni" },
    { titolo: "File segreteria", url: "/monitoraggio/segreteria" },
    { titolo: "Impostazioni", url: "/monitoraggio/impostazioni", soloAdmin: true },
  ];
  const attivaPrincipale = (v) => v.esatta ? percorso === v.url : percorso.startsWith(v.url);
  const quando = (iso) => iso ? new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(",", "") : "mai";

  function disegna(info) {
    const barra = document.createElement("div");
    barra.className = "mm-barra";
    barra.setAttribute("role", "navigation");
    const url = new Set(PRINCIPALI.map(v => v.url));
    const altre = info.gruppi.flatMap(g => g.voci).filter(v => v.disponibile && !url.has(v.url) && !v.url.startsWith("/monitoraggio/segreteria"));
    const corrente = altre.some(v => v.url === percorso);
    barra.innerHTML = `<a class="mm-titolo" href="/monitoraggio">Ufficio reclutamento</a>` +
      PRINCIPALI.filter(v => !v.soloAdmin || info.ruolo === "amministratore").map(v =>
        `<a class="mm-voce${attivaPrincipale(v) ? " mm-attiva" : ""}" href="${v.url}"${attivaPrincipale(v) ? ' aria-current="page"' : ""}>${v.titolo}${v.numero && info.da_comunicare ? ` <span class="mm-numero" title="Bandi ancora da comunicare nei monitoraggi in corso">${info.da_comunicare}</span>` : ""}</a>`).join("") +
      (altre.length ? `<div class="mm-gruppo${corrente ? " mm-corrente" : ""}"><button type="button" aria-expanded="false">Controlli URP ▾</button>
        <div class="mm-voci">${altre.map(v => `<a href="${esc(v.url)}"${v.url === percorso ? ' class="mm-attiva"' : ""}>${esc(v.titolo)}</a>`).join("")}</div></div>` : "") +
      `<span class="mm-destra"><span id="mm-stato"></span><span id="mm-sol"></span>${info.logout && info.utente
        ? `<span>${esc(info.utente)} · <a href="${esc(info.logout)}">Esci</a></span>` : info.login ? `<a href="${esc(info.login)}">Accedi</a>` : ""}</span>`;
    document.body.prepend(barra);
    const pulsante = barra.querySelector(".mm-gruppo > button");
    if (pulsante) {
      pulsante.addEventListener("click", (e) => { e.stopPropagation(); const a = pulsante.parentElement.classList.toggle("mm-aperto"); pulsante.setAttribute("aria-expanded", String(a)); });
      document.addEventListener("click", () => pulsante.parentElement.classList.remove("mm-aperto"));
      document.addEventListener("keydown", (e) => { if (e.key === "Escape") pulsante.parentElement.classList.remove("mm-aperto"); });
    }
    const fonti = [["sol", "Selezioni Online"], ["urp", "URP"], ["segreteria", "File segreteria"]];
    document.getElementById("mm-stato").innerHTML = fonti.map(([k, nome]) =>
      `<span class="mm-fonte" style="margin-right:12px"><i class="mm-pallino${info.fonti?.[k] ? "" : " spento"}"></i>${nome} ${quando(info.fonti?.[k])}</span>`).join("");
  }

  async function aggiornaSol() {
    const el = document.getElementById("mm-sol");
    if (!el) return;
    try {
      const r = await fetch("/api/sol/sessione", { cache: "no-store" });
      if (!r.ok) return;
      const s = await r.json();
      if (!s.disponibile) { el.innerHTML = ""; document.dispatchEvent(new CustomEvent("sol-sessione", { detail: s })); return; }
      const ora = (iso) => new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
      if (s.in_corso) {
        el.innerHTML = "⏳ Login Selezioni Online nella finestra di Chrome…";
        setTimeout(aggiornaSol, 3000);
      } else if (s.collegato) {
        el.innerHTML = `SOL collegato fino alle ${ora(s.scade_il)} · <a href="#" id="mm-sol-esci">Scollega</a>`;
        document.getElementById("mm-sol-esci").onclick = async (e) => { e.preventDefault(); await fetch("/api/sol/esci", { method: "POST" }); aggiornaSol(); document.dispatchEvent(new Event("sol-sessione")); };
      } else {
        el.innerHTML = `<a class="solo-admin" href="${esc(s.login_url || "#")}" id="mm-sol-accedi">Collega Selezioni Online</a>${s.errore ? ` <span title="${esc(s.errore)}">⚠</span>` : ""}`;
        if (!s.login_url) document.getElementById("mm-sol-accedi").onclick = async (e) => { e.preventDefault(); await fetch("/api/sol/accedi", { method: "POST" }); aggiornaSol(); };
      }
      if (!s.in_corso) document.dispatchEvent(new CustomEvent("sol-sessione", { detail: s }));
    } catch (e) { /* facoltativo */ }
  }

  async function avvia() {
    const stile = document.createElement("style");
    stile.textContent = STILE;
    document.head.appendChild(stile);
    if (!document.querySelector('link[href="/monitoraggio/app.css"]')) {
      const foglio = document.createElement("link");
      foglio.rel = "stylesheet";
      foglio.href = "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap";
      document.head.appendChild(foglio);
    }
    try {
      const r = await fetch("/api/menu", { cache: "no-store" });
      if (!r.ok) return;
      const info = await r.json();
      if (info.ruolo === "lettura") document.documentElement.classList.add("sola-lettura");
      disegna(info);
      if (info.vista_come) {
        const barra = document.createElement("div");
        barra.setAttribute("role", "status");
        barra.style.cssText = "background:#7a4b00;color:#fff;padding:10px 18px;font:600 14px system-ui,sans-serif;display:flex;gap:12px;align-items:center;flex-wrap:wrap";
        barra.innerHTML = `<span></span><button type="button" style="font:inherit;padding:4px 10px;cursor:pointer">Torna amministratore</button>`;
        barra.querySelector("span").textContent = `Anteprima: stai vedendo il sito come ${info.vista_come} (sola lettura). Le azioni non vengono eseguite.`;
        barra.querySelector("button").onclick = async () => { await fetch("/api/vista-come/esci", { method: "POST" }); location.href = "/monitoraggio/impostazioni#utenti"; };
        document.body.insertBefore(barra, document.body.firstChild);
      }
      if (info.avviso_dati) {
        const barra = document.createElement("div");
        barra.setAttribute("role", "alert");
        barra.style.cssText = "background:#b42318;color:#fff;padding:10px 18px;font:600 14px system-ui,sans-serif";
        barra.textContent = info.avviso_dati;
        document.body.insertBefore(barra, document.body.firstChild);
      }
      aggiornaSol();
    } catch (e) { /* senza API il menu non si mostra, la pagina resta usabile */ }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia);
  else avvia();
})();
