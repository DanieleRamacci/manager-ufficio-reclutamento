(() => {
  const emailRdp = (righe) => [...new Set(righe.flatMap(r => (r.rdp || []).map(p => (p.email || "").trim()).filter(Boolean)))];

  function rilievi(riga) {
    const atto = riga.atto === "graduatoria" ? "la graduatoria pubblica (oscurata)" : "il provvedimento di assunzione idoneo (scorrimento/utilizzo della graduatoria)";
    const rilievi = [...(riga.note || [])];
    const rif = riga.protocollo ? ` (prot. ${riga.protocollo})` : "";
    const fonti = { sol: "Selezioni Online", urp: "URP", segreteria: "file di riepilogo della segreteria" };
    Object.entries(fonti).forEach(([chiave, nome]) => {
      if (riga.fonti?.[chiave]?.stato !== "mancante") return;
      rilievi.push(`${atto}${rif} non risulta tra i dati attualmente disponibili da ${nome}`);
    });
    return [...new Set(rilievi.filter(Boolean))];
  }

  function messaggio(riga, righeBando, mese) {
    const destinatari = emailRdp(righeBando);
    const codici = [...new Set(righeBando.map(r => r.codice).filter(Boolean))];
    const numero = (codici.length === 1 ? codici[0] : riga.numero_bando) || "numero non disponibile";
    const codice = codici.length > 1 ? `Codici/sedi interessati: ${codici.join(", ")}\n\n` : "";
    const url = righeBando.map(r => r.link_codice || r.fonti?.sol?.url).find(Boolean);
    const urlRiga = riga.link_codice || riga.fonti?.sol?.url;
    const collegamento = url || urlRiga;
    // un link per ogni codice con rilievi: ogni codice ha la sua scheda su Selezioni Online
    const perCodice = new Map();
    righeBando.filter(r => rilievi(r).length).forEach(r => {
      const indirizzo = r.link_codice || r.fonti?.sol?.url;
      if (indirizzo && !perCodice.has(indirizzo)) perCodice.set(indirizzo, r.codice || "");
    });
    if (!perCodice.size && collegamento) perCodice.set(collegamento, riga.codice || "");
    const link = perCodice.size > 1
      ? `Link alle schede su Selezioni Online:\n\n${[...perCodice].map(([indirizzo, nome]) => `${nome}:\n${indirizzo}`).join("\n\n")}`
      : perCodice.size ? `Link al bando su Selezioni Online:\n${[...perCodice.keys()][0]}` : "";
    const voci = righeBando.flatMap(r => {
      const note = rilievi(r);
      if (!note.length) return [];
      const tipo = r.atto === "graduatoria" ? "Graduatoria pubblica (oscurata)" : "Provvedimento di assunzione idoneo / scorrimento";
      const riferimento = [r.codice || "", tipo, r.data ? r.data.slice(0, 10).split("-").reverse().join("/") : "", r.protocollo ? `prot. ${r.protocollo}` : ""]
        .filter(Boolean).join(" · ");
      return note.map(n => `- ${riferimento}: ${n}`);
    });
    const noteFinali = [...new Set(voci)];
    const meseTesto = mese ? new Date(`${mese}-01T00:00:00`).toLocaleDateString("it-IT", { month: "long", year: "numeric" }) : "mese selezionato";
    const oggetto = `Monitoraggio ${meseTesto}. Bando n° ${numero}: Aggiornamento Dati`;
    const email = destinatari.length ? destinatari.join("; ") : "Nessun indirizzo email RdP disponibile";
    const corpo = `Buongiorno gentili tutte e tutti,\n\nnell'ambito del monitoraggio mensile di ${meseTesto}, nella scheda Selezioni Online del bando ${numero} abbiamo rilevato le seguenti difformità:\n\n${codice}${(noteFinali.length ? noteFinali : ["- Verifica richiesta sui dati del bando."]).join("\n\n")}\n\nVi chiediamo cortesemente di verificare quanto indicato e di comunicarci l'avvenuta correzione.\n\nGrazie per la collaborazione.\nCordiali saluti.`;
    const completo = `Destinatari (da incollare nel campo A):\n${email}\n\nOggetto:\n${oggetto}\n\n${link || "Link non disponibile"}\n\nTesto:\n${corpo}`;
    return { destinatari: destinatari.join("; "), oggetto, corpo, completo, collegamento, link, mese };
  }

  async function copia(contenuto, titolo) {
    try {
      if (!contenuto || !navigator.clipboard?.writeText) throw new Error("Appunti non disponibili");
      await navigator.clipboard.writeText(contenuto);
      return { copiato: true, testo: contenuto, titolo };
    } catch {
      return { copiato: false, testo: contenuto || "Nessun indirizzo email RdP disponibile.", titolo };
    }
  }

  window.Solleciti = {
    // ogni codice ha i suoi RdP: un sollecito per codice, mai per l'intero numero di bando
    chiave: (riga) => riga.codice || riga.numero_bando || "",
    destinatari: (righe) => emailRdp(righe),
    crea: messaggio,
    copiaEmail: (righe) => copia(emailRdp(righe).join("; "), "Indirizzi RdP"),
    copiaMessaggio: (riga, righeBando, mese) => copia(messaggio(riga, righeBando, mese).completo, "Sollecito completo"),
  };
})();
