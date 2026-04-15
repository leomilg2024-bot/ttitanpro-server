import os
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

import stripe
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# =========================
# CONFIG
# =========================
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "cambia-esto-en-render")

database_url = os.getenv("DATABASE_URL", "sqlite:///licenses.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
BASE_URL = os.getenv("BASE_URL", "https://ttitanpro-server-1.onrender.com").rstrip("/")

PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Leo Titan Pro")
PRODUCT_DESCRIPTION = os.getenv("PRODUCT_DESCRIPTION", "Bot profesional para NinjaTrader con licencia protegida")
PRODUCT_PRICE_USD = int(os.getenv("PRODUCT_PRICE_USD", "97"))
LICENSE_DURATION_DAYS = int(os.getenv("LICENSE_DURATION_DAYS", "30"))
LICENSE_PREFIX = os.getenv("LICENSE_PREFIX", "TITAN")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
stripe.api_key = STRIPE_SECRET_KEY

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Leo Titan Pro")

# =========================
# MODELO
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
    stripe_payment_intent = db.Column(db.String(255), nullable=True)
    stripe_payment_status = db.Column(db.String(50), nullable=True)

    email_sent = db.Column(db.Boolean, default=False, nullable=False)

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
            "stripe_payment_intent": self.stripe_payment_intent,
            "stripe_payment_status": self.stripe_payment_status,
            "email_sent": self.email_sent,
        }


with app.app_context():
    db.create_all()

# =========================
# HELPERS
# =========================
def admin_ok() -> bool:
    return request.args.get("password") == ADMIN_PASSWORD or request.form.get("password") == ADMIN_PASSWORD

def require_admin():
    if not admin_ok():
        return (
            "<h2>Acceso denegado</h2><p>Password admin incorrecta o faltante.</p>",
            401,
        )
    return None

def generate_license_key(prefix: str = "TITAN") -> str:
    parts = [
        secrets.token_hex(3).upper(),
        secrets.token_hex(3).upper(),
        secrets.token_hex(3).upper(),
    ]
    return f"{prefix}-" + "-".join(parts)

