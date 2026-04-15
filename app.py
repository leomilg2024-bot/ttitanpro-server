
from flask import Flask, request, jsonify, redirect, Response
import os
import json
import uuid
from datetime import datetime, timedelta, timezone
import stripe

app = Flask(__name__)

# =========================
# CONFIG
# =========================
LICENSE_FILE = "licenses.json"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "tititanpro_admin_2026")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_LIFETIME = os.getenv("STRIPE_PRICE_LIFETIME", "")
BASE_URL = os.getenv("BASE_URL", "https://ttitanpro-server-1.onrender.com")

stripe.api_key = STRIPE_SECRET_KEY


# =========================
# HELPERS
# =========================
def now_utc():
    return datetime.now(timezone.utc)


def load_licenses():
    if not os.path.exists(LICENSE_FILE):
        return {}
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_licenses(data):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_license_key(plan="lifetime"):
    suffix = "L" if plan == "lifetime" else "M"
    return f"TITANPRO-{str(uuid.uuid4())[:8].upper()}-{suffix}"


def find_license_by_email(email):
    email = (email or "").strip().lower()
    licenses = load_licenses()
    for key, lic in licenses.items():
        if (lic.get("email") or "").strip().lower() == email and lic.get("status") == "active":
            return key, lic
    return None, None


def upsert_license_for_email(email, plan):
    email = (email or "").strip().lower()
    licenses = load_licenses()

    existing_key = None
    for key, lic in licenses.items():
        if (lic.get("email") or "").strip().lower() == email:
            existing_key = key
            break

    expires_at = None
    if plan == "monthly":
        expires_at = (now_utc() + timedelta(days=30)).isoformat()

    if existing_key:
        licenses[existing_key]["email"] = email
        licenses[existing_key]["plan"] = plan
        licenses[existing_key]["status"] = "active"
        licenses[existing_key]["updated_at"] = now_utc().isoformat()
        licenses[existing_key]["expires_at"] = expires_at
        save_licenses(licenses)
        return existing_key, licenses[existing_key]

    license_key = generate_license_key(plan)
    licenses[license_key] = {
        "email": email,
        "plan": plan,
        "status": "active",
        "created_at": now_utc().isoformat(),
        "updated_at": now_utc().isoformat(),
        "expires_at": expires_at
    }
    save_licenses(licenses)
    return license_key, licenses[license_key]


def revoke_license_by_email(email):
    email = (email or "").strip().lower()
    licenses = load_licenses()
    changed = False

    for key, lic in licenses.items():
        if (lic.get("email") or "").strip().lower() == email:
            lic["status"] = "revoked"
            lic["updated_at"] = now_utc().isoformat()
            changed = True

    if changed:
        save_licenses(licenses)
    return changed


