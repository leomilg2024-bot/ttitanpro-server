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
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")

database_url = os.getenv("DATABASE_URL", "sqlite:///licenses.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Leo Titan Pro")
PRODUCT_DESCRIPTION = os.getenv("PRODUCT_DESCRIPTION", "Bot profesional para NinjaTrader con licencia protegida")
LICENSE_PREFIX = os.getenv("LICENSE_PREFIX", "TITAN")
LICENSE_DURATION_DAYS = int(os.getenv("LICENSE_DURATION_DAYS", "30"))

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_LIFETIME = os.getenv("STRIPE_PRICE_LIFETIME", "")

stripe.api_key = STRIPE_SECRET_KEY

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Leo Titan Pro")

# =========================
# MODEL
# =========================
class License(db.Model):
    __tablename__ = "licenses"

    id = db.Column(db.Integer, primary_key=True)
    license_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    customer_name = db.Column(db.String(120), nullable=True)
    customer_email = db.Column(db.String(120), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    machine_id = db.Column(db.String(255), nullable=True)

    plan_type = db.Column(db.String(50), nullable=True)  # monthly / lifetime
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    stripe_session_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    stripe_customer_id = db.Column(db.String(255), nullable=True, index=True)
    stripe_subscription_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
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
            "plan_type": self.plan_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "expired": self.is_expired(),
            "notes": self.notes,
            "stripe_session_id": self.stripe_session_id,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
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
        return "<h2>Acceso denegado</h2><p>Password admin incorrecta o faltante.</p>", 401
    return None

def generate_license_key(prefix: str = "TITAN") -> str:
    parts = [
        secrets.token_hex(3).upper(),
        secrets.token_hex(3).upper(),
        secrets.token_hex(3).upper(),
    ]
    return f"{prefix}-" + "-".join(parts)

def send_license_email(to_email: str, customer_name: str, license_key: str, expires_at, plan_type: str):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD or not SMTP_FROM_EMAIL:
        print("SMTP no configurado. No se envió email.")
        return False, "SMTP no configurado"

    try:
        subject = f"Tu licencia de {PRODUCT_NAME}"
        expiry_text = expires_at.strftime("%Y-%m-%d %H:%M UTC") if expires_at else "Sin vencimiento"
        plan_text = "Mensual" if plan_type == "monthly" else "De por vida"

        html_body = f"""
        <html>
        <body style="font-family:Arial,sans-serif;background:#111;color:#fff;padding:20px;">
            <div style="max-width:700px;margin:auto;background:#1b1f27;border:1px solid #333;border-radius:16px;padding:24px;">
                <h1 style="color:#4ade80;">Pago completado</h1>
                <p>Hola {customer_name or 'cliente'},</p>
                <p>Gracias por tu compra de <strong>{PRODUCT_NAME}</strong>.</p>
                <p><strong>Plan:</strong> {plan_text}</p>
                <p>Tu licencia es:</p>
                <p style="font-size:22px;font-weight:bold;background:#0b0d11;padding:12px;border-radius:10px;display:inline-block;">
                    {license_key}
                </p>
                <p><strong>Expira:</strong> {expiry_text}</p>
                <p><strong>Servidor:</strong> {BASE_URL}</p>
                <p>Pega esta licencia en tu estrategia de NinjaTrader en el campo <strong>Licencia</strong>.</p>
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

def create_or_get_license_from_session(session_obj):
    """
    Crea licencia una sola vez por session de Stripe.
    """
    session_id = session_obj.get("id")
    if not session_id:
        return None

    existing = License.query.filter_by(stripe_session_id=session_id).first()
    if existing:
        return existing

    metadata = session_obj.get("metadata", {}) or {}

    customer_email = (
        session_obj.get("customer_details", {}).get("email")
        or session_obj.get("customer_email")
        or metadata.get("customer_email")
        or ""
    )

    customer_name = (
        metadata.get("customer_name")
        or session_obj.get("customer_details", {}).get("name")
        or ""
    )

    plan_type = metadata.get("plan_type", "lifetime")

    expires_at = None
    if plan_type == "monthly":
        # La licencia mensual vence en 30 días.
        # Luego puedes automatizar renovaciones si quieres.
        expires_at = datetime.utcnow() + timedelta(days=LICENSE_DURATION_DAYS)
    else:
        # Lifetime sin vencimiento
        expires_at = None

    lic = License(
        license_key=generate_license_key(LICENSE_PREFIX),
        customer_name=customer_name,
        customer_email=customer_email,
        active=True,
        machine_id=None,
        plan_type=plan_type,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
        notes="Creada automáticamente por Stripe",
        stripe_session_id=session_id,
        stripe_customer_id=session_obj.get("customer"),
        stripe_subscription_id=session_obj.get("subscription"),
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
            plan_type=lic.plan_type or "lifetime",
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
            max-width: 1000px;
            margin: auto;
        }
        .hero {
            background: linear-gradient(135deg, #151922, #1d2430);
            border: 1px solid #2e3645;
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,.3);
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
        .plan {
            border: 1px solid #364152;
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 14px;
            background: #10151c;
        }
        .plan h3 {
            margin: 0 0 8px 0;
        }
        .price {
            font-size: 28px;
            font-weight: bold;
            color: #4ade80;
            margin-bottom: 10px;
        }
        button {
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 12px;
            background: #16a34a;
            color: white;
            font-size: 17px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 10px;
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

                <label>Nombre</label>
                <input type="text" id="customer_name" placeholder="Tu nombre">

                <label>Email</label>
                <input type="email" id="customer_email" placeholder="tuemail@gmail.com">

                <div class="plan">
                    <h3>Plan mensual</h3>
                    <div class="price">{{ monthly_label }}</div>
                    <div class="small">Acceso mensual recurrente.</div>
                    <button onclick="buyPlan('monthly')">Comprar mensual</button>
                </div>

                <div class="plan">
                    <h3>Pago de por vida</h3>
                    <div class="price">{{ lifetime_label }}</div>
                    <div class="small">Un solo pago. Acceso permanente.</div>
                    <button onclick="buyPlan('lifetime')">Comprar de por vida</button>
                </div>

                <div class="small">
                    Después del pago, tu licencia se crea sola y también se manda a tu email.
                </div>
            </div>
        </div>
    </div>
</div>

<script>
async function buyPlan(plan) {
    const customer_name = document.getElementById("customer_name").value.trim();
    const customer_email = document.getElementById("customer_email").value.trim();

    if (!customer_email) {
        alert("Debes escribir tu email.");
        return;
    }

    const res = await fetch("/create-checkout-session", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            plan: plan,
            customer_name: customer_name,
            customer_email: customer_email
        })
    });

    const data = await res.json();

    if (data.url) {
        window.location = data.url;
    } else {
        alert(data.error || "No se pudo crear el checkout.");
    }
}
</script>
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
            <p><strong>Plan:</strong> {{ "Mensual" if license.plan_type == "monthly" else "De por vida" }}</p>
            <p><strong>Licencia:</strong></p>
            <p><code>{{ license.license_key }}</code></p>
            <p><strong>Email:</strong> {{ license.customer_email or "" }}</p>
            <p><strong>Expira:</strong> {{ license.expires_at.strftime("%Y-%m-%d %H:%M UTC") if license.expires_at else "Sin vencimiento" }}</p>
            <p><strong>Servidor:</strong> {{ base_url }}</p>
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
    <title>Panel Admin - {{ product_name }}</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0f1115;
            color: #f5f5f5;
            margin: 0;
            padding: 20px;
        }
        .wrap { max-width: 1300px; margin: auto; }
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
        <h2>Licencias</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Licencia</th>
                    <th>Plan</th>
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
                    <td>{{ lic.plan_type or "" }}</td>
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
# ROUTES
# =========================
@app.route("/")
def home():
    return jsonify({
        "ok": True,
        "message": "Leo Titan Pro license server funcionando",
        "time_utc": datetime.utcnow().isoformat()
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

@app.route("/buy")
def buy():
    monthly_label = "$199/mes"
    lifetime_label = "$297 único pago"
    return render_template_string(
        BUY_TEMPLATE,
        product_name=PRODUCT_NAME,
        product_description=PRODUCT_DESCRIPTION,
        monthly_label=monthly_label,
        lifetime_label=lifetime_label,
    )

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Falta STRIPE_SECRET_KEY"}), 500
    if not BASE_URL:
        return jsonify({"error": "Falta BASE_URL"}), 500

    data = request.get_json(silent=True) or {}
    customer_name = (data.get("customer_name") or "").strip()
    customer_email = (data.get("customer_email") or "").strip()
    plan = (data.get("plan") or "").strip().lower()

    if not customer_email:
        return jsonify({"error": "Email requerido"}), 400

    if plan not in ("monthly", "lifetime"):
        return jsonify({"error": "Plan inválido"}), 400

    if plan == "monthly":
        if not STRIPE_PRICE_MONTHLY:
            return jsonify({"error": "Falta STRIPE_PRICE_MONTHLY"}), 500
        price_id = STRIPE_PRICE_MONTHLY
        mode = "subscription"
    else:
        if not STRIPE_PRICE_LIFETIME:
            return jsonify({"error": "Falta STRIPE_PRICE_LIFETIME"}), 500
        price_id = STRIPE_PRICE_LIFETIME
        mode = "payment"

    try:
        session = stripe.checkout.Session.create(
            mode=mode,
            customer_email=customer_email,
            success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/buy",
            line_items=[{
                "price": price_id,
                "quantity": 1
            }],
            metadata={
                "customer_name": customer_name,
                "customer_email": customer_email,
                "plan_type": plan
            },
        )
        return jsonify({"url": session.url})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

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
        return "Falta STRIPE_WEBHOOK_SECRET.", 500

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return "Payload inválido", 400
    except stripe.error.SignatureVerificationError:
        return "Firma inválida", 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        create_or_get_license_from_session(session_obj)

    return jsonify({"received": True})

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
        product_name=PRODUCT_NAME
    )

@app.route("/licenses")
def list_licenses():
    denied = require_admin()
    if denied:
        return denied

    licenses = License.query.order_by(License.id.desc()).all()
    return jsonify([lic.to_dict() for lic in licenses])

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
        plan_type=lic.plan_type or "lifetime",
    )

    if sent:
        lic.email_sent = True
        db.session.commit()

    return redirect(url_for("admin_panel", password=request.args.get("password")))

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
        "plan_type": lic.plan_type,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else None
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
