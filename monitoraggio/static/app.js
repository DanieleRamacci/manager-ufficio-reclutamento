// Funzioni comuni delle pagine (specifiche grafiche, sezione 2): celle fonte, RdP, candidati, finestre, toast.
window.App = (() => {
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ora = (iso) => iso ? new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }) : "";
  const dataIt = (d) => (d || "").slice(0, 10).split("-").reverse().join("/");
  const MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
  const TIPOLOGIE = { TI: "Tempo indeterminato", MOB: "Mobilità" };
  const NOMI_TIPOLOGIA = { tempo_indeterminato: "Tempo indeterminato", reclutamento_speciale: "Reclutamento speciale", categorie_protette: "Categorie protette", mobilita: "Mobilità", comando: "Comando" };
  const ATTI = { bando: "Bando", graduatoria: "Graduatoria pubblica (oscurata)", scorrimento: "Scorrimento", rettifica: "Rettifica" };

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
  function avvisoAttesa(attesa) {
    if (!attesa?.length) return "";
    return `<div class="avviso" role="status"><b>Difformità sospese.</b> Le fonti non si possono ancora confrontare, quindi nessuna difformità viene segnata e non si possono inviare messaggi né chiudere il mese.
      Aggiornamento da concludere: ${attesa.map(f => `${esc(f.nome)} (${esc(f.motivo)})`).join(", ")}. <a class="solo-admin" href="/monitoraggio/impostazioni#aggiornamenti">Vai agli aggiornamenti</a></div>`;
  }
  const DOVE_FONTE = { sol: "Apri il bando su Selezioni Online", urp: "Apri su URP la pagina con tutti i documenti del bando", segreteria: "Apri nel file della segreteria" };
  function cellaFonte(riga, chiave) {
    const c = riga.fonti?.[chiave] || {};
    const diverso = c.stato === "presente" && riga.protocollo_diverso && c.protocollo && riga.protocollo && String(c.protocollo) !== String(riga.protocollo);
    const [classe, testo] = diverso ? ["f-diverso", "protocollo diverso"] : c.stato === "presente" ? ["f-presente", "presente"]
      : c.stato === "mancante" ? ["f-mancante", "mancante"] : c.stato === "non_applicabile" ? ["f-na", "fuori periodo"] : c.stato === "in_attesa" ? ["f-nonprev", "in attesa"] : ["f-nonprev", "non caricato"];
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

  // ricerca a testo libero: tutte le parole cercate devono comparire, in qualsiasi ordine
  const contieneTesto = (cerca, testo) => String(cerca || "").toLowerCase().split(/\s+/).filter(Boolean).every(p => String(testo || "").toLowerCase().includes(p));
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
    const manca = (c) => ["V", "I", "S"].includes((c.esito || "").trim().toUpperCase()) && !String(c.numero_protocollo_graduatoria || "").trim();  // solo a loro Selezioni Online scrive il protocollo
    const senza = lista.filter(manca).length;
    const prove = d.prove || [];
    const ESITI = { V: "Vincitore", I: "Idoneo", S: "Scorrimento" };
    const pubblica = d.graduatoria_pubblica || {};
    // Selezioni Online dà l'istante in UTC: conta il giorno in Italia, come nelle sue pagine
    const giorno = (v) => v && /T.*(Z|[+-]\d\d:?\d\d)$/.test(v) ? new Date(v).toLocaleDateString("sv-SE", { timeZone: "Europe/Rome" }) : v;
    const dataDiversa = (c) => pubblica.data && c.data_protocollo_graduatoria && String(giorno(c.data_protocollo_graduatoria)).slice(0, 10) !== pubblica.data;
    return `<div style="margin-bottom:8px">${lista.length} candidati con punteggi · V ${conta("V")} · I ${conta("I")} · S ${conta("S")}
      ${senza ? ` <span class="etichetta">${senza} senza protocollo graduatoria</span>` : ""}
      ${d.url_punteggi ? ` · <a href="${esc(d.url_punteggi)}" target="_blank" rel="noopener"><b>Apri i punteggi su Selezioni Online ↗</b></a>` : ""}
      ${pubblica.protocollo || pubblica.data ? `<div class="small">Graduatoria pubblica (oscurata) allegata: ${pubblica.protocollo ? `prot. ${esc(pubblica.protocollo)}` : ""}${pubblica.data ? ` del ${esc(dataIt(pubblica.data))}` : ""}</div>` : ""}</div>
      <div class="scroll"><table><thead><tr><th>Pos.</th><th>Cognome</th><th>Nome</th><th>Nascita</th><th>Codice fiscale</th><th>Email</th><th>Email PEC</th>
        ${prove.map(p => `<th>${esc(p.nome || `Prova ${p.n}`)}${p.max ? ` /${esc(p.max)}` : ""}</th>`).join("")}<th>Totale</th><th>Esito</th><th>Prot. graduatoria</th><th>Data prot.</th></tr></thead><tbody>
      ${lista.map(c => `<tr><td>${esc(c.graduatoria)}</td><td>${esc(c.cognome)}</td><td>${esc(c.nome)}</td><td>${esc(dataIt(c.data_nascita))}</td><td class="mono">${esc(c.codice_fiscale)}</td><td>${esc(c.email)}</td><td>${esc(c.email_pec)}</td>
        ${prove.map(p => `<td>${esc(c.prove?.[p.n]?.punteggio)}</td>`).join("")}<td><b>${esc(c.totale_punteggio)}</b></td><td>${esc(c.esito)} ${esc(ESITI[(c.esito || "").toUpperCase()] || "")}</td>
        <td class="${manca(c) ? "f-mancante" : ""}">${esc(c.numero_protocollo_graduatoria) || (manca(c) ? "mancante" : "–")}</td>
        <td class="${dataDiversa(c) ? "f-mancante" : ""}" title="${esc(c.data_protocollo_graduatoria)}">${esc(dataIt(giorno(c.data_protocollo_graduatoria)))}</td></tr>`).join("")}
      </tbody></table></div>`;
  }

  // Atto unico per più sedi: i rilievi «sede «X»: …» vanno nella sotto-riga di quella sede, sotto la riga del bando padre.
  const PREFISSO_SEDE = /^sede «([^»]*)»: /;
  function dividiPerSede(voci) {
    const perSede = new Map(), generali = [];
    voci.forEach(v => {
      const m = PREFISSO_SEDE.exec(v.testo);
      if (!m) { generali.push(v); return; }
      if (!perSede.has(m[1])) perSede.set(m[1], []);
      perSede.get(m[1]).push({ ...v, testo: v.testo.slice(m[0].length) });
    });
    return { generali, perSede };
  }
  // Le sedi di una riga: quelle note dal server, più quelle che compaiono solo nei rilievi
  function sediDellaRiga(riga, perSede) {
    const sedi = [...(riga.sedi || [])];
    perSede.forEach((_, codice) => { if (!sedi.some(s => s.codice === codice)) sedi.push({ codice }); });
    return sedi.length > 1 || perSede.size ? sedi : [];
  }
  const elencoRilievi = (voci) => voci.length ? `<ul class="rilievi">${voci.map(v => `<li class="${v.risolto ? "risolto" : ""}">${esc(v.testo)}</li>`).join("")}</ul>` : `<span class="muted small">nessuna difformità</span>`;

  // Testata dell'area referenti (RdP e coordinatori): le stesse due pagine del sito, più i profili per i coordinatori.
  function testataArea(v, attiva) {
    const voci = [["stato", "Stato complessivo", "/referenti/stato"], ["monitoraggi", "Monitoraggi", "/referenti/monitoraggi"],
      ...(v.coordinatore ? [["profili", "Profili che coordino", "/referenti/profili"]] : [])];
    const barra = document.createElement("div");
    barra.className = "mm-barra testata-area";
    barra.setAttribute("role", "navigation");
    barra.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px;background:#1f3a5f;color:#fff;padding:8px 16px;font-size:14px";
    barra.innerHTML = `<b style="margin-right:8px">Monitoraggio bandi</b>` + voci.map(([k, nome, url]) =>
      `<a href="${url}" style="color:#fff;text-decoration:none;padding:6px 10px;border-radius:6px;${k === attiva ? "background:rgba(255,255,255,.18)" : ""}"${k === attiva ? ' aria-current="page"' : ""}>${nome}</a>`).join("") +
      `<span style="margin-left:auto;display:flex;gap:10px;align-items:center;font-size:13px">${esc(v.email)} <button type="button" class="piccolo" id="esci-area">${v.anteprima ? "Chiudi l'anteprima" : "Esci"}</button></span>`;
    document.body.prepend(barra);
    if (v.anteprima) {
      const avviso = document.createElement("div");
      avviso.setAttribute("role", "status");
      avviso.style.cssText = "background:#7a4b00;color:#fff;padding:8px 16px;font-weight:600";
      avviso.textContent = `Anteprima dell'amministratore: stai vedendo l'area come ${v.email}. Le azioni sono disattivate.`;
      barra.after(avviso);
    }
    $("esci-area").onclick = async () => {
      await fetch("/api/area-referenti/esci", { method: "POST" });
      if (v.anteprima) { document.body.innerHTML = `<main><p>Anteprima chiusa. Puoi chiudere questa scheda.</p></main>`; return; }
      location.href = "/referenti";
    };
  }

  return { $, esc, ora, dataIt, MESI, TIPOLOGIE, ATTI, chiama, json, toast, apriFinestra, chiudiFinestra, avvisoAttesa, chipTipologia, cellaFonte, cellaRdp, collegaRdp, copia, celleCandidati, collegaCandidati, contieneTesto, pannelloCandidati, testataArea, dividiPerSede, sediDellaRiga, elencoRilievi };
})();
