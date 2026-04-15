import os
import secrets
from datetime import datetime, timedelta

import stripe
from flask import (
    Flask,
    request,
    jsonify,
    redirect,
    url_for,
    render_template_string,
)
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# =========================
# CONFIG
# =========================
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "cambia-esto")
database_url = os.getenv("DATABASE_URL", "sqlite:///licenses.db")

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Titan Pro Bot")
PRODUCT_PRICE_USD = int(os.getenv("PRODUCT_PRICE_USD", "97"))  # en dólares enteros
LICENSE_DURATION_DAYS = int(os.getenv("LICENSE_DURATION_DAYS", "30"))  # 0 = sin vencimiento

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# =========================
# MODELOS
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
    stripe_session_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    stripe_payment_status = db.Column(db.String(50), nullable=True)

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
            "stripe_session_id": self.stripe_session_id,
            "stripe_payment_status": self.stripe_payment_status,
        }


with app.app_context():
    db.create_all()

# =========================
# HELPERS
# =========================
def generate_license_key(prefix: str = "TITAN") -> str:
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


def create_license_from_paid_session(session_obj):
    """
    Crea una licencia solo una vez por Stripe session.
    """
    session_id = session_obj.get("id")
    if not session_id:
        return None

    existing = License.query.filter_by(stripe_session_id=session_id).first()
    if existing:
        return existing

    customer_email = session_obj.get("customer_details", {}).get("email") or session_obj.get("customer_email")
    customer_name = session_obj.get("customer_details", {}).get("name") or ""

    expires_at = None
    if LICENSE_DURATION_DAYS > 0:
        expires_at = datetime.utcnow() + timedelta(days=LICENSE_DURATION_DAYS)

    lic = License(
        license_key=generate_license_key("TITAN"),
        customer_name=customer_name,
        customer_email=customer_email,
        active=True,
        expires_at=expires_at,
        notes="Creada automáticamente por pago Stripe",
        stripe_session_id=session_id,
        stripe_payment_status=session_obj.get("payment_status", ""),
    )
    db.session.add(lic)
    db.session.commit()
    return lic

