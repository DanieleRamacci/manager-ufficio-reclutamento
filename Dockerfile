FROM python:3.11-slim

WORKDIR /app

# dipendenze di sistema essenziali (se servono pikepdf/pdfminer ecc. aggiungile qui)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# requirements
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# codice applicazione (TUTTO, incluso avvia_tool.py)
COPY . /app

# variabili (solo esempio)
ENV PYTHONUNBUFFERED=1

EXPOSE 8081
CMD ["python", "avvia_tool.py"]
