import http.server
import socketserver
import threading
import webbrowser
import time
import sys
import os
import subprocess

PORT = 8083
DIR = os.path.dirname(os.path.abspath(__file__))

def start_server():
    os.chdir(DIR)
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"[INFO] Server avviato su http://localhost:{PORT}")
        httpd.serve_forever()

def run_scraper(script_name, block=True):
    print(f"[INFO] Esecuzione script: {script_name}")
    try:
        if block:
            result = subprocess.run(["python3", script_name], check=True, capture_output=True, text=True)
            print(f"[SUCCESS] Completato: {script_name}")
            print(result.stdout)
        else:
            subprocess.Popen(["python3", script_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"[ERRORE] {script_name} fallito:\n{e.stderr}")
        sys.exit(1)

def wait_for_file(filepath, label):
    print(f"[INFO] Attesa file: {label}")
    while not os.path.exists(filepath):
        print(f"[ATTESA] In attesa di {label}...")
        time.sleep(2)
    print(f"[OK] File disponibile: {label}")

def monitor_sol_file():
    sol_file = os.path.join(DIR, "bandi-concorsi-pubblici-sol.json")
    while not os.path.exists(sol_file):
        time.sleep(2)
    print("✅ Dati da Selezioni Online scaricati. Puoi aggiornare la pagina per vedere i nuovi dati.")

def monitor_mobilita_file():
    mobilita_file = os.path.join(DIR, "bandi-mobilita.json")
    while not os.path.exists(mobilita_file):
        time.sleep(2)
    print("✅ Dati da Mobilità/Comandi scaricati. Puoi aggiornare la pagina per vedere i nuovi dati.")

def main():
    # Step 1: Scarica prima URP
    run_scraper("scraper-urp.py", block=True)
    wait_for_file("bandi-completi-urp.json", "URP")

    # Step 2: Avvia il server e apri la pagina
    threading.Thread(target=start_server, daemon=True).start()
    time.sleep(1)

    index_path = os.path.join(DIR, "index.html")
    if os.path.exists(index_path):
        webbrowser.open(f"http://localhost:{PORT}/index.html")
        print("[INFO] Pagina HTML aperta nel browser.")
    else:
        print(f"[ERRORE] Pagina HTML non trovata: {index_path}")

    # Step 3a: Selezioni Online (in background)
    run_scraper("scraper-sol-tutti-bandi.py", block=False)
    threading.Thread(target=monitor_sol_file, daemon=True).start()

    # Step 3b: Mobilità/Comandi (in background)
    run_scraper("scraper-mobilita.py", block=False)
    threading.Thread(target=monitor_mobilita_file, daemon=True).start()

    # Step 4: Mantieni il processo attivo
    print("[INFO] Server attivo. Premi Ctrl+C per uscire.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Server interrotto manualmente.")
        sys.exit(0)

if __name__ == "__main__":
    main()
