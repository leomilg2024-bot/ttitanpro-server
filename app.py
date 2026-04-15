
from flask import Flask, request, jsonify
import os
import json
import uuid
from datetime import datetime, timedelta

app = Flask(__name__)

LICENSE_FILE = "licenses.json"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "tititanpro_admin_2026")


def load_licenses():
    if not os.path.exists(LICENSE_FILE):
        return {}
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_licenses(data):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_license_key(plan="lifetime"):
    suffix = "L" if plan == "lifetime" else "M"
    return f"TITANPRO-{str(uuid.uuid4())[:8].upper()}-{suffix}"


@app.route("/")
def home():
    return "Servidor de licencias TitanPro funcionando 🔥"


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/admin/create-license", methods=["POST"])
def create_license():
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

    licenses = load_licenses()
    license_key = generate_license_key(plan)

    expires_at = None
    if plan == "monthly":
        expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()

    licenses[license_key] = {
        "email": email,
        "plan": plan,
        "status": "active",
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": expires_at
    }

    save_licenses(licenses)

    return jsonify({
        "ok": True,
        "license_key": license_key,
        "email": email,
        "plan": plan,
        "expires_at": expires_at
    })


@app.route("/admin/revoke-license", methods=["POST"])
def revoke_license():
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
    save_licenses(licenses)

    return jsonify({"ok": True, "license_key": license_key, "status": "revoked"})


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
            if datetime.utcnow() > expires_dt:
                lic["status"] = "expired"
                licenses[license_key] = lic
                save_licenses(licenses)

                return jsonify({
                    "valid": False,
                    "status": "expired",
                    "message": "Licencia expirada"
                })
        except:
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