# =========================
# WEB
# =========================
@app.route("/")
def home():
    html = f"""
    <html>
    <head>
        <title>TitanPro Licenses</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #0f1115;
                color: white;
                margin: 0;
                padding: 40px 20px;
            }}
            .wrap {{
                max-width: 900px;
                margin: 0 auto;
            }}
            .hero {{
                text-align: center;
                margin-bottom: 40px;
            }}
            .hero h1 {{
                font-size: 42px;
                margin-bottom: 10px;
                color: #f5c542;
            }}
            .hero p {{
                color: #c8c8c8;
                font-size: 18px;
            }}
            .box {{
                background: #171a21;
                border: 1px solid #2a2f3a;
                border-radius: 16px;
                padding: 24px;
                margin-bottom: 24px;
            }}
            input {{
                width: 100%;
                padding: 14px;
                border-radius: 10px;
                border: 1px solid #333;
                background: #0f1115;
                color: white;
                margin-bottom: 20px;
                font-size: 16px;
            }}
            .plans {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                gap: 20px;
            }}
            .plan {{
                background: #171a21;
                border: 1px solid #2a2f3a;
                border-radius: 16px;
                padding: 24px;
            }}
            .plan h2 {{
                margin-top: 0;
                color: #f5c542;
            }}
            .price {{
                font-size: 34px;
                font-weight: bold;
                margin: 12px 0 20px;
            }}
            button {{
                width: 100%;
                padding: 14px;
                border: none;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
            }}
            .monthly {{
                background: #1fb36a;
                color: white;
            }}
            .lifetime {{
                background: #f5c542;
                color: black;
            }}
            .note {{
                color: #b9b9b9;
                font-size: 14px;
                margin-top: 8px;
            }}
            .footer {{
                margin-top: 28px;
                color: #9d9d9d;
                font-size: 14px;
                text-align: center;
            }}
        </style>
        <script>
            async function buy(plan) {{
                const email = document.getElementById("email").value.trim();
                if (!email) {{
                    alert("Escribe tu correo primero.");
                    return;
                }}

                const res = await fetch("/create-checkout-session", {{
                    method: "POST",
                    headers: {{
                        "Content-Type": "application/json"
                    }},
                    body: JSON.stringify({{ email, plan }})
                }});

                const data = await res.json();

                if (!res.ok) {{
                    alert(data.error || "Error creando checkout.");
                    return;
                }}

                window.location.href = data.url;
            }}
        </script>
    </head>
    <body>
        <div class="wrap">
            <div class="hero">
                <h1>TitanPro</h1>
                <p>Compra automática de licencias para tu bot.</p>
            </div>

            <div class="box">
                <label for="email">Correo del cliente</label>
                <input id="email" type="email" placeholder="cliente@gmail.com" />
                <div class="note">La licencia quedará asociada a ese correo.</div>
            </div>

            <div class="plans">
                <div class="plan">
                    <h2>Mensual</h2>
                    <div class="price">$299</div>
                    <button class="monthly" onclick="buy('monthly')">Comprar mensual</button>
                </div>

                <div class="plan">
                    <h2>De por vida</h2>
                    <div class="price">$899</div>
                    <button class="lifetime" onclick="buy('lifetime')">Comprar lifetime</button>
                </div>
            </div>

            <div class="footer">
                El acceso se activa automáticamente después del pago.
            </div>
        </div>
    </body>
    </html>
    """
    return Response(html, mimetype="text/html")


@app.route("/success")
def success():
    return """
    <h2>Pago completado ✅</h2>
    <p>Tu licencia se está procesando automáticamente.</p>
    <p>Revisa tu correo o contáctame si no la ves reflejada todavía.</p>
    """


@app.route("/cancel")
def cancel():
    return """
    <h2>Pago cancelado</h2>
    <p>No se completó la compra.</p>
    """


@app.route("/health")
def health():
    return jsonify({"ok": True})


# =========================
# STRIPE CHECKOUT
# =========================
@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Falta STRIPE_SECRET_KEY"}), 500

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    plan = (data.get("plan") or "").strip().lower()

    if not email:
        return jsonify({"error": "email requerido"}), 400

    if plan not in ["monthly", "lifetime"]:
        return jsonify({"error": "plan inválido"}), 400

    try:
        if plan == "monthly":
            if not STRIPE_PRICE_MONTHLY:
                return jsonify({"error": "Falta STRIPE_PRICE_MONTHLY"}), 500

            session = stripe.checkout.Session.create(
                mode="subscription",
                customer_email=email,
                line_items=[{"price": STRIPE_PRICE_MONTHLY, "quantity": 1}],
                success_url=f"{BASE_URL}/success",
                cancel_url=f"{BASE_URL}/cancel",
                metadata={
                    "email": email,
                    "plan": "monthly"
                }
            )
        else:
            if not STRIPE_PRICE_LIFETIME:
                return jsonify({"error": "Falta STRIPE_PRICE_LIFETIME"}), 500

            session = stripe.checkout.Session.create(
                mode="payment",
                customer_email=email,
                line_items=[{"price": STRIPE_PRICE_LIFETIME, "quantity": 1}],
                success_url=f"{BASE_URL}/success",
                cancel_url=f"{BASE_URL}/cancel",
                metadata={
                    "email": email,
                    "plan": "lifetime"
                }
            )

        return jsonify({"url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# STRIPE WEBHOOK
# =========================
@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "Falta STRIPE_WEBHOOK_SECRET"}), 500

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return jsonify({"error": "Payload inválido"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Firma inválida"}), 400

    event_type = event["type"]
    obj = event["data"]["object"]

    try:
        if event_type == "checkout.session.completed":
            email = None
            plan = None

            metadata = obj.get("metadata", {}) or {}
            email = (metadata.get("email") or obj.get("customer_details", {}).get("email") or "").strip().lower()
            plan = (metadata.get("plan") or "").strip().lower()

            if email and plan in ["monthly", "lifetime"]:
                upsert_license_for_email(email, plan)

        elif event_type == "invoice.paid":
            customer_email = ""
            subscription = obj.get("subscription")

            if subscription:
                # Renovación de mensual
                customer_email = (obj.get("customer_email") or "").strip().lower()
                if customer_email:
                    upsert_license_for_email(customer_email, "monthly")

        elif event_type in ["customer.subscription.deleted", "customer.subscription.updated"]:
            status = obj.get("status", "")
            customer_id = obj.get("customer", "")

            # Buscar email del customer si se canceló o quedó incompleto
            if status in ["canceled", "unpaid", "incomplete_expired"]:
                customer = stripe.Customer.retrieve(customer_id)
                email = (customer.get("email") or "").strip().lower()
                if email:
                    revoke_license_by_email(email)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"received": True})


