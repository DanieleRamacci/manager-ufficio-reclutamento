"""Protocolli dalle email di Titulus in copia (spec 010): lettura, proposta, controlli, approvazione, programma per Windows."""
import importlib.util
import io
import zipfile
from pathlib import Path

from monitoraggio import atti, protocollo_email as pe
from tests.test_mensile import ambiente  # noqa: F401  (fixture)

# le due email reali mandate dall'utente il 2026-11-19
EMAIL_1 = """Il sistema di protocollo le ha assegnato il seguente documento in copia conoscenza:
N. 496971 del 20261118 (2026-CNR0A00-0496971)
Oggetto: Prova test parola chiave Valentina

Per visualizzare:
 https://titulus-cnr.cineca.it/fe/#/documento/002702338-CNR0A00-f8984abd-52be-47ec-8506-43fc50fb3a00
"""
EMAIL_2 = """Il sistema di protocollo le ha assegnato il seguente documento in copia conoscenza:
N. 485664 del 20261111 (2026-CNR0A00-0485664)
Oggetto: Provvedimento nomina personale vigilanza 367.634 FA IMM

Per visualizzare:
 https://titulus-cnr.cineca.it/fe/#/documento/002686734-CNR0A00-a9d44673-efff-49d7-9c1a-dcbb98c350c6
"""


def _voce(numero, data, oggetto, messaggio="m1"):
    return {"numero": numero, "data": data, "segnatura": f"{data[:4]}-CNR0A00-0{numero}", "oggetto": oggetto,
            "link": "https://titulus-cnr.cineca.it/fe/#/documento/x", "ricevuta_il": "2026-11-19T10:00", "id_messaggio": messaggio}


def test_legge_le_email_reali_di_titulus():
    v = pe.leggi_email("[CC]:Provvedimento nomina personale vigilanza 367.634 FA IMM", EMAIL_2)
    assert v == {"numero": "485664", "data": "20261111", "segnatura": "2026-CNR0A00-0485664",
                 "oggetto": "Provvedimento nomina personale vigilanza 367.634 FA IMM",
                 "link": "https://titulus-cnr.cineca.it/fe/#/documento/002686734-CNR0A00-a9d44673-efff-49d7-9c1a-dcbb98c350c6"}
    assert pe.leggi_email("", EMAIL_1)["numero"] == "496971"
    assert pe.leggi_email("Re: riunione", "Ciao, ci vediamo domani") is None


def test_proposta_dall_oggetto_con_la_frase():
    casi = {
        "Provvedimento nomina personale vigilanza 367.634 FA IMM": ("altro", None, "367.634"),
        "Provvedimento utilizzo graduatoria bando 367.524 CTER cod 03 AR RM1 - rinuncia Galeandro": ("scorrimento", "subentro", "367.524"),
        "Assunzione di una unità mediante l'utilizzo della graduatoria bando 367.434 CA Cod. 13": ("scorrimento", "ordinario", "367.434"),
        "Approvazione graduatoria di merito e nomina vincitore bando 367.498 RIC Sassari": ("graduatoria", None, "367.498"),
        "Rettifica graduatoria bando 367.562 RIC": ("rettifica", None, "367.562"),
        "Autorizzazione agli scorrimenti delle graduatorie bando 367.434 CA": ("autorizzazione", None, "367.434"),
        "Nomina commissione esaminatrice bando 367.640 CTER": ("commissione", None, "367.640"),
    }
    for oggetto, (categoria, sottotipo, bando) in casi.items():
        p = pe.classifica(oggetto)
        assert (p["categoria"], p["sottotipo"], p["numero_bando"]) == (categoria, sottotipo, bando), oggetto
        assert p["motivo"].startswith("nell'oggetto")
    assert pe.classifica("Provvedimento utilizzo graduatoria bando 367.434 Cod. 13")["codice_sotto"] == "13"


