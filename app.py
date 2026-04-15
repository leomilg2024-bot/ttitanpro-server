import os
import secrets
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# =========================
# CONFIGURACION
# =========================
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "cambia-esto-en-render")
database_url = os.getenv("DATABASE_URL", "sqlite:///licenses.db")

# Compatibilidad por si luego usas postgres en Render
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


# =========================
# MODELO DE LICENCIA
# =========================
class License(db.Model):
    __tablename__ = "licenses"

    id = db.Column(db.Integer, primary_key=True)
    license_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    customer_name = db.Column(db.String(120), nullable=True)
    customer_email = db.Column(db.String(120), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    machine_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    def is_expired(self) -> bool:
        return self.expires_at is not None and datetime.utcnow() > self.expires_at

    def to_dict(self):
        return {
            "id": self.id,
            "license_key": self.license_key,
            "customer_name": self.customer_name,
            "customer_email": self.customer_email,
            "active": self.active,
            "machine_id": self.machine_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "expired": self.is_expired(),
            "notes": self.notes,
        }


with app.app_context():
    db.create_all()


# =========================
# FUNCIONES AUXILIARES
# =========================
def generate_license_key(prefix: str = "TITAN") -> str:
    """
    Genera una licencia tipo:
    TITAN-AB12CD-34EFGH-7890JK
    """
    parts = [
        secrets.token_hex(3).upper(),
        secrets.token_hex(3).upper(),
        secrets.token_hex(3).upper(),
    ]
    return f"{prefix}-" + "-".join(parts)


def admin_ok() -> bool:
    return request.args.get("password") == ADMIN_PASSWORD or request.form.get("password") == ADMIN_PASSWORD


def require_admin():
    if not admin_ok():
        return (
            "<h2>Acceso denegado</h2><p>Password admin incorrecta o faltante.</p>",
            401,
        )
    return None


# =========================
# HTML SIMPLE DEL PANEL
# =========================
ADMIN_TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>Panel Admin - Titan Pro Licenses</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0f1115;
            color: #f5f5f5;
            margin: 0;
            padding: 20px;
        }
        .wrap {
            max-width: 1100px;
            margin: auto;
        }
        .card {
            background: #181c23;
            border: 1px solid #2a2f3a;
            border-radius: 14px;
            padding: 18px;
            margin-bottom: 20px;
        }
        h1, h2 {
            margin-top: 0;
        }
        input, textarea, select {
            width: 100%;
            padding: 10px;
            border-radius: 8px;
            border: 1px solid #3a4250;
            background: #0f1115;
            color: #fff;
            margin-top: 6px;
            margin-bottom: 12px;
        }
        button, .btn {
            background: #1f8f4e;
            color: white;
            border: none;
            padding: 10px 14px;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-right: 8px;
            margin-bottom: 6px;
        }
        .btn.red {
            background: #b63737;
        }
        .btn.gray {
            background: #4b5563;
        }
        .btn.blue {
            background: #2563eb;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            font-size: 14px;
        }
        th, td {
            border-bottom: 1px solid #2a2f3a;
            padding: 10px;
            text-align: left;
            vertical-align: top;
        }
        .status-on {
            color: #4ade80;
            font-weight: bold;
        }
        .status-off {
            color: #f87171;
            font-weight: bold;
        }
        .small {
            color: #b7c0cf;
            font-size: 13px;
        }
        code {
            background: #0b0d11;
            padding: 4px 6px;
            border-radius: 6px;
        }
    </style>
