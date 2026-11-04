// Menu comune di tutte le pagine (spec 001, FR-023).
// Le voci arrivano da /api/menu (definite in monitoraggio/web.py): qui solo il disegno.
(function () {
  const STILE = `
    .mm-barra { position: sticky; top: 0; z-index: 1000; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px;
      padding: 6px 14px; background: #1f3a5f; color: #fff; font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif;
      box-shadow: 0 1px 3px rgba(0,0,0,.25); }
    .mm-barra a { color: inherit; text-decoration: none; }
    .mm-titolo { font-weight: 700; margin-right: 10px; white-space: nowrap; }
    .mm-gruppo { position: relative; }
    .mm-gruppo > button { font: inherit; color: inherit; background: transparent; border: 1px solid transparent; border-radius: 5px;
      padding: 4px 10px; cursor: pointer; }
    .mm-gruppo > button:hover, .mm-gruppo.mm-aperto > button { background: rgba(255,255,255,.14); }
    .mm-gruppo.mm-corrente > button { border-color: rgba(255,255,255,.5); }
    .mm-voci { display: none; position: absolute; top: 100%; left: 0; min-width: 220px; margin-top: 4px; padding: 4px 0;
      background: #fff; color: #1d2330; border: 1px solid #d5dbe4; border-radius: 6px; box-shadow: 0 6px 18px rgba(0,0,0,.18); }
    .mm-gruppo.mm-aperto .mm-voci { display: block; }
    .mm-voci a, .mm-voci span { display: block; padding: 6px 14px; white-space: nowrap; color: #1d2330; }
    .mm-voci a:hover { background: #eef2f8; }
    .mm-voci a.mm-attiva { font-weight: 700; background: #e3ebf7; }
    .mm-voci span.mm-no { color: #8a93a3; cursor: default; }
    .mm-voci span.mm-no small { margin-left: 6px; }
    .mm-stato { margin-left: auto; font-size: 12px; opacity: .9; white-space: nowrap; }
    .mm-stato a { text-decoration: underline; }
    .mm-utente { margin-left: 12px; font-size: 12px; white-space: nowrap; }
    a.mm-utente, .mm-utente a { text-decoration: underline; }
    @media (prefers-color-scheme: dark) {
      .mm-voci { background: #1c2027; color: #e6e9ef; border-color: #2e343e; }
      .mm-voci a, .mm-voci span { color: #e6e9ef; }
      .mm-voci a:hover { background: #262c36; } .mm-voci a.mm-attiva { background: #2b3546; }
      .mm-voci span.mm-no { color: #7d8696; }
    }`;

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const percorso = location.pathname.replace(/\/$/, "") || "/";
  const attiva = (url) => url === percorso || (url === "/index.html" && percorso === "/");

  function disegna(gruppi, info) {
    const barra = document.createElement("div");
    barra.className = "mm-barra";
    barra.setAttribute("role", "navigation");
    barra.innerHTML = `<a class="mm-titolo" href="/monitoraggio">Ufficio reclutamento</a>` +
      gruppi.map(g => {
        const corrente = g.voci.some(v => attiva(v.url));
        return `<div class="mm-gruppo${corrente ? " mm-corrente" : ""}"><button type="button" aria-expanded="false">${esc(g.gruppo)} ▾</button>
          <div class="mm-voci">${g.voci.map(v => v.disponibile
            ? `<a href="${esc(v.url)}"${attiva(v.url) ? ' class="mm-attiva" aria-current="page"' : ""}>${esc(v.titolo)}</a>`
            : `<span class="mm-no" title="Non disponibile in questo ambiente">${esc(v.titolo)}<small>non disponibile</small></span>`).join("")}</div></div>`;
      }).join("") + `<span class="mm-stato" id="mm-stato"></span><span class="mm-utente" id="mm-sol"></span>` +
      (info.logout && info.utente ? `<span class="mm-utente">${esc(info.utente)} · <a href="${esc(info.logout)}">Esci</a></span>`
        : info.login ? `<a class="mm-utente" href="${esc(info.login)}">Accedi con SSO</a>` : "");
    document.body.prepend(barra);

    barra.querySelectorAll(".mm-gruppo > button").forEach(b => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const g = b.parentElement, aperto = !g.classList.contains("mm-aperto");
      barra.querySelectorAll(".mm-gruppo").forEach(x => { x.classList.remove("mm-aperto"); x.firstElementChild.setAttribute("aria-expanded", "false"); });
      if (aperto) { g.classList.add("mm-aperto"); b.setAttribute("aria-expanded", "true"); }
    }));
    document.addEventListener("click", () => barra.querySelectorAll(".mm-gruppo").forEach(x => x.classList.remove("mm-aperto")));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") barra.querySelectorAll(".mm-gruppo").forEach(x => x.classList.remove("mm-aperto")); });
  }

  async function aggiornaStato() {
    const el = document.getElementById("mm-stato");
    if (!el) return;
    try {
      const r = await fetch("/api/raccolta/stato", { cache: "no-store" });
      if (!r.ok) return;
      const { fonti } = await r.json();
      const nomi = { urp: "URP", sol: "SOL" };
      const inCorso = Object.keys(fonti).filter(f => fonti[f].in_corso).map(f => nomi[f]);
      const ora = (iso) => iso ? new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }) : "mai";
      el.innerHTML = inCorso.length
        ? `⏳ Raccolta in corso: ${inCorso.join(", ")}`
        : Object.keys(fonti).map(f => {
            const u = fonti[f].ultima, ok = u && u.esito !== "fallita";
            return `${nomi[f]} ${ok ? "" : "⚠ "}${ora(fonti[f].ultima_riuscita && fonti[f].ultima_riuscita.fine)}`;
          }).join(" · ") + ` · <a href="/monitoraggio">dettagli</a>`;
      if (inCorso.length) setTimeout(aggiornaStato, 15000);
    } catch (e) { /* lo stato è un'informazione in più: il menu funziona anche senza */ }
  }

  // Collegamento a Selezioni Online (solo prova locale): l'app apre una finestra di login
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
        el.innerHTML = `<a href="${esc(s.login_url || "#")}" id="mm-sol-accedi">Collega Selezioni Online</a>${s.errore ? ` <span title="${esc(s.errore)}">⚠</span>` : ""}`;
        if (!s.login_url) document.getElementById("mm-sol-accedi").onclick = async (e) => { e.preventDefault(); await fetch("/api/sol/accedi", { method: "POST" }); aggiornaSol(); };
      }
      if (!s.in_corso) document.dispatchEvent(new CustomEvent("sol-sessione", { detail: s }));
    } catch (e) { /* facoltativo */ }
  }

  async function avvia() {
    const stile = document.createElement("style");
    stile.textContent = STILE;
    document.head.appendChild(stile);
    try {
      const r = await fetch("/api/menu", { cache: "no-store" });
      if (!r.ok) return;
      const info = await r.json();
      disegna(info.gruppi, info);
      aggiornaStato();
      aggiornaSol();
    } catch (e) { /* senza API il menu non si mostra, la pagina resta usabile */ }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia);
  else avvia();
})();
