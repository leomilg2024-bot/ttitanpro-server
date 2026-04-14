from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Servidor funcionando 🔥"

@app.route("/health")
def health():
    return {"ok": True}