</head>
<body>
<div class="wrap">
    <div class="card">
        <h1>Panel Admin - Titan Pro Licenses</h1>
        <p class="small">Servidor activo. Total licencias: <strong>{{ total }}</strong></p>
        <p class="small">Para entrar aquí debes usar la URL con <code>?password=TU_PASSWORD</code></p>
    </div>

    <div class="card">
        <h2>Crear nueva licencia</h2>
        <form method="post" action="/create-license">
            <input type="hidden" name="password" value="{{ password }}">
            
            <label>Prefijo</label>
            <input type="text" name="prefix" value="TITAN">

            <label>Nombre del cliente</label>
            <input type="text" name="customer_name" placeholder="Ejemplo: Juan Perez">

            <label>Email del cliente</label>
            <input type="text" name="customer_email" placeholder="cliente@email.com">

            <label>Días de duración (vacío = sin vencimiento)</label>
            <input type="number" name="days_valid" placeholder="30">

            <label>Notas</label>
            <textarea name="notes" rows="3" placeholder="Notas internas"></textarea>

            <button type="submit">Crear licencia</button>
        </form>
    </div>

    <div class="card">
        <h2>Licencias</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Licencia</th>
                    <th>Cliente</th>
                    <th>Email</th>
                    <th>Estado</th>
                    <th>Machine ID</th>
                    <th>Creada</th>
                    <th>Expira</th>
                    <th>Acciones</th>
                </tr>
            </thead>
            <tbody>
                {% for lic in licenses %}
                <tr>
                    <td>{{ lic.id }}</td>
                    <td><code>{{ lic.license_key }}</code></td>
                    <td>{{ lic.customer_name or "" }}</td>
                    <td>{{ lic.customer_email or "" }}</td>
                    <td>
                        {% if lic.active and not lic.is_expired() %}
                            <span class="status-on">ACTIVA</span>
                        {% elif lic.is_expired() %}
                            <span class="status-off">VENCIDA</span>
                        {% else %}
                            <span class="status-off">DESACTIVADA</span>
                        {% endif %}
                    </td>
                    <td>{{ lic.machine_id or "" }}</td>
                    <td>{{ lic.created_at.strftime("%Y-%m-%d %H:%M") if lic.created_at else "" }}</td>
                    <td>{{ lic.expires_at.strftime("%Y-%m-%d %H:%M") if lic.expires_at else "Sin vencimiento" }}</td>
                    <td>
                        <a class="btn blue" href="/toggle-license/{{ lic.id }}?password={{ password }}">Activar/Desactivar</a>
                        <a class="btn gray" href="/clear-machine/{{ lic.id }}?password={{ password }}">Limpiar equipo</a>
                        <a class="btn red" href="/delete-license/{{ lic.id }}?password={{ password }}" onclick="return confirm('¿Eliminar esta licencia?');">Eliminar</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