def test_dal_programma_alla_tabella_e_al_confronto(ambiente, db):  # noqa: F811
    admin = ambiente()
    programma = admin.application.test_client()
    voce = _voce("461293", "20261028", "Provvedimento utilizzo graduatoria bando 367.434 CA Cod. 13 Roma")
    assert programma.post("/api/programma-protocollo/ricevi", json={"voci": [voce]}).status_code == 401  # senza chiave
    chiave = admin.post("/api/segreteria/protocollo/chiavi", json={"nome": "PC segreteria"}).get_json()["chiave"]
    h = {"Authorization": f"Bearer {chiave}"}
    # un PC nuovo resta in attesa: niente viene salvato finché un amministratore non lo abilita
    r = programma.post("/api/programma-protocollo/ricevi", json={"casella": "seg@cnr.it", "voci": [voce]}, headers=h)
    assert r.status_code == 403 and "in attesa di abilitazione" in r.get_json()["error"]
    assert admin.get("/api/segreteria/protocollo").get_json()["protocolli"] == []
    pc = admin.get("/api/impostazioni/programma-protocollo").get_json()["pc"][0]
    assert pc["stato"] == "in_attesa" and pc["nome_pc"] == "PC senza nome" and pc["nome_chiave"] == "PC segreteria"
    assert admin.put(f"/api/impostazioni/programma-protocollo/pc/{pc['id']}", json={"abilitato": True}).status_code == 200
    assert programma.post("/api/programma-protocollo/ricevi", json={"casella": "seg@cnr.it", "voci": [voce]}, headers=h).get_json() == {"nuove": 1, "gia_presenti": 0}
    assert programma.post("/api/programma-protocollo/ricevi", json={"voci": [voce]}, headers=h).get_json() == {"nuove": 0, "gia_presenti": 0}  # stessa email
    # stesso protocollo da un'altra casella con un altro oggetto, e un protocollo simile (una cifra diversa)
    programma.post("/api/programma-protocollo/ricevi", headers=h, json={"casella": "altra@cnr.it", "voci": [
        _voce("0461293", "20261028", "Utilizzo graduatoria 367.434 sede Roma", "m2"), _voce("461298", "20261028", "Utilizzo graduatoria 367.434 Cod. 17", "m3")]})
    d = admin.get("/api/segreteria/protocollo").get_json()
    r = next(x for x in d["protocolli"] if x["numero"] == "461293")
    assert r["categoria"] == "scorrimento" and r["sottotipo"] == "ordinario" and r["numero_bando"] == "367.434" and r["codice_sotto"] == "13"
    testi = [c["testo"] for c in r["controlli"]]
    assert "stesso protocollo ricevuto 2 volte" in testi
    assert "stesso protocollo con un altro oggetto: «Utilizzo graduatoria 367.434 sede Roma»" in testi
    assert "protocollo simile già ricevuto: 461298 (errore di battitura?)" in testi
    assert "non è nel file della segreteria" in testi and "bando 367.434 non trovato nel sistema" in testi
    # approvato, vale come riga del file della segreteria «aggiunta automaticamente»
    assert admin.put(f"/api/segreteria/protocollo/{r['id']}", json={"categoria": "scorrimento", "sottotipo": "subentro", "numero_bando": "367434",
                                                                    "codice_sotto": "13", "note": "rinuncia"}).status_code == 200
    assert admin.post(f"/api/segreteria/protocollo/{r['id']}/stato", json={"stato": "approvato"}).status_code == 200
    seg = next(a for a in atti.elenco_atti(db, "2026-10-01", "2026-10-31") if a["protocollo"] == "461293")
    assert seg["atto"] == "scorrimento" and seg["fonti"]["segreteria"]["stato"] == "presente" and seg["fonti"]["segreteria"]["automatico"]
    # la chiave revocata non vale più
    id_chiave = admin.get("/api/segreteria/protocollo").get_json()["chiavi"][0]["id"]
    admin.delete(f"/api/segreteria/protocollo/chiavi/{id_chiave}")
    assert programma.post("/api/programma-protocollo/ricevi", json={"voci": [voce]}, headers=h).status_code == 401


def test_approvare_uno_scorrimento_richiede_il_bando(ambiente, db):  # noqa: F811
    admin = ambiente()
    pe.ricevi(db, [_voce("500001", "20261020", "Utilizzo della graduatoria senza numero")], "seg", "seg@cnr.it")
    r = admin.get("/api/segreteria/protocollo").get_json()["protocolli"][0]
    assert admin.post(f"/api/segreteria/protocollo/{r['id']}/stato", json={"stato": "approvato"}).status_code == 400
    assert admin.put(f"/api/segreteria/protocollo/{r['id']}", json={"categoria": "scorrimento"}).status_code == 400  # serve la tipologia


