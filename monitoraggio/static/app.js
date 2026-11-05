// Funzioni comuni delle pagine (specifiche grafiche, sezione 2): celle fonte, RdP, candidati, finestre, toast.
window.App = (() => {
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ora = (iso) => iso ? new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }) : "";
  const dataIt = (d) => (d || "").slice(0, 10).split("-").reverse().join("/");
  const MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
  const TIPOLOGIE = { TI: "Tempo indeterminato", MOB: "Mobilità" };
  const NOMI_TIPOLOGIA = { tempo_indeterminato: "Tempo indeterminato", reclutamento_speciale: "Reclutamento speciale", categorie_protette: "Categorie protette", mobilita: "Mobilità", comando: "Comando" };
  const ATTI = { bando: "Bando", graduatoria: "Graduatoria", scorrimento: "Scorrimento", rettifica: "Rettifica" };

  async function chiama(url, opzioni) {
    const r = await fetch(url, { cache: "no-store", ...opzioni });
    const corpo = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(corpo.error || corpo.msg || `Errore ${r.status}`); e.corpo = corpo; e.status = r.status; throw e; }
    return corpo;
  }
  const json = (metodo, dati) => ({ method: metodo, headers: { "Content-Type": "application/json" }, body: JSON.stringify(dati ?? {}) });

  let timerToast;
  function toast(testo) {
    let el = $("toast");
    if (!el) { el = document.createElement("div"); el.id = "toast"; el.setAttribute("role", "status"); document.body.appendChild(el); }
    el.textContent = testo;
    el.hidden = false;
    clearTimeout(timerToast);
    timerToast = setTimeout(() => { el.hidden = true; }, 2500);
  }

  function apriFinestra(html) {
    chiudiFinestra();
    const o = document.createElement("div");
    o.className = "sovrapposta";
    o.id = "sovrapposta";
    o.innerHTML = `<div class="finestra" role="dialog" aria-modal="true">${html}</div>`;
    o.addEventListener("mousedown", (e) => { if (e.target === o) chiudiFinestra(); });
    document.body.appendChild(o);
    return o;
  }
  function chiudiFinestra() { $("sovrapposta")?.remove(); }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") chiudiFinestra(); });

  function chipTipologia(tipologia) {
    const gruppo = ["mobilita", "comando"].includes(tipologia) ? "MOB" : tipologia ? "TI" : "altro";
    return `<span class="chip t-${gruppo}">${esc(NOMI_TIPOLOGIA[tipologia] || tipologia || "Non indicata")}</span>`;
  }

  // Cella fonte: presente, mancante, protocollo diverso, fuori periodo, non caricato.
  const DOVE_FONTE = { sol: "Apri il bando su Selezioni Online", urp: "Apri il bando su URP", segreteria: "Apri nel file della segreteria" };
  function cellaFonte(riga, chiave) {
    const c = riga.fonti?.[chiave] || {};
    const diverso = c.stato === "presente" && riga.protocollo_diverso && c.protocollo && riga.protocollo && String(c.protocollo) !== String(riga.protocollo);
    const [classe, testo] = diverso ? ["f-diverso", "protocollo diverso"] : c.stato === "presente" ? ["f-presente", "presente"]
      : c.stato === "mancante" ? ["f-mancante", "mancante"] : c.stato === "non_applicabile" ? ["f-na", "fuori periodo"] : ["f-nonprev", "non caricato"];
    const contenuto = `${testo}${c.stato === "presente" ? `<small>${esc(c.protocollo || "")}</small>` : ""}`;
    return `<td class="cella-fonte ${classe}">${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener" title="${DOVE_FONTE[chiave]}">${contenuto}<span class="freccia"> ↗</span></a>` : contenuto}</td>`;
  }

  // RdP compatti: al massimo 2 nomi, poi "+N altri · email"; il clic apre i dettagli nella cella.
  const nomeRdp = (p) => [p.nome, p.cognome].filter(Boolean).join(" ");
  function cellaRdp(riga) {
    const persone = riga.rdp || [];
    if (!persone.length) return `<td class="rdp muted2">–</td>`;
    const altri = persone.length - 2;
    const dati = esc(JSON.stringify(persone));
    return `<td class="rdp" data-rdp="${dati}">${persone.slice(0, 2).map(p => `<div class="nome" title="${esc(nomeRdp(p))}">${esc(nomeRdp(p))}</div>`).join("")}
      <button type="button" class="link rdp-apri">${altri > 0 ? `+${altri} altri · email` : "email"}</button></td>`;
  }
  function collegaRdp(radice) {
    radice.querySelectorAll(".rdp-apri").forEach(b => b.onclick = (e) => {
      e.stopPropagation();
      const td = b.closest("td");
      const persone = JSON.parse(td.dataset.rdp);
      const chiuso = td.innerHTML;
      td.classList.add("rdp-aperto");
      td.innerHTML = persone.map(p => `<div class="nome">${esc(nomeRdp(p))}</div><div class="email">${p.email ? `<a href="mailto:${esc(p.email)}">${esc(p.email)}</a>` : "email non disponibile"}</div>`).join("") +
        `<button type="button" class="link rdp-copia">Copia indirizzi</button> · <button type="button" class="link rdp-chiudi">chiudi</button>`;
      td.querySelector(".rdp-copia").onclick = (ev) => { ev.stopPropagation(); copia(persone.map(p => p.email).filter(Boolean).join("; "), "Indirizzi copiati"); };
      td.querySelector(".rdp-chiudi").onclick = (ev) => { ev.stopPropagation(); td.classList.remove("rdp-aperto"); td.innerHTML = chiuso; collegaRdp(td); };
    });
  }

  async function copia(testo, messaggio) {
    try { await navigator.clipboard.writeText(testo); toast(messaggio || "Copiato"); return true; }
    catch { toast("Copia automatica non disponibile"); return false; }
  }

  // Candidati e punteggi SOL, in un pannello sotto la riga.
  function celleCandidati(riga) {
    const p = riga.punteggi;
    const candidati = p?.candidati ? `<button type="button" class="piccolo apri-candidati" data-scheda="${p.scheda_id}">${p.con_punteggi ?? ""} candidati ▾</button>` : "";
    const sol = riga.url_punteggi ? `<a class="small" href="${esc(riga.url_punteggi)}" target="_blank" rel="noopener">Punteggi su SOL ↗</a>` : "";
    return candidati || sol ? `<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:4px">${candidati}${sol}</div>` : "";
  }
  function collegaCandidati(radice, colonne) {
    radice.querySelectorAll(".apri-candidati").forEach(b => b.onclick = async (e) => {
      e.stopPropagation();
      const tr = b.closest("tr");
      if (tr.nextElementSibling?.classList.contains("riga-candidati")) { tr.nextElementSibling.remove(); return; }
      const riga = document.createElement("tr");
      riga.className = "riga-candidati";
      riga.innerHTML = `<td colspan="${colonne}" class="pannello-candidati">Caricamento…</td>`;
      tr.after(riga);
      const cella = riga.firstElementChild;
      try { cella.innerHTML = pannelloCandidati(await chiama(`/api/punteggi/candidati/${b.dataset.scheda}`)); }
      catch (err) { cella.innerHTML = `<span class="etichetta">${esc(err.message)}</span>`; }
    });
  }
  function pannelloCandidati(d) {
    const lista = d.candidati || [];
    const conta = (e) => lista.filter(c => (c.esito || "").toUpperCase() === e).length;
    const senza = lista.filter(c => !String(c.numero_protocollo_graduatoria || "").trim()).length;
    const prove = d.prove || [];
    const ESITI = { V: "Vincitore", I: "Idoneo", S: "Scorrimento" };
    return `<div style="margin-bottom:8px">${lista.length} candidati con punteggi · V ${conta("V")} · I ${conta("I")} · S ${conta("S")}
      ${senza ? ` <span class="etichetta">${senza} senza protocollo graduatoria</span>` : ""}
      ${d.url_punteggi ? ` · <a href="${esc(d.url_punteggi)}" target="_blank" rel="noopener"><b>Apri i punteggi su Selezioni Online ↗</b></a>` : ""}</div>
      <div class="scroll"><table><thead><tr><th>Pos.</th><th>Cognome</th><th>Nome</th><th>Nascita</th><th>Codice fiscale</th><th>Email</th><th>Email PEC</th>
        ${prove.map(p => `<th>${esc(p.nome || `Prova ${p.n}`)}${p.max ? ` /${esc(p.max)}` : ""}</th>`).join("")}<th>Totale</th><th>Esito</th><th>Prot. graduatoria</th></tr></thead><tbody>
      ${lista.map(c => `<tr><td>${esc(c.graduatoria)}</td><td>${esc(c.cognome)}</td><td>${esc(c.nome)}</td><td>${esc(dataIt(c.data_nascita))}</td><td class="mono">${esc(c.codice_fiscale)}</td><td>${esc(c.email)}</td><td>${esc(c.email_pec)}</td>
        ${prove.map(p => `<td>${esc(c.prove?.[p.n]?.punteggio)}</td>`).join("")}<td><b>${esc(c.totale_punteggio)}</b></td><td>${esc(c.esito)} ${esc(ESITI[(c.esito || "").toUpperCase()] || "")}</td>
        <td class="${String(c.numero_protocollo_graduatoria || "").trim() ? "" : "f-mancante"}">${esc(c.numero_protocollo_graduatoria) || "mancante"}</td></tr>`).join("")}
      </tbody></table></div>`;
  }

  return { $, esc, ora, dataIt, MESI, TIPOLOGIE, ATTI, chiama, json, toast, apriFinestra, chiudiFinestra, chipTipologia, cellaFonte, cellaRdp, collegaRdp, copia, celleCandidati, collegaCandidati };
})();