# =========================
# ADMIN
# =========================
@app.route("/admin/create-license", methods=["POST"])
def admin_create_license():
    token = request.headers.get("X-Admin-Token", "")
    if token != ADMIN_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    plan = (data.get("plan") or "lifetime").strip().lower()

    if not email:
        return jsonify({"error": "email requerido"}), 400

    if plan not in ["lifetime", "monthly"]:
        return jsonify({"error": "plan inválido"}), 400

    key, lic = upsert_license_for_email(email, plan)

    return jsonify({
        "ok": True,
        "license_key": key,
        "email": email,
        "plan": plan,
        "expires_at": lic.get("expires_at")
    })


@app.route("/admin/revoke-license", methods=["POST"])
def admin_revoke_license():
    token = request.headers.get("X-Admin-Token", "")
    if token != ADMIN_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    license_key = (data.get("license_key") or "").strip()

    if not license_key:
        return jsonify({"error": "license_key requerido"}), 400

    licenses = load_licenses()
    if license_key not in licenses:
        return jsonify({"error": "licencia no encontrada"}), 404

    licenses[license_key]["status"] = "revoked"
    licenses[license_key]["updated_at"] = now_utc().isoformat()
    save_licenses(licenses)

    return jsonify({"ok": True, "license_key": license_key, "status": "revoked"})


# =========================
# BOT VALIDATION
# =========================
@app.route("/api/validate")
def validate_license():
    license_key = (request.args.get("key") or "").strip()

    if not license_key:
        return jsonify({
            "valid": False,
            "status": "missing_key",
            "message": "Falta license key"
        }), 400

    licenses = load_licenses()
    lic = licenses.get(license_key)

    if not lic:
        return jsonify({
            "valid": False,
            "status": "not_found",
            "message": "Licencia no encontrada"
        })

    if lic.get("status") != "active":
        return jsonify({
            "valid": False,
            "status": lic.get("status"),
            "message": "Licencia inactiva"
        })

    if lic.get("plan") == "monthly":
        expires_at = lic.get("expires_at")
        if not expires_at:
            return jsonify({
                "valid": False,
                "status": "misconfigured",
                "message": "Licencia mensual mal configurada"
            })

        try:
            expires_dt = datetime.fromisoformat(expires_at)
            if now_utc() > expires_dt:
                lic["status"] = "expired"
                lic["updated_at"] = now_utc().isoformat()
                licenses[license_key] = lic
                save_licenses(licenses)

                return jsonify({
                    "valid": False,
                    "status": "expired",
                    "message": "Licencia expirada"
                })
        except Exception:
            return jsonify({
                "valid": False,
                "status": "error",
                "message": "Error leyendo expiración"
            })

    return jsonify({
        "valid": True,
        "status": "active",
        "plan": lic.get("plan"),
        "email": lic.get("email"),
        "expires_at": lic.get("expires_at")
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