def test_zip_per_windows_e_lettura_di_una_cartella(ambiente, tmp_path):  # noqa: F811
    admin = ambiente()
    z = zipfile.ZipFile(io.BytesIO(admin.get("/monitoraggio/segreteria/programma-protocollo").data))
    nomi = set(z.namelist())
    assert {"Protocollo-monitoraggio/protocollo_cnr.py", "Protocollo-monitoraggio/Prova-senza-inviare.bat",
            "Protocollo-monitoraggio/Leggi-e-invia.bat", "Protocollo-monitoraggio/Controllo-continuo.bat", "Protocollo-monitoraggio/LEGGIMI.txt"} <= nomi
    auto = z.read("Protocollo-monitoraggio/Avvio-automatico-attiva.bat").decode()
    assert "schtasks /Create" in auto and "/MO 15" in auto and "pythonw.exe" in auto and "--registro" in auto and "\r\n" in auto
    assert "schtasks /Delete" in z.read("Protocollo-monitoraggio/Avvio-automatico-disattiva.bat").decode()
    bat = z.read("Protocollo-monitoraggio/Prova-senza-inviare.bat")
    assert b"\r\n" in bat and b"--prova" in bat and b"%LOCALAPPDATA%\\MonitoraggioProtocollo" in bat
    codice = z.read("Protocollo-monitoraggio/protocollo_cnr.py").decode()
    assert "__SERVER__" not in codice and 'SERVER = "http://localhost"' in codice
    # il programma legge una cartella di email salvate (.eml)
    (tmp_path / "prog").mkdir()
    (tmp_path / "prog" / "protocollo_cnr.py").write_text(codice)
    spec = importlib.util.spec_from_file_location("protocollo_cnr", tmp_path / "prog" / "protocollo_cnr.py")
    prog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prog)
    (tmp_path / "email").mkdir()
    (tmp_path / "email" / "a.eml").write_text("Subject: [CC]:Provvedimento nomina personale vigilanza 367.634 FA IMM\nMessage-ID: <a@x>\n"
                                              "Content-Type: text/plain; charset=utf-8\n\n" + EMAIL_2)
    (tmp_path / "email" / "b.eml").write_text("Subject: altro\n\nNon c'entra")
    voci, _ = prog.da_cartella(str(tmp_path / "email"))
    assert [(v["numero"], v["oggetto"]) for v in voci] == [("485664", "Provvedimento nomina personale vigilanza 367.634 FA IMM")]
    assert Path(prog.CONFIG).name == "config.json"


class _Data:
    def __init__(self, d):
        self.year, self.month, self.day, self.hour, self.minute = d.year, d.month, d.day, d.hour, d.minute


class _Email:
    Class = 43

    def __init__(self, corpo, oggetto, quando, id_):
        self.Body, self.Subject, self.ReceivedTime, self.EntryID = corpo, oggetto, _Data(quando), id_


class _Raccolta(list):
    """Come le raccolte di Outlook: Count e Item(i) da 1; un elemento None simula quello che non risponde."""
    @property
    def Count(self):
        return len(self)

    def Item(self, i):
        if self[i - 1] is None:
            raise OSError(-1039924975, "OLE error 0xc2040111")
        return self[i - 1]


class _Elementi(_Raccolta):
    def Sort(self, *a):
        self.sort(key=lambda e: (e.ReceivedTime.year, e.ReceivedTime.month, e.ReceivedTime.day), reverse=True)


class _Cartella:
    def __init__(self, email=(), sotto=()):
        self.Items, self.Folders = _Elementi(email), _Raccolta(sotto)


class _Casella:
    def __init__(self, nome, inbox, tipo=0):
        self.DisplayName, self._inbox, self.ExchangeStoreType = nome, inbox, tipo

    def GetDefaultFolder(self, n):
        return self._inbox

    def GetRootFolder(self):
        return _Cartella(sotto=[self._inbox])


