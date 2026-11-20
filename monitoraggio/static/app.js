// Funzioni comuni delle pagine (specifiche grafiche, sezione 2): celle fonte, RdP, candidati, finestre, toast.
// app installabile (spec 009): manifest e service worker, una volta sola per pagina
if (!document.querySelector('script[src="/pwa.js"]')) { const s = document.createElement("script"); s.src = "/pwa.js"; s.defer = true; document.head.appendChild(s); }
window.App = (() => {
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ora = (iso) => iso ? new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }) : "";
  const dataIt = (d) => (d || "").slice(0, 10).split("-").reverse().join("/");
  const MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
  const TIPOLOGIE = { TI: "Tempo indeterminato", MOB: "Mobilità" };
  const NOMI_TIPOLOGIA = { tempo_indeterminato: "Tempo indeterminato", reclutamento_speciale: "Reclutamento speciale", categorie_protette: "Categorie protette", mobilita: "Mobilità", comando: "Comando" };
  const ATTI = { bando: "Bando", graduatoria: "Graduatoria pubblica con i soli vincitori", scorrimento: "Scorrimento", rettifica: "Rettifica",
    deserto: "Concorso deserto", revocato: "Bando revocato", senza_esito: "Senza esito da oltre 12 mesi" };
  // tipi di atto con una scheda propria (spec 012: deserti e revocati); gli altri vanno in «Altri atti»
  const ATTI_CON_SCHEDA = ["bando", "graduatoria", "scorrimento", "rettifica", "deserto", "revocato"];

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
    const [classe, testoStato] = diverso ? ["f-diverso", "protocollo diverso"] : c.stato === "presente" ? ["f-presente", "presente"]
      : c.stato === "mancante" ? ["f-mancante", "mancante"] : c.stato === "non_applicabile" ? ["f-na", "fuori periodo"] : c.stato === "in_attesa" ? ["f-nonprev", "in attesa"] : ["f-nonprev", "non caricato"];
    const testo = c.testo || testoStato;  // spec 012: «non nel file», «nessun esito»
    const contenuto = `${esc(testo)}${c.stato === "presente" ? `<small>${esc(c.protocollo || "")}</small>` : ""}${c.automatico ? `<small title="Protocollo approvato dalle email di Titulus, non ancora nel file caricato">aggiunto automaticamente</small>` : ""}`;
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
      ${pubblica.protocollo || pubblica.data ? `<div class="small">Graduatoria pubblica con i soli vincitori allegata: ${pubblica.protocollo ? `prot. ${esc(pubblica.protocollo)}` : ""}${pubblica.data ? ` del ${esc(dataIt(pubblica.data))}` : ""}</div>` : ""}</div>
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

  // Tabella dei totali del monitoraggio (spec 011): per voce quanti atti risultano a noi e quanti sono nei file caricati.
  // `link(codice)`: indirizzo della pagina del monitoraggio filtrata sul bando, per controllare un atto che manca.
  function tabellaTotali(tot, link) {
    const pers = (n, c) => c.senza_persone || !n ? "" : ` <span class="muted small">(${n} ${n === 1 ? "persona" : "persone"})</span>`;
    const confronto = (c) => !c.nei_file_da || c.categoria === "Bandi pubblicati";
    const coppia = (v, c) => `${v.attesi}${confronto(c) ? ` <span class="muted small">· nei file</span> ${v.nei_file}` : ""}`;
    const righe = tot.categorie.map(c => {
      const t = c.totale, mancano = confronto(c) ? t.attesi - t.nei_file : null;
      return `<tr><td><b>${esc(c.categoria)}</b>${c.nei_file_da ? `<div class="muted small">${esc(c.nei_file_da)}</div>` : ""}</td>
        <td style="text-align:center"><b>${t.attesi}</b>${pers(t.persone_attese, c)}</td>
        <td style="text-align:center">${confronto(c) ? `<b>${t.nei_file}</b>${pers(t.persone_nei_file, c)}` : `<span class="muted2">–</span>`}</td>
        <td style="text-align:center">${mancano === null ? `<span class="muted2">–</span>` : mancano > 0 ? `<b style="color:var(--ko)">${mancano}</b>` : mancano < 0 ? `<b style="color:var(--warn)">${-mancano} in più</b>` : `<span style="color:var(--ok)">0</span>`}
          ${(c.mancanti || []).length ? `<div class="small" style="text-align:left;margin-top:4px">${c.mancanti.map(x => `<div>${link ? `<a href="${esc(link(x.codice))}" title="Apri il monitoraggio filtrato su questo bando">${esc(x.codice)}</a>` : esc(x.codice)}${x.protocollo ? ` <span class="muted">prot. ${esc(x.protocollo)}</span>` : ""}${x.mobilita ? ` <span class="muted">(mobilità)</span>` : ""}</div>`).join("")}</div>` : ""}</td>
        <td class="small">${coppia(c.concorsi, c)}</td><td class="small">${coppia(c.mobilita, c)}</td>
        <td class="small">${c.per_gruppo.map(g => `${esc(g.nome)}: ${coppia(g, c)}`).join("<br>")}</td></tr>`;
    }).join("");
    const tip = Object.entries(tot.scorrimenti_per_tipologia || {}).map(([k, n]) => `${esc(k)} ${n}`).join(" · ");
    return `<div class="scroll"><table><thead><tr><th>Voce</th><th style="text-align:center">Risultano a noi</th><th style="text-align:center">Nei file caricati</th>
      <th style="text-align:center">Mancano nei file</th><th>Concorsi</th><th>Mobilità</th><th>Per profilo</th></tr></thead><tbody>${righe}</tbody></table></div>
      ${tip ? `<p class="small" style="margin:6px 0 0">Scorrimenti per tipologia indicata nel file: ${tip}</p>` : ""}`;
  }

  // Di cosa è fatto il totale della scheda «Tutti»: i subentri sono già tra gli scorrimenti, le rettifiche non hanno una scheda.
  function scomposizioneAtti(righe) {
    const n = (f) => righe.filter(f).length, plurale = (k, uno, molti) => `${k} ${k === 1 ? uno : molti}`;
    const parti = [plurale(n(r => r.atto === "bando"), "bando pubblicato", "bandi pubblicati"), plurale(n(r => r.atto === "graduatoria"), "graduatoria", "graduatorie"),
      `${plurale(n(r => r.atto === "scorrimento"), "scorrimento", "scorrimenti")} (di cui ${plurale(n(r => r.sottotipo === "subentro"), "subentro", "subentri")})`];
    const rettifiche = n(r => r.atto === "rettifica"), altri = n(r => !ATTI_CON_SCHEDA.includes(r.atto));
    const deserti = n(r => r.atto === "deserto"), revocati = n(r => r.atto === "revocato");
    if (rettifiche) parti.push(plurale(rettifiche, "rettifica di graduatoria", "rettifiche di graduatoria"));
    if (deserti) parti.push(plurale(deserti, "concorso deserto", "concorsi deserti"));
    if (revocati) parti.push(plurale(revocati, "bando revocato", "bandi revocati"));
    if (altri) parti.push(plurale(altri, "altro atto", "altri atti"));
    return `${plurale(righe.length, "atto", "atti")}: ${parti.join(", ")}.`;
  }

  // Comunicazione ai referenti di un atto (monitoraggio e stato complessivo, spec 009): stato, protocollo dell'email, storico.
  // Ritorna i pezzi; ogni pagina aggiunge le sue azioni.
  function partiComunicazione(c) {
    const storico = [...(c.storico || [])].sort((a, b) => String(a.data || "").localeCompare(String(b.data || "")));
    let numeroInvio = 0;
    const righeStorico = storico.map(s => {
      const inviata = s.stato === "inviata";
      const tipo = inviata ? (++numeroInvio === 1 ? "Prima comunicazione" : `Sollecito ${numeroInvio - 1}`)
        : s.stato === "prova" ? "Invio di prova" : s.stato === "annullata" ? "Annullata" : "Da confermare";
      const statoInvio = inviata ? (s.canale === "Segnata a mano" ? "segnata come inviata" : "inviata") : s.stato;
      return `<div class="small" style="padding:4px 0;border-top:1px solid var(--border-soft)"><b>${tipo}</b> · ${ora(s.data)} · ${esc(statoInvio)}${s.utente ? ` · ${esc(s.utente)}` : ""}${s.oggetto ? `<div class="muted" title="${esc(s.oggetto)}" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.oggetto)}</div>` : ""}</div>`;
    }).join("");
    const invii = storico.filter(s => s.stato === "inviata").length, prove = storico.filter(s => s.stato === "prova").length;
    const storicoHtml = storico.length ? `<details style="margin-top:5px"><summary class="small">Storico: ${invii} ${invii === 1 ? "invio" : "invii"}${prove ? ` · ${prove} prove` : ""}</summary>${righeStorico}</details>` : "";
    const P = { in_attesa: ["p-na", "in attesa delle fonti"], in_regola: ["p-na", "in regola"], da_inviare: ["p-ko", "da inviare"],
      da_confermare: ["p-warn", "copiata · da confermare"], inviata: ["p-ok", `inviata ${dataIt(c.quando).slice(0, 5)}`],
      inviata_a_mano: ["p-ok", `inviata ${dataIt(c.quando).slice(0, 5)}`] }[c.stato] || ["p-blu", String(c.stato || "").replace(/_/g, " ")];
    return { pillola: `<span class="pillola ${P[0]}">${esc(P[1])}</span>`, storico: storicoHtml,
      id: c.id ? `<div class="mono muted2" style="font-size:10.5px;margin-top:3px">${esc(c.id)}</div>` : "",
      azionabile: !["in_attesa", "in_regola"].includes(c.stato), inviata: ["inviata", "inviata_a_mano"].includes(c.stato) };
  }

  // Spec 012: esporta in Excel le righe visibili. colonne: [[chiave, titolo, (riga) => valore], ...]; la scelta delle colonne
  // resta nel browser per pagina. url: l'API che fa il file (amministrazione o area referenti).
  function esportaExcel({ colonne, righe, nome, url, chiave }) {
    const memoria = `esporta-colonne:${chiave || location.pathname}`;
    let scelte = null;
    try { scelte = JSON.parse(localStorage.getItem(memoria) || "null"); } catch { scelte = null; }
    const attive = new Set(Array.isArray(scelte) ? scelte : colonne.map(c => c[0]));
    document.getElementById("esporta-finestra")?.remove();
    const o = document.createElement("div");
    o.id = "esporta-finestra";
    o.style.cssText = "position:fixed;inset:0;background:rgba(20,28,40,.4);z-index:3000;display:flex;align-items:center;justify-content:center;padding:16px";
    o.innerHTML = `<div role="dialog" aria-modal="true" aria-labelledby="esporta-titolo" style="background:var(--surface,#fff);color:inherit;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.25);width:100%;max-width:560px;max-height:90vh;display:flex;flex-direction:column">
      <div style="padding:14px 18px;border-bottom:1px solid #e3e6ea"><b id="esporta-titolo">Esporta in Excel</b><div style="font-size:12.5px;opacity:.75;margin-top:2px">${righe.length} ${righe.length === 1 ? "riga" : "righe"}, con i filtri attivi. Scegli le colonne.</div></div>
      <div style="padding:12px 18px;overflow:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px">
        ${colonne.map(([k, t]) => `<label style="display:flex;gap:6px;align-items:center;font-size:13.5px"><input type="checkbox" value="${esc(k)}"${attive.has(k) ? " checked" : ""}> ${esc(t)}</label>`).join("")}</div>
      <div style="padding:12px 18px;border-top:1px solid #e3e6ea;display:flex;gap:8px;justify-content:space-between;flex-wrap:wrap">
        <span><button type="button" data-tutte="1">Tutte</button> <button type="button" data-tutte="0">Nessuna</button></span>
        <span><button type="button" id="esporta-annulla">Annulla</button> <button type="button" class="primario" id="esporta-scarica">Scarica Excel</button></span></div></div>`;
    document.body.appendChild(o);
    const caselle = () => [...o.querySelectorAll("input[type=checkbox]")];
    o.querySelectorAll("[data-tutte]").forEach(b => b.onclick = () => caselle().forEach(c => { c.checked = b.dataset.tutte === "1"; }));
    const chiudi = () => o.remove();
    o.addEventListener("mousedown", (e) => { if (e.target === o) chiudi(); });
    o.querySelector("#esporta-annulla").onclick = chiudi;
    o.querySelector("#esporta-scarica").onclick = async (e) => {
      const scelte = caselle().filter(c => c.checked).map(c => c.value);
      if (!scelte.length) return toast("Scegli almeno una colonna");
      try { localStorage.setItem(memoria, JSON.stringify(scelte)); } catch { /* solo comodità */ }
      const usate = colonne.filter(c => scelte.includes(c[0]));
      const valore = (v) => v === null || v === undefined ? "" : typeof v === "number" ? v : String(v);
      e.target.disabled = true;
      try {
        const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
          body: JSON.stringify({ nome, colonne: usate.map(c => c[1]), righe: righe.map(x => usate.map(c => valore(c[2](x)))) }) });
        if (!r.ok) { const c = await r.json().catch(() => ({})); throw new Error(c.error || `Errore ${r.status}`); }
        const blob = await r.blob();
        const nomeFile = (/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(r.headers.get("Content-Disposition") || "") || [])[1] || `${nome || "esportazione"}.xlsx`;
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = decodeURIComponent(nomeFile);
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        chiudi();
      } catch (err) { toast(err.message); e.target.disabled = false; }
    };
  }
  // Colonne comuni delle righe degli atti (stato complessivo): valori come li vede la pagina
  function colonneAtti() {
    const fonte = (k) => (r) => { const c = r.fonti?.[k] || {}; return c.testo || { presente: "presente", mancante: "mancante", non_applicabile: "fuori periodo", non_caricato: "non caricato", in_attesa: "in attesa" }[c.stato] || c.stato || ""; };
    const persone = (l) => (l || []).map(p => [p.nome, p.cognome].filter(Boolean).join(" ") || p.email).join("; ");
    return [
      ["data", "Data", r => dataIt(r.data)], ["numero_bando", "N. bando", r => r.numero_bando], ["codice", "Codice", r => r.codice],
      ["titolo_bando", "Titolo del bando", r => r.titolo_bando], ["tipologia", "Tipologia", r => NOMI_TIPOLOGIA[r.tipologia] || r.tipologia],
      ["atto", "Atto", r => ATTI[r.atto] || r.atto], ["sottotipo", "Sottotipo", r => r.sottotipo && r.sottotipo !== "non_specificato" ? r.sottotipo : ""],
      ["protocollo", "Protocollo", r => r.protocollo], ["titolo", "Titolo del documento", r => r.titolo],
      ["sol", "Selezioni Online", fonte("sol")], ["prot_sol", "Protocollo SOL", r => r.fonti?.sol?.protocollo], ["link_sol", "Link SOL", r => r.fonti?.sol?.url || r.link_sol],
      ["urp", "URP", fonte("urp")], ["prot_urp", "Protocollo URP", r => r.fonti?.urp?.protocollo], ["link_urp", "Link URP", r => r.fonti?.urp?.url],
      ["segreteria", "File segreteria", fonte("segreteria")], ["prot_segreteria", "Protocollo segreteria", r => r.fonti?.segreteria?.protocollo],
      ["difforme", "Con difformità", r => r.difforme ? "sì" : "no"], ["note", "Note e difformità", r => [...(r.note || []), ...(r.avviso ? [r.avviso] : [])].join("; ")],
      ["rdp", "RdP", r => persone(r.rdp)], ["rdp_email", "Email RdP", r => (r.rdp || []).map(p => p.email).filter(Boolean).join("; ")],
      ["coordinatore", "Coordinatore", r => r.coordinatore?.email || ""], ["persone", "Persone nel file segreteria", r => r.persone ?? ""],
    ];
  }

  return { $, esc, ora, dataIt, MESI, TIPOLOGIE, ATTI, ATTI_CON_SCHEDA, esportaExcel, colonneAtti, chiama, json, toast, partiComunicazione, scomposizioneAtti, tabellaTotali, apriFinestra, chiudiFinestra, avvisoAttesa, chipTipologia, cellaFonte, cellaRdp, collegaRdp, copia, celleCandidati, collegaCandidati, contieneTesto, pannelloCandidati, testataArea, dividiPerSede, sediDellaRiga, elencoRilievi };
})();
