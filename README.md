# manager-ufficio-reclutamento

## Avvio rapido
```
source .venv/bin/activate
pip install -r requirements.txt
python avvia_tool.py
```

## PyTorch 2.6 + YOLO checkpoint note
PyTorch 2.6+ può causare crash nel load dei checkpoint YOLO (default `weights_only=True`).
Questo progetto è testato con `torch==2.5.1`.

Fallback non predefinito (solo se ti fidi del checkpoint):
```
export PII_TORCH_UNSAFE_LOAD=1
```