# =========================
# HTML
# =========================
BUY_TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>Comprar {{ product_name }}</title>
    <style>
        body { background:#0f1115; color:#fff; font-family:Arial,sans-serif; margin:0; padding:30px; }
        .box { max-width:700px; margin:auto; background:#181c23; border:1px solid #2a2f3a; border-radius:16px; padding:24px; }
        h1 { margin-top:0; }
        p { color:#d1d5db; }
        .price { font-size:36px; font-weight:700; margin:18px 0; color:#4ade80; }
        input { width:100%; padding:12px; border-radius:10px; border:1px solid #3a4250; background:#0f1115; color:#fff; margin-top:6px; margin-bottom:16px; }
        button { background:#16a34a; color:#fff; border:none; padding:14px 18px; border-radius:10px; cursor:pointer; font-size:16px; }
        .small { font-size:13px; color:#9ca3af; }
    </style>
</head>
<body>
    <div class="box">
        <h1>{{ product_name }}</h1>
        <p>Compra automática con tarjeta. Cuando el pago se complete, tu licencia se crea sola.</p>
        <div class="price">${{ price }}</div>
        <form method="post" action="/create-checkout-session">
            <label>Nombre</label>
            <input type="text" name="customer_name" placeholder="Tu nombre" required>

            <label>Email</label>
            <input type="email" name="customer_email" placeholder="tuemail@gmail.com" required>

            <button type="submit">Comprar ahora</button>
        </form>
        <p class="small">Después del pago verás tu licencia en pantalla.</p>
    </div>
</body>
</html>
"""

SUCCESS_TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>Pago completado</title>
    <style>
        body { background:#0f1115; color:#fff; font-family:Arial,sans-serif; margin:0; padding:30px; }
        .box { max-width:800px; margin:auto; background:#181c23; border:1px solid #2a2f3a; border-radius:16px; padding:24px; }
        code { background:#0b0d11; padding:8px 10px; border-radius:8px; display:inline-block; font-size:20px; }
        .ok { color:#4ade80; font-weight:700; }
        .warn { color:#fbbf24; }
    </style>
</head>
<body>
    <div class="box">
        <h1 class="ok">Pago completado</h1>

        {% if license %}
            <p>Tu licencia fue creada correctamente.</p>
            <p><strong>Licencia:</strong></p>
            <p><code>{{ license.license_key }}</code></p>
            <p><strong>Email:</strong> {{ license.customer_email or "" }}</p>
            <p><strong>Expira:</strong> {{ license.expires_at.strftime("%Y-%m-%d %H:%M") if license.expires_at else "Sin vencimiento" }}</p>
        {% else %}
            <p class="warn">Tu pago fue aceptado, pero la licencia todavía no aparece.</p>
            <p>Recarga esta página en unos segundos.</p>
        {% endif %}
    </div>
</body>
</html>
"""

ADMIN_TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>Panel Admin</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0f1115;
            color: #f5f5f5;
            margin: 0;
            padding: 20px;
        }
        .wrap { max-width: 1200px; margin: auto; }
        .card {
            background: #181c23;
            border: 1px solid #2a2f3a;
            border-radius: 14px;
            padding: 18px;
            margin-bottom: 20px;
        }
        input, textarea {
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
        .btn.red { background: #b63737; }
        .btn.gray { background: #4b5563; }
        .btn.blue { background: #2563eb; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 14px; }
        th, td { border-bottom: 1px solid #2a2f3a; padding: 10px; text-align: left; vertical-align: top; }
        .status-on { color: #4ade80; font-weight: bold; }
        .status-off { color: #f87171; font-weight: bold; }
        code { background: #0b0d11; padding: 4px 6px; border-radius: 6px; }
    </style>
</head>
<body>
<div class="wrap">
    <div class="card">
        <h1>Panel Admin - Titan Pro</h1>
        <p>Total licencias: <strong>{{ total }}</strong></p>
        <p>Link de compra: <code>{{ base_url }}/buy</code></p>
    </div>

    <div class="card">
        <h2>Crear licencia manual</h2>
        <form method="post" action="/create-license">
            <input type="hidden" name="password" value="{{ password }}">
            <label>Nombre del cliente</label>
            <input type="text" name="customer_name">

            <label>Email del cliente</label>
            <input type="text" name="customer_email">

            <label>Días de duración (vacío = sin vencimiento)</label>
            <input type="number" name="days_valid" placeholder="30">

            <label>Notas</label>
            <textarea name="notes" rows="3"></textarea>

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
                    <th>Stripe Session</th>
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
                    <td>{{ lic.stripe_session_id or "" }}</td>
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
# RUTAS BÁSICAS
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


# =========================
# COMPRA AUTOMÁTICA
# =========================
@app.route("/buy")
def buy():
    return render_template_string(
        BUY_TEMPLATE,
        product_name=PRODUCT_NAME,
        price=PRODUCT_PRICE_USD
    )


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    if not STRIPE_SECRET_KEY:
        return "Falta STRIPE_SECRET_KEY en variables ambientales.", 500

    customer_name = (request.form.get("customer_name") or "").strip()
    customer_email = (request.form.get("customer_email") or "").strip()

    if not customer_email:
        return "Email requerido.", 400

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/buy",
            customer_email=customer_email,
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": PRODUCT_NAME,
                        },
                        "unit_amount": PRODUCT_PRICE_USD * 100,
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "customer_name": customer_name,
                "customer_email": customer_email,
                "product_name": PRODUCT_NAME,
            },
        )
        return redirect(session.url, code=303)
    except Exception as e:
        return f"Error creando checkout: {str(e)}", 500


@app.route("/success")
def success():
    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return "Falta session_id.", 400

    lic = License.query.filter_by(stripe_session_id=session_id).first()
    return render_template_string(SUCCESS_TEMPLATE, license=lic)


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    if not STRIPE_WEBHOOK_SECRET:
        return "Falta STRIPE_WEBHOOK_SECRET.", 500

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return "Payload inválido", 400
    except stripe.error.SignatureVerificationError:
        return "Firma inválida", 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        create_license_from_paid_session(session_obj)

    return jsonify({"received": True})


# =========================
# PANEL ADMIN
# =========================
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
        password=request.args.get("password", ""),
        base_url=BASE_URL,
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

    customer_name = (request.form.get("customer_name") or "").strip()
    customer_email = (request.form.get("customer_email") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    days_valid = (request.form.get("days_valid") or "").strip()

    expires_at = None
    if days_valid:
        try:
            days = int(days_valid)
            if days > 0:
                expires_at = datetime.utcnow() + timedelta(days=days)
        except ValueError:
            pass

    lic = License(
        license_key=generate_license_key("TITAN"),
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
# VALIDACIÓN PARA EL BOT
# =========================
@app.route("/validate", methods=["GET", "POST"])
def validate_license():
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
# INICIO
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
