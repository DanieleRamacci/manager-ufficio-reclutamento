from monitoraggio import comunicazioni


def _riga(atto, sol="presente", rilievi=()):
    return {"atto": atto, "fonti": {"sol": {"stato": sol}}, "rilievi": list(rilievi)}


def test_istruzioni_email_per_caso():
    # A: graduatoria su SOL con punteggi/esiti da completare
    a = [_riga("graduatoria", "presente", ["esito (V/I/S) mancante su SOL (3 candidati)"])]
    assert comunicazioni.istruzioni_email(a) == [comunicazioni.ISTRUZIONE_A]
    # B: graduatoria non su SOL
    b = [_riga("graduatoria", "mancante", ["la graduatoria non risulta tra i dati attualmente disponibili da Selezioni Online"])]
    assert comunicazioni.istruzioni_email(b) == [comunicazioni.ISTRUZIONE_B]
    # C: scorrimento
    c = [_riga("scorrimento", "mancante", ["il provvedimento ... non risulta ..."])]
    assert comunicazioni.istruzioni_email(c) == [comunicazioni.ISTRUZIONE_C]
    # tutti e tre, nell'ordine A, B, C
    tutti = a + b + c
    assert comunicazioni.istruzioni_email(tutti) == [comunicazioni.ISTRUZIONE_A, comunicazioni.ISTRUZIONE_B, comunicazioni.ISTRUZIONE_C]
    # graduatoria su SOL ma solo "protocollo diverso": nessuna istruzione sui punteggi
    assert comunicazioni.istruzioni_email([_riga("graduatoria", "presente", ["protocollo diverso: SOL 1, URP 2"])]) == []


def test_da_sbloccare():
    assert comunicazioni.da_sbloccare(_riga("graduatoria", "presente", ["protocollo della graduatoria pubblica (oscurata) non valorizzato sui candidati su SOL (2 candidati)"]))
    assert not comunicazioni.da_sbloccare(_riga("graduatoria", "presente", ["mancano i punteggi su SOL"]))
    assert not comunicazioni.da_sbloccare(_riga("scorrimento", "mancante", ["protocollo della graduatoria pubblica (oscurata) non valorizzato sui candidati su SOL (2 candidati)"]))


def test_da_sbloccare_solo_se_la_graduatoria_e_su_sol():
    testo = ["protocollo della graduatoria pubblica (oscurata) non valorizzato sui candidati su SOL (13 candidati)"]
    assert comunicazioni.da_sbloccare(_riga("graduatoria", "presente", testo))
    assert not comunicazioni.da_sbloccare(_riga("graduatoria", "mancante", testo))