</body>
</html>
"""


# =========================
# RUTAS PRINCIPALES
# =========================
@app.route("/")
def home():
    return jsonify({
        "ok": True,
        "message": "Titan Pro License Server funcionando",
        "time_utc": datetime.utcnow().isoformat()
    })


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


@app.route("/admin")
def admin_panel():
    denied = require_admin()
    if denied:
        return denied

    licenses = License.query.order_by(License.id.desc()).all()
    return render_template_string(
        ADMIN_TEMPLATE,
        licenses=licenses,
        total=len(licenses),
        password=request.args.get("password", "")
    )


@app.route("/licenses")
def list_licenses():
    denied = require_admin()
    if denied:
        return denied

    licenses = License.query.order_by(License.id.desc()).all()
    return jsonify([lic.to_dict() for lic in licenses])


@app.route("/create-license", methods=["POST"])
def create_license():
    denied = require_admin()
    if denied:
        return denied

    prefix = (request.form.get("prefix") or "TITAN").strip().upper()
    customer_name = (request.form.get("customer_name") or "").strip()
    customer_email = (request.form.get("customer_email") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    days_valid = (request.form.get("days_valid") or "").strip()

    license_key = generate_license_key(prefix=prefix)

    expires_at = None
    if days_valid:
        try:
            days = int(days_valid)
            if days > 0:
                expires_at = datetime.utcnow() + timedelta(days=days)
        except ValueError:
            pass

    lic = License(
        license_key=license_key,
        customer_name=customer_name,
        customer_email=customer_email,
        active=True,
        expires_at=expires_at,
        notes=notes
    )

    db.session.add(lic)
    db.session.commit()

    return redirect(url_for("admin_panel", password=request.form.get("password")))


@app.route("/toggle-license/<int:license_id>")
def toggle_license(license_id):
    denied = require_admin()
    if denied:
        return denied

    lic = License.query.get_or_404(license_id)
    lic.active = not lic.active
    db.session.commit()

    return redirect(url_for("admin_panel", password=request.args.get("password")))


@app.route("/clear-machine/<int:license_id>")
def clear_machine(license_id):
    denied = require_admin()
    if denied:
        return denied

    lic = License.query.get_or_404(license_id)
    lic.machine_id = None
    db.session.commit()

    return redirect(url_for("admin_panel", password=request.args.get("password")))


@app.route("/delete-license/<int:license_id>")
def delete_license(license_id):
    denied = require_admin()
    if denied:
        return denied

    lic = License.query.get_or_404(license_id)
    db.session.delete(lic)
    db.session.commit()

    return redirect(url_for("admin_panel", password=request.args.get("password")))


# =========================
# VALIDACION PARA EL BOT
# =========================
@app.route("/validate", methods=["GET", "POST"])
def validate_license():
    """
    Tu bot puede enviar:
    - key: licencia
    - machine_id: id unico de la PC (opcional al principio, recomendado)
    
    Respuesta:
    {
      "status": "valid" / "invalid",
      "message": "...",
      ...
    }
    """
    license_key = (request.values.get("key") or "").strip().upper()
    machine_id = (request.values.get("machine_id") or "").strip()

    if not license_key:
        return jsonify({
            "status": "invalid",
            "message": "Falta la licencia"
        }), 400

    lic = License.query.filter_by(license_key=license_key).first()

    if not lic:
        return jsonify({
            "status": "invalid",
            "message": "Licencia no encontrada"
        }), 404

    if not lic.active:
        return jsonify({
            "status": "invalid",
            "message": "Licencia desactivada"
        }), 403

    if lic.is_expired():
        return jsonify({
            "status": "invalid",
            "message": "Licencia vencida"
        }), 403

    # Bloqueo opcional por equipo:
    # - Si la licencia no tiene machine_id guardado, guarda el primero que llegue
    # - Si ya tiene uno, solo valida si coincide
    if machine_id:
        if lic.machine_id is None:
            lic.machine_id = machine_id
            db.session.commit()
        elif lic.machine_id != machine_id:
            return jsonify({
                "status": "invalid",
                "message": "Licencia usada en otro equipo"
            }), 403

    return jsonify({
        "status": "valid",
        "message": "Licencia válida",
        "license_key": lic.license_key,
        "customer_name": lic.customer_name,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else None
    })


# =========================
# CREAR LICENCIA POR API
# =========================
@app.route("/api/create-license", methods=["POST"])
def api_create_license():
    """
    Esta ruta es opcional.
    Sirve si luego quieres crear licencias desde otra app.
    Debes enviar admin_password.
    """
    admin_password = request.values.get("admin_password", "")
    if admin_password != ADMIN_PASSWORD:
        return jsonify({"ok": False, "message": "No autorizado"}), 401

    prefix = (request.values.get("prefix") or "TITAN").strip().upper()
    customer_name = (request.values.get("customer_name") or "").strip()
    customer_email = (request.values.get("customer_email") or "").strip()
    notes = (request.values.get("notes") or "").strip()
    days_valid = (request.values.get("days_valid") or "").strip()

    license_key = generate_license_key(prefix=prefix)

    expires_at = None
    if days_valid:
        try:
            days = int(days_valid)
            if days > 0:
                expires_at = datetime.utcnow() + timedelta(days=days)
        except ValueError:
            return jsonify({"ok": False, "message": "days_valid inválido"}), 400

    lic = License(
        license_key=license_key,
        customer_name=customer_name,
        customer_email=customer_email,
        active=True,
        expires_at=expires_at,
        notes=notes
    )
    db.session.add(lic)
    db.session.commit()

    return jsonify({
        "ok": True,
        "message": "Licencia creada",
        "license": lic.to_dict()
    })


# =========================
# INICIO
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