def send_license_email(to_email: str, customer_name: str, license_key: str, expires_at):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD or not SMTP_FROM_EMAIL:
        print("SMTP no configurado. No se envió email.")
        return False, "SMTP no configurado"

    try:
        subject = f"Tu licencia de {PRODUCT_NAME}"
        expiry_text = expires_at.strftime("%Y-%m-%d %H:%M UTC") if expires_at else "Sin vencimiento"

        html_body = f"""
        <html>
        <body style="font-family:Arial,sans-serif;background:#111;color:#fff;padding:20px;">
            <div style="max-width:700px;margin:auto;background:#1b1f27;border:1px solid #333;border-radius:16px;padding:24px;">
                <h1 style="color:#4ade80;">Pago completado</h1>
                <p>Hola {customer_name or 'cliente'},</p>
                <p>Gracias por tu compra de <strong>{PRODUCT_NAME}</strong>.</p>
                <p>Tu licencia es:</p>
                <p style="font-size:22px;font-weight:bold;background:#0b0d11;padding:12px;border-radius:10px;display:inline-block;">
                    {license_key}
                </p>
                <p><strong>Expira:</strong> {expiry_text}</p>
                <p><strong>Servidor:</strong> {BASE_URL}</p>
                <p>En NinjaTrader, pega la licencia en el campo <strong>Licencia</strong> y deja la URL del servidor en:</p>
                <p style="font-size:18px;background:#0b0d11;padding:10px;border-radius:10px;display:inline-block;">
                    {BASE_URL}
                </p>
                <hr style="border-color:#333;margin:24px 0;">
                <p style="color:#bbb;">No compartas esta licencia. Si se usa en otro equipo, puede bloquearse.</p>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = to_email

        msg.attach(MIMEText(html_body, "html"))

        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())
        server.quit()

        return True, "Email enviado"
    except Exception as ex:
        print(f"ERROR enviando email: {ex}")
        return False, str(ex)

def create_license_from_session(session_obj):
    session_id = session_obj.get("id")
    if not session_id:
        return None

    existing = License.query.filter_by(stripe_session_id=session_id).first()
    if existing:
        return existing

    customer_email = (
        session_obj.get("customer_details", {}).get("email")
        or session_obj.get("customer_email")
        or ""
    )

    customer_name = (
        session_obj.get("metadata", {}).get("customer_name")
        or session_obj.get("customer_details", {}).get("name")
        or ""
    )

    expires_at = None
    if LICENSE_DURATION_DAYS > 0:
        expires_at = datetime.utcnow() + timedelta(days=LICENSE_DURATION_DAYS)

    lic = License(
        license_key=generate_license_key(LICENSE_PREFIX),
        customer_name=customer_name,
        customer_email=customer_email,
        active=True,
        machine_id=None,
        expires_at=expires_at,
        notes="Creada automáticamente por Stripe",
        stripe_session_id=session_id,
        stripe_payment_intent=session_obj.get("payment_intent"),
        stripe_payment_status=session_obj.get("payment_status", ""),
        email_sent=False,
    )

    db.session.add(lic)
    db.session.commit()

    if customer_email:
        sent, _ = send_license_email(
            to_email=customer_email,
            customer_name=customer_name,
            license_key=lic.license_key,
            expires_at=lic.expires_at,
        )
        if sent:
            lic.email_sent = True
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
    <title>{{ product_name }}</title>
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #0f1115;
            color: white;
            padding: 30px;
        }
        .wrap {
            max-width: 900px;
            margin: auto;
        }
        .hero {
            background: linear-gradient(135deg, #151922, #1d2430);
            border: 1px solid #2e3645;
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,.3);
        }
        .price {
            font-size: 42px;
            font-weight: bold;
            color: #4ade80;
            margin: 20px 0;
        }
        .subtitle {
            color: #cbd5e1;
            line-height: 1.6;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 24px;
        }
        .card {
            background: #171b22;
            border: 1px solid #2e3645;
            border-radius: 16px;
            padding: 20px;
        }
        input {
            width: 100%;
            padding: 14px;
            border-radius: 10px;
            border: 1px solid #364152;
            background: #0f1115;
            color: white;
            margin-top: 8px;
            margin-bottom: 16px;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            padding: 16px;
            border: none;
            border-radius: 12px;
            background: #16a34a;
            color: white;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
        }
        ul {
            color: #cbd5e1;
            line-height: 1.8;
            padding-left: 18px;
        }
        .small {
            color: #9ca3af;
            font-size: 13px;
            margin-top: 12px;
        }
        @media (max-width: 800px) {
            .grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
<div class="wrap">
    <div class="hero">
        <h1>{{ product_name }}</h1>
        <p class="subtitle">{{ product_description }}</p>
        <div class="price">${{ price }}</div>
        <div class="grid">
            <div class="card">
                <h2>Qué incluye</h2>
                <ul>
                    <li>Licencia original</li>
                    <li>Bloqueo por equipo</li>
                    <li>Validación automática</li>
                    <li>Entrega inmediata por email</li>
                    <li>Acceso al servidor de licencias</li>
                </ul>
            </div>
            <div class="card">
                <h2>Comprar ahora</h2>
                <form method="post" action="/create-checkout-session">
                    <label>Nombre</label>
                    <input type="text" name="customer_name" required>

                    <label>Email</label>
                    <input type="email" name="customer_email" required>

                    <button type="submit">Pagar con tarjeta</button>
                </form>
                <div class="small">
                    Después del pago, tu licencia se crea sola y también se manda a tu email.
                </div>
            </div>
        </div>
    </div>
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
        body { background:#0f1115; color:#fff; font-family:Arial,sans-serif; padding:30px; }
        .box { max-width:800px; margin:auto; background:#181c23; border:1px solid #2a2f3a; border-radius:16px; padding:24px; }
        code { background:#0b0d11; padding:10px 14px; border-radius:10px; display:inline-block; font-size:20px; }
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
            <p><strong>Expira:</strong> {{ license.expires_at.strftime("%Y-%m-%d %H:%M UTC") if license.expires_at else "Sin vencimiento" }}</p>
            <p><strong>Servidor:</strong> {{ base_url }}</p>
            <p>También se envió a tu correo si el SMTP está configurado.</p>
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
    <title>Panel Admin - Titan Pro</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0f1115;
            color: #f5f5f5;
            margin: 0;
            padding: 20px;
        }
        .wrap {
            max-width: 1250px;
            margin: auto;
        }
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
            box-sizing: border-box;
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
        .btn.orange { background: #d97706; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 14px; }
        th, td { border-bottom: 1px solid #2a2f3a; padding: 10px; text-align: left; vertical-align: top; }
        .status-on { color: #4ade80; font-weight: bold; }
        .status-off { color: #f87171; font-weight: bold; }
        code { background: #0b0d11; padding: 4px 6px; border-radius: 6px; }
        .muted { color: #aab2bf; }
    </style>
</head>
<body>
<div class="wrap">
    <div class="card">
        <h1>Panel Admin - {{ product_name }}</h1>
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
                    <th>Email</th>
                    <th>Stripe</th>
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
                    <td>{{ "Enviado" if lic.email_sent else "Pendiente" }}</td>
                    <td>{{ lic.stripe_payment_status or "" }}</td>
                    <td>
                        <a class="btn blue" href="/toggle-license/{{ lic.id }}?password={{ password }}">Activar/Desactivar</a>
                        <a class="btn gray" href="/clear-machine/{{ lic.id }}?password={{ password }}">Limpiar equipo</a>
                        <a class="btn orange" href="/resend-email/{{ lic.id }}?password={{ password }}">Reenviar email</a>
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
# RUTAS BASICAS
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
# PAGINA DE COMPRA
# =========================
@app.route("/buy")
def buy():
    return render_template_string(
        BUY_TEMPLATE,
        product_name=PRODUCT_NAME,
        product_description=PRODUCT_DESCRIPTION,
        price=PRODUCT_PRICE_USD
    )

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    if not STRIPE_SECRET_KEY:
        return "Falta STRIPE_SECRET_KEY en Render.", 500

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
                            "description": PRODUCT_DESCRIPTION,
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
    except Exception as ex:
        return f"Error creando checkout: {str(ex)}", 500

@app.route("/success")
def success():
    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return "Falta session_id.", 400

    lic = License.query.filter_by(stripe_session_id=session_id).first()
    return render_template_string(
        SUCCESS_TEMPLATE,
        license=lic,
        base_url=BASE_URL
    )

@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    if not STRIPE_WEBHOOK_SECRET:
        return "Falta STRIPE_WEBHOOK_SECRET en Render.", 500

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
        create_license_from_session(session_obj)

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
        product_name=PRODUCT_NAME,
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
        license_key=generate_license_key(LICENSE_PREFIX),
        customer_name=customer_name,
        customer_email=customer_email,
        active=True,
        expires_at=expires_at,
        notes=notes,
        email_sent=False
    )

    db.session.add(lic)
    db.session.commit()

    if customer_email:
        sent, _ = send_license_email(customer_email, customer_name, lic.license_key, lic.expires_at)
        if sent:
            lic.email_sent = True
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

@app.route("/resend-email/<int:license_id>")
def resend_email(license_id):
    denied = require_admin()
    if denied:
        return denied

    lic = License.query.get_or_404(license_id)

    if not lic.customer_email:
        return redirect(url_for("admin_panel", password=request.args.get("password")))

    sent, _ = send_license_email(
        to_email=lic.customer_email,
        customer_name=lic.customer_name or "",
        license_key=lic.license_key,
        expires_at=lic.expires_at,
    )

    if sent:
        lic.email_sent = True
        db.session.commit()

    return redirect(url_for("admin_panel", password=request.args.get("password")))

# =========================
# VALIDACION PARA BOT
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

    # Bloqueo por equipo
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
# API OPCIONAL
# =========================
@app.route("/api/create-license", methods=["POST"])
def api_create_license():
    admin_password = request.values.get("admin_password", "")
    if admin_password != ADMIN_PASSWORD:
        return jsonify({"ok": False, "message": "No autorizado"}), 401

    customer_name = (request.values.get("customer_name") or "").strip()
    customer_email = (request.values.get("customer_email") or "").strip()
    notes = (request.values.get("notes") or "").strip()
    days_valid = (request.values.get("days_valid") or "").strip()

    expires_at = None
    if days_valid:
        try:
            days = int(days_valid)
            if days > 0:
                expires_at = datetime.utcnow() + timedelta(days=days)
        except ValueError:
            return jsonify({"ok": False, "message": "days_valid inválido"}), 400

    lic = License(
        license_key=generate_license_key(LICENSE_PREFIX),
        customer_name=customer_name,
        customer_email=customer_email,
        active=True,
        expires_at=expires_at,
        notes=notes,
    )
    db.session.add(lic)
    db.session.commit()

    return jsonify({
        "ok": True,
        "message": "Licencia creada",
        "license": lic.to_dict()
    })

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