def test_piu_caselle_in_outlook_ognuna_con_il_suo_nome(ambiente, tmp_path, monkeypatch):  # noqa: F811
    from datetime import datetime
    admin = ambiente()
    codice = zipfile.ZipFile(io.BytesIO(admin.get("/monitoraggio/segreteria/programma-protocollo").data)).read("Protocollo-monitoraggio/protocollo_cnr.py").decode()
    (tmp_path / "protocollo_cnr.py").write_text(codice)
    spec = importlib.util.spec_from_file_location("protocollo_cnr2", tmp_path / "protocollo_cnr.py")
    prog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prog)
    oggi = datetime.now()
    personale = _Casella("mario.rossi@cnr.it", _Cartella([_Email(EMAIL_1, "[CC]:Prova", oggi, "a"), _Email("ciao", "riunione", oggi, "b")]))
    segreteria = _Casella("Segreteria Reclutamento", _Cartella([], [_Cartella([_Email(EMAIL_2, "[CC]:vigilanza", oggi, "c")])]))
    pubbliche = _Casella("Cartelle pubbliche", _Cartella([_Email(EMAIL_2, "x", oggi, "d")]), tipo=2)

    class _Ns:
        Stores = _Raccolta([personale, None, segreteria, pubbliche])  # None: la casella che dà l'errore OLE 0xc2040111
    monkeypatch.setattr(prog, "_outlook", lambda: _Ns())
    voci, lette = prog.da_outlook(60)
    assert lette == ["mario.rossi@cnr.it", "Segreteria Reclutamento"]  # le cartelle pubbliche no
    assert sorted((v["numero"], v["casella"]) for v in voci) == [("485664", "Segreteria Reclutamento"), ("496971", "mario.rossi@cnr.it")]
    voci, lette = prog.da_outlook(60, filtro=["segreteria"])
    assert lette == ["Segreteria Reclutamento"] and [v["numero"] for v in voci] == ["485664"]


def test_la_casella_di_ogni_email_arriva_nella_tabella(ambiente, db):  # noqa: F811
    admin = ambiente()
    pe.ricevi(db, [{**_voce("485664", "20261111", "Provvedimento nomina personale vigilanza 367.634 FA IMM", "a"), "casella": "Segreteria Reclutamento"},
                   {**_voce("485664", "20261111", "Provvedimento nomina personale vigilanza 367.634 FA IMM", "b"), "casella": "mario.rossi@cnr.it"}], "seg", "")
    r = admin.get("/api/segreteria/protocollo").get_json()["protocolli"][0]
    assert [x["casella"] for x in r["ricevute"]] == ["Segreteria Reclutamento", "mario.rossi@cnr.it"]



def test_pc_che_comunicano_abilita_disabilita(ambiente, db):  # noqa: F811
    admin = ambiente()
    programma = admin.application.test_client()
    chiave = admin.post("/api/segreteria/protocollo/chiavi", json={"nome": "Segreteria"}).get_json()["chiave"]
    h = {"Authorization": f"Bearer {chiave}"}
    pc = {"nome": "PC-SEGRETERIA-01", "utente": "maria.bianchi", "versione": "1.1", "caselle": ["Segreteria Reclutamento", "maria.bianchi@cnr.it"]}
    assert programma.post("/api/programma-protocollo/ricevi", json={"voci": [], "pc": pc}, headers=h).status_code == 403  # contatto senza email
    d = admin.get("/api/impostazioni/programma-protocollo").get_json()["pc"][0]
    assert (d["nome_pc"], d["utente_windows"], d["caselle"], d["contatti"]) == ("PC-SEGRETERIA-01", "maria.bianchi", pc["caselle"], 1)
    admin.put(f"/api/impostazioni/programma-protocollo/pc/{d['id']}", json={"abilitato": True})
    assert programma.post("/api/programma-protocollo/ricevi", json={"voci": [_voce("461293", "20261028", "Utilizzo graduatoria 367.434")], "pc": pc},
                          headers=h).get_json() == {"nuove": 1, "gia_presenti": 0}
    d = admin.get("/api/impostazioni/programma-protocollo").get_json()["pc"][0]
    assert d["stato"] == "abilitato" and d["email_ricevute"] == 1 and d["contatti"] == 2 and d["deciso_da"]
    # un altro PC con la stessa chiave è un PC diverso: anche lui in attesa
    assert programma.post("/api/programma-protocollo/ricevi", json={"voci": [], "pc": {**pc, "nome": "PC-CASA"}}, headers=h).status_code == 403
    admin.put(f"/api/impostazioni/programma-protocollo/pc/{d['id']}", json={"abilitato": False})
    r = programma.post("/api/programma-protocollo/ricevi", json={"voci": [], "pc": pc}, headers=h)
    assert r.status_code == 403 and "disabilitato" in r.get_json()["error"]
    # solo gli amministratori vedono e decidono
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    assert admin.application.test_client().get("/api/impostazioni/programma-protocollo").status_code in (302, 401, 403)
