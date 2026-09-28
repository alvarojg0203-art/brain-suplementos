"""
BrainSuplementos — servidor Flask
Sirve la web pública (index.html + static/), expone una API que lee y
escribe en MySQL (productos, clientes, pedidos), y un panel de
administración en /admin con usuarios propios (no una sola contraseña
fija): la primera vez que se entra, pide crear la cuenta del
administrador (nombre, mail, usuario, contraseña, pregunta de
seguridad). Después se loguea normal, y si se olvida la contraseña
la puede recuperar respondiendo esa pregunta.

Cómo correrlo (ver README.md para el detalle):
    pip install -r requirements.txt
    copiar .env.example a .env y completar los datos de tu MySQL
    python app.py
Después abrís http://localhost:5000 (web pública) o
http://localhost:5000/admin (panel de administración).
"""

import json
import os
import re
import secrets
import smtplib
import time
import uuid
from datetime import datetime, timedelta, date
from datetime import time as dt_time
from decimal import Decimal
from email.mime.text import MIMEText
from functools import wraps
from io import BytesIO

import mercadopago
import mysql.connector
from mysql.connector import Error as MySQLError
from dotenv import load_dotenv
from flask import (
    Flask, jsonify, request, send_from_directory,
    render_template, redirect, url_for, session, flash, Response, send_file
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from authlib.jose import jwt as jose_jwt

load_dotenv()

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY", "cambia-esta-clave-en-produccion")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "brainsuplementos"),
    "charset": "utf8mb4",  # para que tildes, ñ y emojis (íconos de categoría) siempre viajen bien
}

UPLOAD_FOLDER = os.path.join("static", "img")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =============================================================
# LOGIN SOCIAL: Google y Apple (opcional — solo se activa si
# están completas las variables correspondientes en .env)
# =============================================================
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID")        # Services ID, ej: com.brainsuplementos.web
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID")
APPLE_PRIVATE_KEY = os.getenv("APPLE_PRIVATE_KEY")     # contenido del archivo .p8 de Apple

oauth = OAuth(app)


# =============================================================
# ENVÍO DE MAILS (opcional — para "olvidé mi contraseña" de clientes)
# =============================================================
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER

# A partir de cuántas unidades o menos se le avisa a la dueña por mail que
# un producto/variante se está por agotar (mismo umbral que el "¡Últimas
# unidades!" que ve el cliente en la tienda — ver LOW_STOCK_THRESHOLD en caro.js).
LOW_STOCK_THRESHOLD = 3


def smtp_configured():
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def send_email(to_address, subject, body):
    """Manda un mail de texto plano por SMTP. Devuelve True/False según si
    se pudo enviar (nunca tira una excepción hacia afuera)."""
    if not smtp_configured():
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_address
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_address], msg.as_string())
        return True
    except Exception as e:
        app.logger.error(f"No se pudo enviar el mail: {e}")
        return False


# =============================================================
# COBRO ONLINE: Mercado Pago Checkout Pro (opcional — si no está
# configurado, el pago con Mercado Pago se degrada a "avisamos por
# WhatsApp" como los otros métodos, sin romper el resto de la compra)
# =============================================================
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
MP_PUBLIC_KEY = os.getenv("MP_PUBLIC_KEY")  # clave pública, se manda al navegador (no es secreta)

mp_sdk = mercadopago.SDK(MP_ACCESS_TOKEN) if MP_ACCESS_TOKEN else None


def mp_configured():
    return bool(MP_ACCESS_TOKEN)


def mp_card_form_configured():
    """El formulario de tarjeta embebido (Payment Brick) además del access
    token necesita la Public Key, que es la que se manda al navegador."""
    return bool(MP_ACCESS_TOKEN and MP_PUBLIC_KEY)


def crear_preferencia_mp(order_id, items, total):
    """Crea una preferencia de pago en Mercado Pago para un pedido ya
    guardado y devuelve la URL de checkout (init_point), o None si Mercado
    Pago no está configurado o si falla la llamada a la API.

    Usamos un solo ítem con el total ya calculado por el servidor (con
    cupón y envío incluidos) en vez de un ítem por producto: así el monto
    que termina cobrando Mercado Pago siempre coincide con `total`, sin
    importar si hay descuento de cupón o costo de envío de por medio
    (si se armara un ítem por producto con su precio de catálogo, ese
    descuento/envío quedaría afuera de lo que Mercado Pago cobra)."""
    if not mp_configured():
        return None
    try:
        preference_data = {
            "items": [
                {
                    "title": f"Pedido #{order_id} - BrainSuplementos",
                    "quantity": 1,
                    "unit_price": float(total),
                    "currency_id": "ARS",
                }
            ],
            "external_reference": str(order_id),
            "back_urls": {
                "success": url_for("pago_exito", order_id=order_id, _external=True),
                "pending": url_for("pago_pendiente", order_id=order_id, _external=True),
                "failure": url_for("pago_error", order_id=order_id, _external=True),
            },
            "auto_return": "approved",
            "notification_url": url_for("mercadopago_webhook", _external=True),
        }
        result = mp_sdk.preference().create(preference_data)
        response = result.get("response", {})
        preference_id = response.get("id")
        if preference_id:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE orders SET mp_preference_id = %s WHERE id = %s",
                (preference_id, order_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
        return response.get("init_point")
    except Exception as e:
        app.logger.error(f"No se pudo crear la preferencia de Mercado Pago: {e}")
        return None


def google_configured():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def apple_configured():
    return bool(APPLE_CLIENT_ID and APPLE_TEAM_ID and APPLE_KEY_ID and APPLE_PRIVATE_KEY)


if google_configured():
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def generate_apple_client_secret():
    """Apple no usa un client_secret fijo: pide un JWT firmado (ES256) con la
    private key que se descarga una sola vez desde Apple Developer. Se genera
    acá al arrancar el server; alcanza porque dura hasta 6 meses."""
    now = int(time.time())
    header = {"alg": "ES256", "kid": APPLE_KEY_ID}
    payload = {
        "iss": APPLE_TEAM_ID,
        "iat": now,
        "exp": now + 3600 * 24 * 30,  # 30 días
        "aud": "https://appleid.apple.com",
        "sub": APPLE_CLIENT_ID,
    }
    key = APPLE_PRIVATE_KEY.replace("\\n", "\n")
    token = jose_jwt.encode(header, payload, key)
    return token.decode("utf-8") if isinstance(token, bytes) else token


if apple_configured():
    oauth.register(
        name="apple",
        client_id=APPLE_CLIENT_ID,
        client_secret=generate_apple_client_secret(),
        server_metadata_url="https://appleid.apple.com/.well-known/openid-configuration",
        client_kwargs={"scope": "name email", "response_mode": "form_post"},
    )


def find_or_create_oauth_customer(provider, oauth_id, email, name):
    """Busca un cliente por su id de Google/Apple, o por email si ya se había
    registrado antes con contraseña, y si no existe lo crea."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM customers WHERE auth_provider = %s AND oauth_id = %s",
        (provider, oauth_id),
    )
    customer = cursor.fetchone()

    if not customer and email:
        cursor.execute("SELECT * FROM customers WHERE email = %s", (email,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                "UPDATE customers SET auth_provider = %s, oauth_id = %s WHERE id = %s",
                (provider, oauth_id, existing["id"]),
            )
            conn.commit()
            existing["auth_provider"] = provider
            existing["oauth_id"] = oauth_id
            customer = existing

    if not customer:
        cursor.execute(
            """INSERT INTO customers (name, email, auth_provider, oauth_id)
               VALUES (%s, %s, %s, %s)""",
            (name, email or None, provider, oauth_id),
        )
        conn.commit()
        customer = {"id": cursor.lastrowid, "name": name}

    cursor.close()
    conn.close()
    return customer


def get_connection():
    """Abre una conexión nueva a MySQL usando los datos de .env"""
    return mysql.connector.connect(**DB_CONFIG)


def to_float(value):
    """Convierte Decimal (que devuelve MySQL) a float para poder mandarlo como JSON"""
    return float(value) if isinstance(value, Decimal) else value


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(view):
    """Protege las rutas de /admin: si no hay sesión iniciada, manda al login.

    Además de mirar la sesión, confirma que ese admin siga existiendo en la
    base de datos. Esto evita que una cookie de sesión vieja (por ejemplo,
    de un admin que después se borró de la tabla `admins`) siga dando acceso
    al panel."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id:
            return redirect(url_for("admin_login"))
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM admins WHERE id = %s", (admin_id,))
        exists = cursor.fetchone()
        cursor.close()
        conn.close()
        if not exists:
            session.clear()
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def any_admin_exists():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM admins")
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return count > 0


# =============================================================
# WEB PÚBLICA
# =============================================================
@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/catalogo")
def catalogo_page():
    # Mismo archivo que la home: index.html decide con JS (según la URL)
    # si muestra el catálogo completo como página aparte o el resto de la
    # tienda, así no duplicamos el header, el carrito ni los modales.
    return send_from_directory(".", "index.html")


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.route("/terminos")
def terminos():
    return render_template("terminos.html")


@app.route("/cambios-y-devoluciones")
def cambios_y_devoluciones():
    return render_template("cambios.html")


@app.route("/privacidad")
def privacidad():
    return render_template("privacidad.html")


@app.route("/sitemap.xml")
def sitemap():
    base = request.url_root.rstrip("/")
    pages = [
        {"loc": f"{base}/", "priority": "1.0"},
        {"loc": f"{base}/terminos", "priority": "0.3"},
        {"loc": f"{base}/cambios-y-devoluciones", "priority": "0.3"},
        {"loc": f"{base}/privacidad", "priority": "0.3"},
    ]
    xml = render_template("sitemap.xml", pages=pages)
    return Response(xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots_txt():
    base = request.url_root.rstrip("/")
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /cuenta\n"
        "Disallow: /reset-password\n"
        f"\nSitemap: {base}/sitemap.xml\n"
    )
    return Response(content, mimetype="text/plain")


# =============================================================
# CUENTAS DE CLIENTE: para poder comprar hace falta estar
# registrada/o (mail y contraseña, Google o Apple).
# =============================================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("customer_id"):
        return redirect(request.args.get("next") or url_for("home"))

    next_url = request.args.get("next") or request.form.get("next") or ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not all([name, email, password]):
            flash("Completá nombre, email y contraseña")
        elif password != password2:
            flash("Las contraseñas no coinciden")
        elif len(password) < 6:
            flash("La contraseña tiene que tener al menos 6 caracteres")
        else:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO customers (name, email, phone, password_hash, auth_provider)
                       VALUES (%s, %s, %s, %s, 'local')""",
                    (name, email, phone or None, generate_password_hash(password)),
                )
                conn.commit()
                customer_id = cursor.lastrowid
                cursor.close()
                conn.close()

                session["customer_id"] = customer_id
                session["customer_name"] = name
                flash("¡Cuenta creada! Ya podés comprar.")
                return redirect(next_url or url_for("home"))
            except MySQLError as e:
                if "Duplicate" in str(e):
                    flash("Ya existe una cuenta con ese email. Probá iniciar sesión.")
                else:
                    flash(f"No se pudo crear la cuenta: {e}")

    return render_template("register.html", next=next_url)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("customer_id"):
        return redirect(request.args.get("next") or url_for("home"))

    next_url = request.args.get("next") or request.form.get("next") or ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM customers WHERE email = %s AND auth_provider = 'local'",
            (email,),
        )
        customer = cursor.fetchone()
        cursor.close()
        conn.close()

        if customer and customer["password_hash"] and check_password_hash(customer["password_hash"], password):
            session["customer_id"] = customer["id"]
            session["customer_name"] = customer["name"]
            return redirect(next_url or url_for("home"))
        flash("Email o contraseña incorrectos")

    return render_template(
        "login.html",
        next=next_url,
        google_enabled=google_configured(),
        apple_enabled=apple_configured(),
    )


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not smtp_configured():
            flash("El envío de mails todavía no está configurado en esta tienda. Escribinos por WhatsApp para recuperar tu cuenta.")
            return render_template("forgot_password.html")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM customers WHERE email = %s AND auth_provider = 'local'", (email,)
        )
        customer = cursor.fetchone()

        if customer:
            token = secrets.token_urlsafe(32)
            expires = datetime.utcnow() + timedelta(hours=1)
            cursor.execute(
                "UPDATE customers SET reset_token = %s, reset_token_expires = %s WHERE id = %s",
                (token, expires, customer["id"]),
            )
            conn.commit()
            reset_link = url_for("reset_password", token=token, _external=True)
            send_email(
                email,
                "Recuperar tu contraseña · BrainSuplementos",
                f"Hola {customer['name']},\n\n"
                f"Tocá este link para poner una contraseña nueva (vale por 1 hora):\n{reset_link}\n\n"
                f"Si no lo pediste vos, ignorá este mail.",
            )

        cursor.close()
        conn.close()

        flash("Si ese mail está registrado, te enviamos un link para recuperar tu contraseña.")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    token = request.args.get("token") or request.form.get("token")
    if not token:
        flash("Ese link no es válido")
        return redirect(url_for("forgot_password"))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM customers WHERE reset_token = %s AND auth_provider = 'local'", (token,)
    )
    customer = cursor.fetchone()

    if not customer or not customer["reset_token_expires"] or customer["reset_token_expires"] < datetime.utcnow():
        cursor.close()
        conn.close()
        flash("Ese link venció o no es válido. Pedí uno nuevo.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if password != password2:
            flash("Las contraseñas no coinciden")
        elif len(password) < 6:
            flash("La contraseña tiene que tener al menos 6 caracteres")
        else:
            cursor.execute(
                "UPDATE customers SET password_hash = %s, reset_token = NULL, reset_token_expires = NULL WHERE id = %s",
                (generate_password_hash(password), customer["id"]),
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash("Contraseña actualizada, ya podés ingresar")
            return redirect(url_for("login"))

    cursor.close()
    conn.close()
    return render_template("reset_password.html", token=token)


@app.route("/logout")
def logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    return redirect(url_for("home"))


@app.route("/cuenta")
def customer_account():
    if not session.get("customer_id"):
        return redirect(url_for("login", next="/cuenta"))

    customer_id = session["customer_id"]
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
    customer = cursor.fetchone()

    if not customer:
        cursor.close()
        conn.close()
        session.pop("customer_id", None)
        session.pop("customer_name", None)
        return redirect(url_for("login"))

    cursor.execute(
        """SELECT id, payment_status, delivery_status, cancelled, total, payment_method, delivery_method,
                  delivery_address, created_at
           FROM orders WHERE customer_id = %s ORDER BY created_at DESC""",
        (customer_id,),
    )
    orders = cursor.fetchall()
    for o in orders:
        o["total"] = to_float(o["total"])
        o["items"] = []

    if orders:
        order_ids = [o["id"] for o in orders]
        placeholders = ",".join(["%s"] * len(order_ids))
        cursor.execute(
            f"""SELECT order_id, product_name, unit_price, qty, flavor_name, weight_label
                FROM order_items WHERE order_id IN ({placeholders})""",
            tuple(order_ids),
        )
        items_by_order = {}
        for it in cursor.fetchall():
            it["unit_price"] = to_float(it["unit_price"])
            items_by_order.setdefault(it["order_id"], []).append(it)
        for o in orders:
            o["items"] = items_by_order.get(o["id"], [])

    cursor.close()
    conn.close()
    return render_template("cuenta.html", customer=customer, orders=orders)


@app.route("/api/me")
def api_me():
    if not session.get("customer_id"):
        return jsonify({"logged_in": False})

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT name, email, phone, address FROM customers WHERE id = %s",
        (session["customer_id"],),
    )
    customer = cursor.fetchone()
    cursor.close()
    conn.close()

    if not customer:
        session.pop("customer_id", None)
        session.pop("customer_name", None)
        return jsonify({"logged_in": False})

    return jsonify({
        "logged_in": True,
        "id": session["customer_id"],
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["phone"],
        "address": customer["address"],
    })


# ---- Google ----
@app.route("/auth/google/login")
def google_login():
    if not google_configured():
        flash("El login con Google todavía no está configurado.")
        return redirect(url_for("login"))
    session["oauth_next"] = request.args.get("next", "")
    redirect_uri = url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    if not google_configured():
        return redirect(url_for("login"))
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").lower()
    name = userinfo.get("name") or (email.split("@")[0] if email else "Cliente")
    google_id = userinfo.get("sub")

    customer = find_or_create_oauth_customer("google", google_id, email, name)
    session["customer_id"] = customer["id"]
    session["customer_name"] = customer["name"]
    next_url = session.pop("oauth_next", "") or url_for("home")
    return redirect(next_url)


# ---- Apple ----
@app.route("/auth/apple/login")
def apple_login():
    if not apple_configured():
        flash("El login con Apple todavía no está configurado.")
        return redirect(url_for("login"))
    session["oauth_next"] = request.args.get("next", "")
    redirect_uri = url_for("apple_callback", _external=True)
    return oauth.apple.authorize_redirect(redirect_uri)


@app.route("/auth/apple/callback", methods=["GET", "POST"])
def apple_callback():
    if not apple_configured():
        return redirect(url_for("login"))
    token = oauth.apple.authorize_access_token()
    userinfo = token.get("userinfo") or {}
    apple_id = userinfo.get("sub")
    email = (userinfo.get("email") or "").lower()

    # Apple solo manda nombre y mail la primera vez que la persona autoriza,
    # como JSON en el campo "user" del POST (no viene en el id_token).
    name = None
    user_json = request.form.get("user")
    if user_json:
        try:
            info = json.loads(user_json)
            name_parts = info.get("name", {})
            name = " ".join(filter(None, [name_parts.get("firstName"), name_parts.get("lastName")])).strip()
            email = email or (info.get("email") or "").lower()
        except (ValueError, KeyError):
            pass
    name = name or (email.split("@")[0] if email else "Cliente Apple")

    customer = find_or_create_oauth_customer("apple", apple_id, email, name)
    session["customer_id"] = customer["id"]
    session["customer_name"] = customer["name"]
    next_url = session.pop("oauth_next", "") or url_for("home")
    return redirect(next_url)


# =============================================================
# API pública: productos y pedidos (usada por static/js/caro.js)
# =============================================================
@app.route("/api/hero-slides", methods=["GET"])
def list_hero_slides():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM hero_slides WHERE active = 1 ORDER BY sort_order, id"
        )
        slides = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(slides)
    except MySQLError as e:
        if _table_missing(e):
            return jsonify([])
        app.logger.error(f"Error al listar slides: {e}")
        return jsonify([])


@app.route("/api/goal-banners", methods=["GET"])
def list_goal_banners():
    """Banners motivacionales ("Ganar masa muscular", etc.) que llevan
    directo a los productos de una categoría. Lista vacía (no error) si
    todavía no cargaron ninguno o no corrieron la migración."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM goal_banners WHERE active = 1 ORDER BY sort_order, id"
        )
        banners = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(banners)
    except MySQLError as e:
        if _table_missing(e):
            return jsonify([])
        app.logger.error(f"Error al listar banners: {e}")
        return jsonify([])


@app.route("/api/brands", methods=["GET"])
def list_brands():
    """Logos de "Marcas con las que trabajamos" para la franja animada de
    la home. Lista vacía (no error) si todavía no cargaron ninguna marca,
    o si no corrieron la migración que crea esta tabla — así el front
    simplemente no muestra la sección en vez de romperse."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM brands WHERE active = 1 ORDER BY sort_order, id")
        brands = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(brands)
    except MySQLError as e:
        if _table_missing(e):
            return jsonify([])
        app.logger.error(f"Error al listar marcas: {e}")
        return jsonify([])


@app.route("/api/instagram-posts", methods=["GET"])
def list_instagram_posts():
    """Capturas reales de posteos/reels para la tira "Seguinos en
    Instagram" de la home. Lista vacía (no error) si todavía no
    cargaron ninguna, o si no corrieron la migración de esta tabla."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM instagram_posts WHERE active = 1 ORDER BY sort_order, id")
        posts = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(posts)
    except MySQLError as e:
        if _table_missing(e):
            return jsonify([])
        app.logger.error(f"Error al listar posteos de Instagram: {e}")
        return jsonify([])


@app.route("/api/payment-methods", methods=["GET"])
def api_payment_methods():
    return jsonify(get_payment_settings())


@app.route("/api/mp-config", methods=["GET"])
def api_mp_config():
    """La Public Key de Mercado Pago no es secreta (está pensada para vivir
    en el navegador), así que es seguro exponerla acá. El Access Token
    (el que sí es secreto) nunca se manda al frontend."""
    if not mp_card_form_configured():
        return jsonify({"public_key": None})
    return jsonify({"public_key": MP_PUBLIC_KEY})


def _enrich_products(cursor, rows):
    """Le suma a una lista de filas de products (con category/category_name
    ya traídos por el SELECT que las buscó) los sabores con su stock real,
    las fotos extra y el promedio de estrellas — es la misma lógica que
    usaba /api/products, separada en una función aparte para poder
    reutilizarla en otros endpoints que también necesitan la ficha
    completa del producto (ej: /api/most-purchased) sin repetir el
    código ni arriesgar que se desincronicen con el tiempo."""
    flavors_by_product = {}
    images_by_product = {}
    rating_by_product = {}
    if rows:
        product_ids = [r["id"] for r in rows]
        placeholders = ",".join(["%s"] * len(product_ids))
        try:
            cursor.execute(
                f"SELECT * FROM product_flavors WHERE product_id IN ({placeholders}) "
                f"ORDER BY sort_order, id",
                tuple(product_ids),
            )
            colors = cursor.fetchall()
            if colors:
                flavor_ids = [c["id"] for c in colors]
                fplaceholders = ",".join(["%s"] * len(flavor_ids))
                cursor.execute(
                    f"SELECT * FROM product_flavor_images WHERE flavor_id IN ({fplaceholders}) "
                    f"ORDER BY sort_order, id",
                    tuple(flavor_ids),
                )
                images_by_flavor = {}
                for img in cursor.fetchall():
                    images_by_flavor.setdefault(img["flavor_id"], []).append(img["image_url"])
                for c in colors:
                    c["images"] = images_by_flavor.get(c["id"], [])
                    c["thumbnail"] = c["images"][0] if c["images"] else None
                    flavors_by_product.setdefault(c["product_id"], []).append(c)

                try:
                    cursor.execute(
                        f"SELECT product_flavor_id, SUM(stock) AS total_stock FROM product_weights "
                        f"WHERE product_flavor_id IN ({fplaceholders}) GROUP BY product_flavor_id",
                        tuple(flavor_ids),
                    )
                    flavor_weight_stock = {row["product_flavor_id"]: row["total_stock"] for row in cursor.fetchall()}
                    for c in colors:
                        if c["id"] in flavor_weight_stock:
                            c["stock"] = flavor_weight_stock[c["id"]]
                except MySQLError as e:
                    if not _table_missing(e):
                        raise
        except MySQLError as e:
            if not _table_missing(e):
                raise
            app.logger.warning("Falta la migración de sabores (product_flavors) — ver README sección 6.")

        try:
            cursor.execute(
                f"SELECT product_id, image_url FROM product_images "
                f"WHERE product_id IN ({placeholders}) ORDER BY sort_order, id",
                tuple(product_ids),
            )
            for img in cursor.fetchall():
                images_by_product.setdefault(img["product_id"], []).append(img["image_url"])
        except MySQLError as e:
            if not _table_missing(e):
                raise

        try:
            cursor.execute(
                f"SELECT product_id, AVG(rating) AS avg_rating, COUNT(*) AS n FROM product_reviews "
                f"WHERE product_id IN ({placeholders}) GROUP BY product_id",
                tuple(product_ids),
            )
            for row in cursor.fetchall():
                rating_by_product[row["product_id"]] = {
                    "avg": round(float(row["avg_rating"]), 1), "count": row["n"],
                }
        except MySQLError as e:
            if not _table_missing(e):
                raise

    for r in rows:
        r["price"] = to_float(r["price"])
        r["discount_percent"] = to_float(r["discount_percent"])
        product_flavors = flavors_by_product.get(r["id"], [])
        if product_flavors:
            r["stock"] = sum(c["stock"] for c in product_flavors)
            r["image_url"] = product_flavors[0]["thumbnail"] or r["image_url"]
        r["colors"] = [
            {"id": c["id"], "name": c["flavor_name"], "hex": c["flavor_color_hex"], "images": c.get("images", [])}
            for c in product_flavors
        ]
        r["images"] = images_by_product.get(r["id"], [])
        rating = rating_by_product.get(r["id"])
        r["rating_avg"] = rating["avg"] if rating else None
        r["rating_count"] = rating["count"] if rating else 0
    return rows


@app.route("/api/products", methods=["GET"])
def list_products():
    category = request.args.get("category")  # opcional: ?category=creatina (slug de categories)
    # Opcional: ?subcategoria=whey — solo tiene efecto junto con la
    # categoría que tenga esa subcategoría cargada.
    subcategoria = (request.args.get("subcategoria") or "").strip() or None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        base = (
            "SELECT p.*, cat.slug AS category, cat.name AS category_name "
            "FROM products p JOIN categories cat ON p.category_id = cat.id "
            "LEFT JOIN subcategories sub ON p.subcategory_id = sub.id"
        )
        conditions = ["p.active = 1"]
        params = []
        if category and category != "todos":
            conditions.append("cat.slug = %s")
            params.append(category)
        if subcategoria:
            conditions.append("sub.slug = %s")
            params.append(subcategoria)
        cursor.execute(
            f"{base} WHERE {' AND '.join(conditions)} ORDER BY cat.sort_order, p.created_at DESC",
            tuple(params),
        )
        rows = cursor.fetchall()
        rows = _enrich_products(cursor, rows)
        cursor.close()
        conn.close()
        return jsonify(rows)
    except MySQLError as e:
        app.logger.error(f"Error al listar productos: {e}")
        return jsonify({"error": "No se pudo cargar el catálogo"}), 500


@app.route("/api/newest-products", methods=["GET"])
def newest_products():
    """"Novedades": primero los productos que el admin fijó a mano en
    /admin/destacados (sección "novedades"), y después se completa el
    resto con los cargados más recientemente — a diferencia de "Más
    vendidos" (antes "Los más llevados"), que ordena por ventas reales."""
    try:
        limit = min(max(int(request.args.get("limit", 12)), 1), 24)
    except (TypeError, ValueError):
        limit = 12
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        pinned_rows = []
        try:
            cursor.execute(
                """SELECT p.*, cat.slug AS category, cat.name AS category_name
                   FROM featured_products fp
                   JOIN products p ON p.id = fp.product_id
                   JOIN categories cat ON p.category_id = cat.id
                   WHERE fp.section = 'novedades' AND p.active = 1
                   ORDER BY fp.sort_order, fp.id
                   LIMIT %s""",
                (limit,),
            )
            pinned_rows = cursor.fetchall()
        except MySQLError as e:
            if not _table_missing(e):
                raise

        pinned_ids = [r["id"] for r in pinned_rows]
        rows = pinned_rows
        remaining = limit - len(pinned_rows)
        if remaining > 0:
            if pinned_ids:
                placeholders = ",".join(["%s"] * len(pinned_ids))
                cursor.execute(
                    f"""SELECT p.*, cat.slug AS category, cat.name AS category_name
                        FROM products p
                        JOIN categories cat ON p.category_id = cat.id
                        WHERE p.active = 1 AND p.id NOT IN ({placeholders})
                        ORDER BY p.created_at DESC
                        LIMIT %s""",
                    (*pinned_ids, remaining),
                )
            else:
                cursor.execute(
                    """SELECT p.*, cat.slug AS category, cat.name AS category_name
                       FROM products p
                       JOIN categories cat ON p.category_id = cat.id
                       WHERE p.active = 1
                       ORDER BY p.created_at DESC
                       LIMIT %s""",
                    (remaining,),
                )
            rows = rows + cursor.fetchall()

        rows = _enrich_products(cursor, rows)
        cursor.close()
        conn.close()
        return jsonify(rows)
    except MySQLError as e:
        app.logger.error(f"Error al calcular novedades: {e}")
        return jsonify([])


@app.route("/api/most-purchased", methods=["GET"])
def most_purchased():
    """"Más vendidos": primero los productos que el admin fijó a mano en
    /admin/destacados (sección "vendidos"), y después se completa el
    resto sumando las cantidades de order_items de todos los pedidos que
    no estén cancelados. Si la tienda es nueva y todavía no tiene ventas,
    ese resto se completa con los productos más nuevos para que la
    sección nunca aparezca vacía."""
    try:
        limit = min(max(int(request.args.get("limit", 12)), 1), 24)
    except (TypeError, ValueError):
        limit = 12
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        pinned_rows = []
        try:
            cursor.execute(
                """SELECT p.*, cat.slug AS category, cat.name AS category_name
                   FROM featured_products fp
                   JOIN products p ON p.id = fp.product_id
                   JOIN categories cat ON p.category_id = cat.id
                   WHERE fp.section = 'vendidos' AND p.active = 1
                   ORDER BY fp.sort_order, fp.id
                   LIMIT %s""",
                (limit,),
            )
            pinned_rows = cursor.fetchall()
        except MySQLError as e:
            if not _table_missing(e):
                raise

        pinned_ids = [r["id"] for r in pinned_rows]
        rows = pinned_rows
        remaining = limit - len(pinned_rows)
        if remaining > 0:
            exclude_clause = ""
            params = []
            if pinned_ids:
                placeholders = ",".join(["%s"] * len(pinned_ids))
                exclude_clause = f"AND p.id NOT IN ({placeholders})"
                params = list(pinned_ids)
            params.append(remaining)
            cursor.execute(
                f"""SELECT p.*, cat.slug AS category, cat.name AS category_name,
                           COALESCE(t.total_sold, 0) AS total_sold
                    FROM products p
                    JOIN categories cat ON p.category_id = cat.id
                    LEFT JOIN (
                      SELECT oi.product_id, SUM(oi.qty) AS total_sold
                      FROM order_items oi
                      JOIN orders o ON o.id = oi.order_id
                      WHERE o.cancelled = 0
                      GROUP BY oi.product_id
                    ) t ON t.product_id = p.id
                    WHERE p.active = 1 {exclude_clause}
                    ORDER BY total_sold DESC, p.created_at DESC
                    LIMIT %s""",
                tuple(params),
            )
            extra_rows = cursor.fetchall()
            for r in extra_rows:
                r.pop("total_sold", None)
            rows = rows + extra_rows

        rows = _enrich_products(cursor, rows)
        cursor.close()
        conn.close()
        return jsonify(rows)
    except MySQLError as e:
        app.logger.error(f"Error al calcular los más vendidos: {e}")
        return jsonify([])


@app.route("/api/products/<int:product_id>", methods=["GET"])
def product_detail(product_id):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT p.*, cat.slug AS category, cat.name AS category_name "
            "FROM products p JOIN categories cat ON p.category_id = cat.id "
            "WHERE p.id = %s AND p.active = 1",
            (product_id,),
        )
        product = cursor.fetchone()
        cursor.close()
        conn.close()

        if not product:
            return jsonify({"error": "Producto no encontrado"}), 404

        product["price"] = to_float(product["price"])
        product["discount_percent"] = to_float(product["discount_percent"])

        colors = get_flavors_for_product(product_id)
        product["colors"] = [
            {
                "id": c["id"],
                "name": c["flavor_name"],
                "hex": c["flavor_color_hex"],
                "stock": c["stock"],
                "images": [img["image_url"] for img in c["images"]],
                # Si este sabor tiene pesos propios, el navegador los usa
                # en vez de los pesos generales de más abajo — cada peso
                # trae su propio stock (ej: 2 de este sabor en L, 1 en M).
                "sizes": [
                    {"id": s["id"], "name": s["weight_label"], "stock": s["stock"]}
                    for s in c.get("sizes", [])
                ],
            }
            for c in colors
        ]

        sizes = get_weights_for_product(product_id)
        product["sizes"] = [
            {"id": s["id"], "name": s["weight_label"], "stock": s["stock"]}
            for s in sizes
        ]

        extra_images = get_images_for_product(product_id)
        product["images"] = [img["image_url"] for img in extra_images]

        reviews = get_reviews_for_product(product_id)
        product["reviews"] = [
            {
                "id": r["id"],
                "customer_id": r["customer_id"],
                "customer_name": r["customer_name"],
                "rating": r["rating"],
                "comment": r["comment"],
                "verified": r.get("verified", False),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in reviews
        ]
        product["rating_count"] = len(reviews)
        product["rating_avg"] = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None

        return jsonify(product)
    except MySQLError as e:
        app.logger.error(f"Error al leer producto: {e}")
        return jsonify({"error": "No se pudo cargar el producto"}), 500


@app.route("/api/products/<int:product_id>/reviews", methods=["POST"])
def submit_review(product_id):
    """Un cliente logueado deja (o actualiza) su reseña de este producto.
    Una sola reseña por cliente y producto: si ya había opinado, se
    actualiza en vez de duplicarse."""
    if not session.get("customer_id"):
        return jsonify({"error": "Tenés que iniciar sesión para dejar una reseña"}), 401

    try:
        rating = int(request.json.get("rating"))
    except (TypeError, ValueError, AttributeError):
        return jsonify({"error": "Falta la calificación"}), 400
    if rating < 1 or rating > 5:
        return jsonify({"error": "La calificación tiene que ser de 1 a 5"}), 400
    comment = (request.json.get("comment") or "").strip()[:2000]
    customer_id = session["customer_id"]

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM products WHERE id = %s", (product_id,))
        if not cursor.fetchone():
            cursor.close(); conn.close()
            return jsonify({"error": "Producto no encontrado"}), 404
        cursor.execute(
            """INSERT INTO product_reviews (product_id, customer_id, rating, comment)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE rating = VALUES(rating), comment = VALUES(comment)""",
            (product_id, customer_id, rating, comment),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"ok": True})
    except MySQLError as e:
        if _table_missing(e):
            return jsonify({"error": "Todavía no está habilitada esta función (falta correr una migración)"}), 500
        app.logger.error(f"Error al guardar reseña: {e}")
        return jsonify({"error": "No se pudo guardar la reseña"}), 500


@app.route("/api/reviews/<int:review_id>", methods=["DELETE"])
def delete_own_review(review_id):
    """El cliente puede borrar su propia reseña."""
    if not session.get("customer_id"):
        return jsonify({"error": "Tenés que iniciar sesión"}), 401
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT customer_id FROM product_reviews WHERE id = %s", (review_id,))
        row = cursor.fetchone()
        if not row or row["customer_id"] != session["customer_id"]:
            cursor.close(); conn.close()
            return jsonify({"error": "Esa reseña no es tuya"}), 403
        cursor.execute("DELETE FROM product_reviews WHERE id = %s", (review_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"ok": True})
    except MySQLError as e:
        app.logger.error(f"Error al borrar reseña: {e}")
        return jsonify({"error": "No se pudo borrar la reseña"}), 500


@app.route("/api/sets", methods=["GET"])
def list_sets():
    """Combos/looks visibles en la tienda, con sus productos (solo los
    que siguen activos). Si la migración de combos todavía no se corrió,
    devuelve una lista vacía en vez de romper la home. El precio de cada
    producto adentro de un combo es el que se cargó puntualmente para ESE
    combo (columna price de product_set_items), ignorando el precio y el
    descuento que tenga ese producto en el catálogo normal."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT id, name, description, image_url, discount_price FROM product_sets "
                "WHERE active = 1 ORDER BY sort_order, created_at DESC"
            )
            sets = cursor.fetchall()
        except MySQLError as e:
            if not _table_missing(e):
                raise
            cursor.execute(
                "SELECT id, name, description, image_url FROM product_sets "
                "WHERE active = 1 ORDER BY sort_order, created_at DESC"
            )
            sets = cursor.fetchall()
            for s in sets:
                s["discount_price"] = None

        for s in sets:
            s["discount_price"] = to_float(s.get("discount_price")) if s.get("discount_price") is not None else None

        if sets:
            set_ids = [s["id"] for s in sets]
            placeholders = ",".join(["%s"] * len(set_ids))
            try:
                cursor.execute(
                    f"""SELECT si.set_id, p.id, p.name, p.image_url, si.price AS set_price
                        FROM product_set_items si
                        JOIN products p ON p.id = si.product_id
                        WHERE si.set_id IN ({placeholders}) AND p.active = 1
                        ORDER BY si.sort_order, si.id""",
                    tuple(set_ids),
                )
                item_rows = cursor.fetchall()
                has_set_price_column = True
            except MySQLError as e:
                if not _table_missing(e):
                    raise
                cursor.execute(
                    f"""SELECT si.set_id, p.id, p.name, p.price, p.discount_percent, p.image_url
                        FROM product_set_items si
                        JOIN products p ON p.id = si.product_id
                        WHERE si.set_id IN ({placeholders}) AND p.active = 1
                        ORDER BY si.sort_order, si.id""",
                    tuple(set_ids),
                )
                item_rows = cursor.fetchall()
                has_set_price_column = False

            # Si el producto tiene sabores o pesos, no lo podemos agregar
            # solos al carrito con "Agregar combo" (hay que elegir cuál),
            # así que le avisamos al frontend cuáles necesitan abrir la
            # ficha del producto en vez de agregarse directo.
            has_flavors = set()
            has_weights = set()
            if item_rows:
                product_ids = list({row["id"] for row in item_rows})
                pplaceholders = ",".join(["%s"] * len(product_ids))
                try:
                    cursor.execute(
                        f"SELECT DISTINCT product_id FROM product_flavors WHERE product_id IN ({pplaceholders})",
                        tuple(product_ids),
                    )
                    has_flavors = {row["product_id"] for row in cursor.fetchall()}
                except MySQLError as e:
                    if not _table_missing(e):
                        raise
                try:
                    cursor.execute(
                        f"SELECT DISTINCT product_id FROM product_weights WHERE product_id IN ({pplaceholders})",
                        tuple(product_ids),
                    )
                    has_weights = {row["product_id"] for row in cursor.fetchall()}
                except MySQLError as e:
                    if not _table_missing(e):
                        raise

            items_by_set = {}
            for row in item_rows:
                if has_set_price_column:
                    row["price"] = to_float(row.get("set_price")) if row.get("set_price") is not None else 0.0
                    row["discount_percent"] = None
                else:
                    row["price"] = to_float(row["price"])
                    row["discount_percent"] = to_float(row["discount_percent"])
                items_by_set.setdefault(row["set_id"], []).append({
                    "id": row["id"], "name": row["name"], "price": row["price"],
                    "discount_percent": row["discount_percent"], "image_url": row["image_url"],
                    "has_variants": row["id"] in has_flavors or row["id"] in has_weights,
                })
            for s in sets:
                s["items"] = items_by_set.get(s["id"], [])

        cursor.close()
        conn.close()
        # Un combo con menos de 2 productos activos ya no tiene sentido
        # mostrarlo (por ejemplo si se pausó uno de los productos).
        sets = [s for s in sets if len(s.get("items", [])) >= 2]
        return jsonify(sets)
    except MySQLError as e:
        if _table_missing(e):
            return jsonify([])
        app.logger.error(f"Error al listar combos: {e}")
        return jsonify([])


class InsufficientStockError(Exception):
    def __init__(self, message):
        self.message = message


def decrement_stock_or_raise(cursor, items):
    """Chequea y descuenta stock real para cada item del pedido, dentro de
    la transacción ya abierta en `cursor`. Usa SELECT ... FOR UPDATE para
    bloquear la fila mientras dura la transacción, así dos compras al
    mismo tiempo no vendan de más. Levanta InsufficientStockError si algo
    no tiene stock suficiente (el llamador debe hacer rollback).

    Devuelve una lista de "avisos de stock bajo": una entrada por cada
    variante que, con esta venta, cruzó por primera vez el umbral de
    LOW_STOCK_THRESHOLD (estaba arriba antes de vender, quedó igual o por
    debajo después) — el llamador manda el mail a la dueña después de
    confirmar la transacción."""
    low_stock_alerts = []
    for i in items:
        qty = int(i["qty"])
        flavor_id = i.get("flavor_id")
        weight_id = i.get("weight_id")
        item_product_id = i.get("product_id")

        # Si el peso elegido pertenece a un sabor en particular (stock por
        # combinación sabor+peso, ej: "2 de Rosa viejo peso L"), el stock
        # real es el de ESE peso nomás — no hay que tocar el stock del
        # sabor por separado, porque ya no significa nada en ese modo.
        weight_belongs_to_flavor = False

        if weight_id:
            cursor.execute(
                "SELECT stock, product_flavor_id FROM product_weights WHERE id = %s FOR UPDATE",
                (weight_id,),
            )
            row = cursor.fetchone()
            if not row or row[0] < qty:
                raise InsufficientStockError(f"No hay stock suficiente de \"{i['name']}\" en ese peso")
            cursor.execute("UPDATE product_weights SET stock = stock - %s WHERE id = %s", (qty, weight_id))
            weight_belongs_to_flavor = row[1] is not None
            new_stock = row[0] - qty
            if row[0] > LOW_STOCK_THRESHOLD >= new_stock:
                variant = ", ".join(filter(None, [i.get("flavor_name"), f"Peso {i.get('weight_label')}" if i.get("weight_label") else None]))
                low_stock_alerts.append({"name": i["name"], "variant": variant, "stock": new_stock})

        if flavor_id and not weight_belongs_to_flavor:
            cursor.execute("SELECT stock FROM product_flavors WHERE id = %s FOR UPDATE", (flavor_id,))
            row = cursor.fetchone()
            if not row or row[0] < qty:
                raise InsufficientStockError(f"No hay stock suficiente de \"{i['name']}\" en ese sabor")
            cursor.execute("UPDATE product_flavors SET stock = stock - %s WHERE id = %s", (qty, flavor_id))
            new_stock = row[0] - qty
            if row[0] > LOW_STOCK_THRESHOLD >= new_stock:
                low_stock_alerts.append({"name": i["name"], "variant": i.get("flavor_name") or "", "stock": new_stock})

        if not flavor_id and not weight_id and item_product_id:
            cursor.execute("SELECT stock FROM products WHERE id = %s FOR UPDATE", (item_product_id,))
            row = cursor.fetchone()
            if not row or row[0] < qty:
                raise InsufficientStockError(f"No hay stock suficiente de \"{i['name']}\"")
            cursor.execute("UPDATE products SET stock = stock - %s WHERE id = %s", (qty, item_product_id))
            new_stock = row[0] - qty
            if row[0] > LOW_STOCK_THRESHOLD >= new_stock:
                low_stock_alerts.append({"name": i["name"], "variant": "", "stock": new_stock})

    return low_stock_alerts


def restore_stock_for_pos_sale_items(cursor, items):
    """Inverso de decrement_stock_or_raise, para cuando se cancela una
    venta presencial: le devuelve a cada variante la cantidad que se le
    había descontado. Sigue exactamente el mismo criterio de qué columna
    tocar (peso propio de un sabor, sabor sin peso propio, peso suelto,
    o producto sin variantes) para no duplicar ni perder unidades. `items`
    son filas de pos_sale_items (dict con product_id, qty, product_flavor_id,
    product_weight_id)."""
    for it in items:
        qty = it["qty"]
        flavor_id = it.get("product_flavor_id")
        weight_id = it.get("product_weight_id")
        product_id = it.get("product_id")

        weight_belongs_to_flavor = False
        if weight_id:
            cursor.execute("SELECT product_flavor_id FROM product_weights WHERE id = %s", (weight_id,))
            row = cursor.fetchone()
            if row:
                cursor.execute("UPDATE product_weights SET stock = stock + %s WHERE id = %s", (qty, weight_id))
                weight_belongs_to_flavor = row[0] is not None

        if flavor_id and not weight_belongs_to_flavor:
            cursor.execute("UPDATE product_flavors SET stock = stock + %s WHERE id = %s", (qty, flavor_id))

        if not flavor_id and not weight_id and product_id:
            cursor.execute("UPDATE products SET stock = stock + %s WHERE id = %s", (qty, product_id))


def send_low_stock_alerts(low_stock_alerts):
    """Le manda un mail a la dueña avisando qué productos/variantes se
    están por agotar, después de confirmada una venta."""
    if not low_stock_alerts or not smtp_configured():
        return
    to_address = get_store_notification_email()
    if not to_address:
        return
    lines = []
    for a in low_stock_alerts:
        variant = f" ({a['variant']})" if a["variant"] else ""
        unidades = "unidad" if a["stock"] == 1 else "unidades"
        lines.append(f"- {a['name']}{variant}: quedan {a['stock']} {unidades}")
    body = (
        "Hola,\n\nEstos productos se están por agotar en BrainSuplementos:\n\n"
        + "\n".join(lines)
        + "\n\nConviene reponer stock pronto.\n\n— BrainSuplementos"
    )
    try:
        send_email(to_address, "Alerta de stock bajo · BrainSuplementos", body)
    except Exception as e:
        app.logger.error(f"No se pudo enviar alerta de stock bajo: {e}")


def resolve_shipping_cost(cursor, delivery_method, shipping_zone_id, item_subtotal):
    """Calcula el costo de envío real para el pedido, validando la zona en
    el servidor (nunca confiamos en un precio que mande el navegador).
    `cursor` tiene que ser dictionary=True. Devuelve (zone_name, shipping_cost, error)."""
    if delivery_method != "Envío a domicilio" or not shipping_zone_id:
        return None, Decimal("0"), None
    try:
        cursor.execute(
            "SELECT * FROM shipping_zones WHERE id = %s AND active = 1", (shipping_zone_id,)
        )
        zone = cursor.fetchone()
    except MySQLError as e:
        if _table_missing(e):
            return None, Decimal("0"), None
        raise
    if not zone:
        return None, None, "Elegí una zona de envío válida"
    free_from = zone["free_from"]
    if free_from is not None and item_subtotal >= Decimal(str(free_from)):
        return zone["name"], Decimal("0"), None
    return zone["name"], Decimal(str(zone["price"])), None


def get_valid_coupon(cursor, code):
    """Busca un cupón por código y valida que se pueda usar (activo, no
    vencido, no agotado). Devuelve (fila_del_cupon, None) si es válido, o
    (None, "motivo") si no. `cursor` tiene que ser dictionary=True."""
    if not code or not code.strip():
        return None, "Ingresá un código"
    cursor.execute("SELECT * FROM coupons WHERE code = %s", (code.strip().upper(),))
    row = cursor.fetchone()
    if not row:
        return None, "Ese cupón no existe"
    if not row["active"]:
        return None, "Ese cupón ya no está activo"
    if row["expires_at"] and row["expires_at"] < date.today():
        return None, "Ese cupón venció"
    if row["usage_limit"] is not None and row["used_count"] >= row["usage_limit"]:
        return None, "Ese cupón llegó al límite de usos"
    return row, None


@app.route("/api/coupons/validate", methods=["POST"])
def validate_coupon():
    """Valida un cupón antes de confirmar la compra (para mostrar el
    descuento en el resumen del checkout, sin consumir el uso todavía)."""
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    try:
        subtotal = Decimal(str(data.get("subtotal", 0)))
    except Exception:
        subtotal = Decimal("0")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        coupon, error = get_valid_coupon(cursor, code)
        cursor.close()
        conn.close()
        if error:
            return jsonify({"valid": False, "error": error}), 400
        discount = (subtotal * Decimal(str(coupon["percent_off"])) / 100).quantize(Decimal("0.01"))
        return jsonify({
            "valid": True,
            "code": coupon["code"],
            "percent_off": to_float(coupon["percent_off"]),
            "discount_amount": to_float(discount),
        })
    except MySQLError as e:
        if _table_missing(e):
            return jsonify({"valid": False, "error": "Los cupones todavía no están habilitados"}), 400
        app.logger.error(f"Error al validar cupón: {e}")
        return jsonify({"valid": False, "error": "No se pudo validar el cupón"}), 500


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ensure_welcome_coupon():
    """Se asegura de que exista el cupón que se le regala a quien completa
    el popup de bienvenida (10% de descuento, sin vencimiento ni límite de
    usos). Si la tienda ya lo tiene creado o lo editó desde Admin → Cupones,
    respeta ese cupón tal cual está — sólo lo crea si no existe."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("INSERT IGNORE INTO coupons (code, percent_off, active) VALUES ('BIENVENIDA10', 10, 1)")
    conn.commit()
    cursor.execute("SELECT * FROM coupons WHERE code = 'BIENVENIDA10'")
    coupon = cursor.fetchone()
    cursor.close()
    conn.close()
    return coupon


@app.route("/api/welcome-signup", methods=["POST"])
def welcome_signup():
    """Popup de bienvenida: guarda nombre/mail/cumpleaños y devuelve (y si
    hay SMTP configurado, también manda por mail) un cupón de descuento
    para la primera compra. No falla si el visitante ya se había anotado
    antes con el mismo mail — simplemente actualiza sus datos."""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    birthday = (data.get("birthday") or "").strip() or None

    if not name:
        return jsonify({"ok": False, "error": "Contanos tu nombre"}), 400
    if not email or not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "Ese mail no parece válido"}), 400

    try:
        coupon = ensure_welcome_coupon()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO welcome_signups (name, email, birthday, coupon_code)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE name = VALUES(name), birthday = VALUES(birthday)""",
            (name, email, birthday, coupon["code"]),
        )
        conn.commit()
        cursor.close()
        conn.close()

        emailed = send_email(
            email,
            "¡Bienvenido/a a BrainSuplementos! 🎁 Tu cupón de descuento",
            f"Hola {name}!\n\n"
            f"Gracias por sumarte a BrainSuplementos. Como regalo de bienvenida "
            f"tenés un {int(coupon['percent_off'])}% de descuento para tu primera compra.\n\n"
            f"Código: {coupon['code']}\n\n"
            f"Cargalo en el checkout, en el campo de cupón, antes de confirmar tu pedido.\n\n"
            f"Te esperamos! 💪",
        )
        return jsonify({
            "ok": True,
            "code": coupon["code"],
            "percent_off": to_float(coupon["percent_off"]),
            "emailed": emailed,
        })
    except MySQLError as e:
        if _table_missing(e):
            return jsonify({"ok": False, "error": "Esta función todavía no está habilitada (falta correr migracion_bienvenida.sql)"}), 400
        app.logger.error(f"Error al guardar el registro de bienvenida: {e}")
        return jsonify({"ok": False, "error": "No se pudo guardar. Probá de nuevo."}), 500


@app.route("/api/stock-notify", methods=["POST"])
def request_stock_notify():
    """Guarda el pedido de "avisame cuando haya stock" de un producto sin
    stock (o de una combinación sabor/peso puntual sin stock)."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip()
    product_id = data.get("product_id")
    flavor_id = data.get("flavor_id") or None
    weight_id = data.get("weight_id") or None

    if not email or "@" not in email:
        return jsonify({"error": "Ingresá un email válido"}), 400
    if not product_id:
        return jsonify({"error": "Falta el producto"}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        query = "SELECT id FROM stock_notify_requests WHERE email = %s AND product_id = %s"
        params = [email, product_id]
        if flavor_id is not None:
            query += " AND product_flavor_id = %s"
            params.append(flavor_id)
        else:
            query += " AND product_flavor_id IS NULL"
        if weight_id is not None:
            query += " AND product_weight_id = %s"
            params.append(weight_id)
        else:
            query += " AND product_weight_id IS NULL"
        cursor.execute(query, tuple(params))
        existing = cursor.fetchone()

        plain_cursor = conn.cursor()
        if existing:
            plain_cursor.execute(
                "UPDATE stock_notify_requests SET notified = 0 WHERE id = %s", (existing["id"],)
            )
        else:
            plain_cursor.execute(
                "INSERT INTO stock_notify_requests (email, product_id, product_flavor_id, product_weight_id) "
                "VALUES (%s, %s, %s, %s)",
                (email, product_id, flavor_id, weight_id),
            )
        conn.commit()
        plain_cursor.close()
        cursor.close()
        conn.close()
        return jsonify({"ok": True})
    except MySQLError as e:
        if _table_missing(e):
            return jsonify({"error": "Corré migracion_funciones_nuevas.sql para activar esta función"}), 503
        app.logger.error(f"Error al guardar aviso de stock: {e}")
        return jsonify({"error": "No se pudo guardar el aviso"}), 500


def check_stock_notify(product_id, product_flavor_id=None, product_weight_id=None):
    """Si alguien pidió que le avisemos cuando esta variante puntual (o el
    producto entero, si no tiene sabor/peso) tenga stock, y ahora lo
    tiene, le mandamos el mail y marcamos el pedido como avisado para no
    volver a mandarlo. Se llama después de cualquier ALTA o actualización
    de stock (sabor, peso o producto sin variantes)."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        if product_weight_id is not None:
            cursor.execute("SELECT stock FROM product_weights WHERE id = %s", (product_weight_id,))
        elif product_flavor_id is not None:
            cursor.execute("SELECT stock FROM product_flavors WHERE id = %s", (product_flavor_id,))
        else:
            cursor.execute("SELECT stock FROM products WHERE id = %s", (product_id,))
        row = cursor.fetchone()
        stock = row["stock"] if row else 0
        if not stock or stock <= 0:
            cursor.close()
            conn.close()
            return

        query = "SELECT * FROM stock_notify_requests WHERE product_id = %s AND notified = 0"
        params = [product_id]
        if product_flavor_id is not None:
            query += " AND product_flavor_id = %s"
            params.append(product_flavor_id)
        else:
            query += " AND product_flavor_id IS NULL"
        if product_weight_id is not None:
            query += " AND product_weight_id = %s"
            params.append(product_weight_id)
        else:
            query += " AND product_weight_id IS NULL"
        cursor.execute(query, tuple(params))
        requests_to_notify = cursor.fetchall()
        if not requests_to_notify:
            cursor.close()
            conn.close()
            return

        cursor.execute("SELECT name FROM products WHERE id = %s", (product_id,))
        prod = cursor.fetchone()
        product_name = prod["name"] if prod else "un producto"

        plain_cursor = conn.cursor()
        for r in requests_to_notify:
            if smtp_configured():
                try:
                    send_email(
                        r["email"],
                        f"¡Ya hay stock de {product_name}! · BrainSuplementos",
                        f"Hola,\n\nEl producto que estabas esperando ya tiene stock disponible: {product_name}.\n"
                        f"Entrá a la tienda para verlo antes de que se agote de nuevo.\n\n— BrainSuplementos",
                    )
                except Exception as e:
                    app.logger.error(f"No se pudo enviar aviso de stock a {r['email']}: {e}")
            plain_cursor.execute(
                "UPDATE stock_notify_requests SET notified = 1 WHERE id = %s", (r["id"],)
            )
        conn.commit()
        plain_cursor.close()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if not _table_missing(e):
            app.logger.error(f"Error al chequear avisos de stock: {e}")


def insert_order_and_items(cursor, customer_id, total, payment_method, delivery_method, delivery_address, items,
                            coupon_code=None, discount_amount=None, shipping_zone=None, shipping_cost=None):
    """Inserta la fila de orders y sus order_items dentro de la transacción
    ya abierta en `cursor`. Devuelve el order_id. Si todavía no corriste
    alguna de las migraciones (cupones, envíos), guarda igual el pedido sin
    esos campos (para que nunca tiren abajo el checkout)."""
    try:
        cursor.execute(
            """INSERT INTO orders
               (customer_id, total, payment_method, delivery_method, delivery_address, payment_status,
                coupon_code, discount_amount, shipping_zone, shipping_cost)
               VALUES (%s, %s, %s, %s, %s, 'pendiente', %s, %s, %s, %s)""",
            (customer_id, total, payment_method, delivery_method, delivery_address,
             coupon_code, discount_amount, shipping_zone, shipping_cost),
        )
    except MySQLError as e:
        if not _table_missing(e):
            raise
        try:
            cursor.execute(
                """INSERT INTO orders
                   (customer_id, total, payment_method, delivery_method, delivery_address, payment_status,
                    coupon_code, discount_amount)
                   VALUES (%s, %s, %s, %s, %s, 'pendiente', %s, %s)""",
                (customer_id, total, payment_method, delivery_method, delivery_address, coupon_code, discount_amount),
            )
        except MySQLError as e2:
            if not _table_missing(e2):
                raise
            cursor.execute(
                """INSERT INTO orders
                   (customer_id, total, payment_method, delivery_method, delivery_address, payment_status)
                   VALUES (%s, %s, %s, %s, %s, 'pendiente')""",
                (customer_id, total, payment_method, delivery_method, delivery_address),
            )
    order_id = cursor.lastrowid

    for i in items:
        cursor.execute(
            """INSERT INTO order_items
               (order_id, product_id, product_name, unit_price, qty,
                product_flavor_id, flavor_name, product_weight_id, weight_label)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                order_id, i.get("product_id"), i["name"], i["price"], i["qty"],
                i.get("flavor_id"), i.get("flavor_name"),
                i.get("weight_id"), i.get("weight_label"),
            ),
        )
    return order_id


@app.route("/api/orders", methods=["POST"])
def create_order():
    if not session.get("customer_id"):
        return jsonify({"error": "login_required"}), 401

    data = request.get_json(force=True, silent=True) or {}

    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    delivery_method = data.get("delivery_method", "")
    delivery_address = data.get("delivery_address")
    payment_method = data.get("payment_method", "")
    items = data.get("items", [])  # [{product_id, name, price, qty}, ...]

    if not name or not phone:
        return jsonify({"error": "Faltan nombre o teléfono"}), 400
    if not items:
        return jsonify({"error": "El carrito está vacío"}), 400

    item_subtotal = sum(Decimal(str(i["price"])) * int(i["qty"]) for i in items)
    total = item_subtotal
    customer_id = session["customer_id"]
    coupon_code_input = (data.get("coupon_code") or "").strip()
    shipping_zone_id = data.get("shipping_zone_id") if delivery_method == "Envío a domicilio" else None

    try:
        conn = get_connection()

        discount_amount = Decimal("0")
        applied_coupon = None
        if coupon_code_input:
            dcursor = conn.cursor(dictionary=True)
            applied_coupon, coupon_error = get_valid_coupon(dcursor, coupon_code_input)
            dcursor.close()
            if coupon_error:
                conn.close()
                return jsonify({"error": coupon_error}), 400
            discount_amount = (total * Decimal(str(applied_coupon["percent_off"])) / 100).quantize(Decimal("0.01"))
            total = total - discount_amount

        dcursor = conn.cursor(dictionary=True)
        shipping_zone_name, shipping_cost, shipping_error = resolve_shipping_cost(
            dcursor, delivery_method, shipping_zone_id, item_subtotal
        )
        dcursor.close()
        if shipping_error:
            conn.close()
            return jsonify({"error": shipping_error}), 400
        total = total + shipping_cost

        cursor = conn.cursor()

        # Actualiza los datos de contacto de la cuenta con lo que puso en este pedido
        cursor.execute(
            "UPDATE customers SET name = %s, phone = %s, address = %s WHERE id = %s",
            (name, phone, delivery_address, customer_id),
        )

        try:
            low_stock_alerts = decrement_stock_or_raise(cursor, items)
        except InsufficientStockError as e:
            conn.rollback()
            cursor.close()
            conn.close()
            return jsonify({"error": e.message}), 409

        order_id = insert_order_and_items(
            cursor, customer_id, total, payment_method, delivery_method, delivery_address, items,
            coupon_code=applied_coupon["code"] if applied_coupon else None,
            discount_amount=discount_amount if applied_coupon else None,
            shipping_zone=shipping_zone_name, shipping_cost=shipping_cost,
        )

        if applied_coupon:
            try:
                cursor.execute("UPDATE coupons SET used_count = used_count + 1 WHERE id = %s", (applied_coupon["id"],))
            except MySQLError as e:
                if not _table_missing(e):
                    raise

        conn.commit()
        cursor.close()
        conn.close()
        send_low_stock_alerts(low_stock_alerts)

        # Tarjeta de crédito, débito y Mercado Pago van los tres al mismo
        # checkout alojado por Mercado Pago: ahí es MP quien pide el número
        # de tarjeta de forma segura, esta web nunca lo ve ni lo guarda.
        checkout_url = None
        METODOS_MP = {"Mercado Pago", "Tarjeta de crédito", "Tarjeta de débito"}
        if payment_method in METODOS_MP and mp_configured():
            checkout_url = crear_preferencia_mp(order_id, items, total)

        return jsonify({"order_id": order_id, "total": float(total), "checkout_url": checkout_url}), 201

    except MySQLError as e:
        app.logger.error(f"Error al crear pedido: {e}")
        return jsonify({"error": "No se pudo guardar el pedido"}), 500


@app.route("/api/orders/card-payment", methods=["POST"])
def create_order_card_payment():
    """Crea el pedido y cobra la tarjeta en el mismo paso, usando el token
    que generó el formulario embebido de Mercado Pago (Payment Brick) en
    el navegador del cliente. Ese token ya viene tokenizado por el SDK de
    MP — acá nunca se recibe ni se guarda el número de tarjeta real."""
    if not session.get("customer_id"):
        return jsonify({"error": "login_required"}), 401
    if not mp_card_form_configured():
        return jsonify({"error": "El pago con tarjeta no está disponible"}), 503

    data = request.get_json(force=True, silent=True) or {}

    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    delivery_method = data.get("delivery_method", "")
    delivery_address = data.get("delivery_address")
    items = data.get("items", [])
    token = data.get("token")
    payment_method_id = data.get("payment_method_id")
    issuer_id = data.get("issuer_id")
    installments = data.get("installments", 1)
    payer = data.get("payer") or {}

    if not name or not phone:
        return jsonify({"error": "Faltan nombre o teléfono"}), 400
    if not items:
        return jsonify({"error": "El carrito está vacío"}), 400
    if not token or not payment_method_id:
        return jsonify({"error": "Faltan datos de la tarjeta"}), 400

    item_subtotal = sum(Decimal(str(i["price"])) * int(i["qty"]) for i in items)
    total = item_subtotal
    customer_id = session["customer_id"]
    coupon_code_input = (data.get("coupon_code") or "").strip()
    shipping_zone_id = data.get("shipping_zone_id") if delivery_method == "Envío a domicilio" else None

    try:
        conn = get_connection()

        discount_amount = Decimal("0")
        applied_coupon = None
        if coupon_code_input:
            dcursor = conn.cursor(dictionary=True)
            applied_coupon, coupon_error = get_valid_coupon(dcursor, coupon_code_input)
            dcursor.close()
            if coupon_error:
                conn.close()
                return jsonify({"error": coupon_error}), 400
            discount_amount = (total * Decimal(str(applied_coupon["percent_off"])) / 100).quantize(Decimal("0.01"))
            total = total - discount_amount

        dcursor = conn.cursor(dictionary=True)
        shipping_zone_name, shipping_cost, shipping_error = resolve_shipping_cost(
            dcursor, delivery_method, shipping_zone_id, item_subtotal
        )
        dcursor.close()
        if shipping_error:
            conn.close()
            return jsonify({"error": shipping_error}), 400
        total = total + shipping_cost

        cursor = conn.cursor()

        cursor.execute(
            "UPDATE customers SET name = %s, phone = %s, address = %s WHERE id = %s",
            (name, phone, delivery_address, customer_id),
        )

        try:
            low_stock_alerts = decrement_stock_or_raise(cursor, items)
        except InsufficientStockError as e:
            conn.rollback()
            cursor.close()
            conn.close()
            return jsonify({"error": e.message}), 409

        order_id = insert_order_and_items(
            cursor, customer_id, total, "Tarjeta de crédito/débito", delivery_method, delivery_address, items,
            coupon_code=applied_coupon["code"] if applied_coupon else None,
            discount_amount=discount_amount if applied_coupon else None,
            shipping_zone=shipping_zone_name, shipping_cost=shipping_cost,
        )

        if applied_coupon:
            try:
                cursor.execute("UPDATE coupons SET used_count = used_count + 1 WHERE id = %s", (applied_coupon["id"],))
            except MySQLError as e:
                if not _table_missing(e):
                    raise

        conn.commit()
        cursor.close()
        conn.close()
        send_low_stock_alerts(low_stock_alerts)
    except MySQLError as e:
        app.logger.error(f"Error al crear pedido con tarjeta: {e}")
        return jsonify({"error": "No se pudo guardar el pedido"}), 500

    # El pedido ya está guardado (con el stock descontado) aunque el cobro
    # de acá para abajo falle — así no se pierde el pedido por un problema
    # de red con Mercado Pago; el estado queda en "pendiente" y se puede
    # resolver a mano desde el panel.
    try:
        payment_data = {
            "transaction_amount": float(total),
            "token": token,
            "description": f"Pedido #{order_id} - BrainSuplementos",
            "installments": int(installments),
            "payment_method_id": payment_method_id,
            "external_reference": str(order_id),
            "payer": {
                "email": payer.get("email") or "",
                "identification": payer.get("identification") or {},
            },
        }
        if issuer_id:
            payment_data["issuer_id"] = issuer_id

        result = mp_sdk.payment().create(payment_data)
        payment = result.get("response", {})
        mp_status = payment.get("status")  # approved, in_process, rejected, etc.
        mp_payment_id = payment.get("id")
        status_detail = payment.get("status_detail")

        new_status = {
            "approved": "pagado",
            "in_process": "pendiente",
            "pending": "pendiente",
            "rejected": "cancelado",
            "cancelled": "cancelado",
        }.get(mp_status, "pendiente")
        new_payment_status = "pagado" if new_status == "pagado" else "pendiente"
        new_cancelled = 1 if new_status == "cancelado" else 0

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET payment_status = %s, cancelled = %s, mp_payment_id = %s WHERE id = %s",
            (new_payment_status, new_cancelled, mp_payment_id, order_id),
        )
        conn.commit()
        cursor.close()
        conn.close()

        if new_status == "pagado":
            send_payment_confirmation_emails(order_id)

        return jsonify({
            "order_id": order_id,
            "status": new_status,
            "mp_status": mp_status,
            "status_detail": status_detail,
        }), 201
    except Exception as e:
        app.logger.error(f"Error al procesar el pago con tarjeta (pedido #{order_id}): {e}")
        return jsonify({
            "order_id": order_id,
            "status": "pendiente",
            "error": "El pedido se guardó pero no pudimos confirmar el pago. Te contactaremos para coordinarlo.",
        }), 502


# =============================================================
# MERCADO PAGO: retorno del checkout y webhook de notificaciones
# =============================================================
@app.route("/pago/exito")
def pago_exito():
    order_id = request.args.get("order_id")
    return render_template("pago_resultado.html", estado="exito", order_id=order_id)


@app.route("/pago/pendiente")
def pago_pendiente():
    order_id = request.args.get("order_id")
    return render_template("pago_resultado.html", estado="pendiente", order_id=order_id)


@app.route("/pago/error")
def pago_error():
    order_id = request.args.get("order_id")
    return render_template("pago_resultado.html", estado="error", order_id=order_id)


@app.route("/webhooks/mercadopago", methods=["POST", "GET"])
def mercadopago_webhook():
    """Mercado Pago llama a esta URL cada vez que cambia el estado de un
    pago. Para que funcione en tu compu local hace falta exponerla a
    internet (ej: con ngrok) — ver README. Si Mercado Pago no está
    configurado, no hace nada."""
    if not mp_configured():
        return "", 200

    payment_id = request.args.get("id") or request.args.get("data.id")
    topic = request.args.get("type") or request.args.get("topic")

    body = request.get_json(silent=True) or {}
    if not payment_id:
        payment_id = (body.get("data") or {}).get("id")
    if not topic:
        topic = body.get("type")

    try:
        if topic == "payment" and payment_id:
            payment_info = mp_sdk.payment().get(payment_id)
            payment = payment_info.get("response", {})
            order_id = payment.get("external_reference")
            mp_status = payment.get("status")  # approved, pending, rejected, etc.

            new_status = {"approved": "pagado", "rejected": "cancelado"}.get(mp_status)
            if order_id and new_status:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT payment_status, cancelled FROM orders WHERE id = %s", (order_id,))
                row = cursor.fetchone()
                if row:
                    previous_status = "cancelado" if row[1] else row[0]
                else:
                    previous_status = None

                if previous_status != new_status:
                    new_payment_status = "pagado" if new_status == "pagado" else "pendiente"
                    new_cancelled = 1 if new_status == "cancelado" else 0
                    cursor.execute(
                        "UPDATE orders SET payment_status = %s, cancelled = %s, mp_payment_id = %s WHERE id = %s",
                        (new_payment_status, new_cancelled, payment_id, order_id),
                    )
                    conn.commit()
                cursor.close()
                conn.close()

                # Solo mandamos los mails la primera vez que pasa a "pagado"
                # (Mercado Pago puede llamar al webhook más de una vez para
                # el mismo pago).
                if new_status == "pagado" and previous_status != "pagado":
                    send_payment_confirmation_emails(order_id)
    except Exception as e:
        app.logger.error(f"Error al procesar webhook de Mercado Pago: {e}")

    return "", 200


def get_order_full(order_id):
    """Devuelve un pedido con sus items y los datos del cliente, o None
    si no existe."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT o.*, c.name AS customer_name, c.email AS customer_email, c.phone AS customer_phone
           FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.id = %s""",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        cursor.close()
        conn.close()
        return None
    order["total"] = to_float(order["total"])

    cursor.execute(
        "SELECT product_name, unit_price, qty, flavor_name, weight_label FROM order_items WHERE order_id = %s",
        (order_id,),
    )
    items = cursor.fetchall()
    for it in items:
        it["unit_price"] = to_float(it["unit_price"])
    order["items"] = items

    cursor.close()
    conn.close()
    return order


def get_store_notification_email():
    """Mail al que avisar cuando hay una venta nueva: el de la cuenta de
    administrador (la que se creó la primera vez que se entró a /admin)."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT email FROM admins ORDER BY id LIMIT 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row["email"] if row else None
    except MySQLError:
        return None


def _format_order_items_text(items):
    lines = []
    for it in items:
        variant = ", ".join(filter(None, [
            it.get("flavor_name"),
            f"Peso {it['weight_label']}" if it.get("weight_label") else None,
        ]))
        lines.append(
            f"- {it['product_name']}{f' ({variant})' if variant else ''} "
            f"x{it['qty']} — ${it['unit_price']:.2f}"
        )
    return "\n".join(lines)


def send_payment_confirmation_emails(order_id):
    """Cuando Mercado Pago confirma un pago (tarjeta de crédito, débito o
    dinero en cuenta), le manda el comprobante de la compra al cliente y
    avisa por mail a la dueña de la tienda que vendió algo, para que pueda
    seguir el contacto por mail o WhatsApp. No hace nada si SMTP no está
    configurado (no rompe el resto del webhook)."""
    if not smtp_configured():
        return
    try:
        order = get_order_full(order_id)
        if not order:
            return
        items_text = _format_order_items_text(order["items"])
        entrega_line = f"Entrega: {order['delivery_method']}"
        if order.get("delivery_address"):
            entrega_line += f"\nDirección: {order['delivery_address']}"

        if order.get("customer_email"):
            send_email(
                order["customer_email"],
                f"Comprobante de tu compra · Pedido #{order_id} · BrainSuplementos",
                f"Hola {order['customer_name']},\n\n"
                f"¡Tu pago se acreditó! Este es el comprobante de tu compra:\n\n"
                f"Pedido #{order_id}\n{items_text}\n\n"
                f"Total: ${order['total']:.2f}\n"
                f"Método de pago: {order['payment_method']}\n"
                f"{entrega_line}\n\n"
                f"Gracias por tu compra. Ante cualquier consulta, escribinos por WhatsApp.",
            )

        admin_email = get_store_notification_email()
        if admin_email:
            send_email(
                admin_email,
                f"¡Vendiste algo! Pedido #{order_id} · BrainSuplementos",
                f"Se acreditó un pago nuevo en la tienda.\n\n"
                f"Pedido #{order_id}\n{items_text}\n\n"
                f"Total: ${order['total']:.2f}\n"
                f"Método de pago: {order['payment_method']}\n\n"
                f"Cliente: {order['customer_name']}\n"
                f"Teléfono: {order['customer_phone']}\n"
                f"Mail: {order.get('customer_email') or '(sin mail)'}\n"
                f"{entrega_line}\n\n"
                f"Podés contactar al cliente por mail o por WhatsApp para coordinar la entrega.",
            )
    except Exception as e:
        app.logger.error(f"No se pudo mandar el mail de comprobante/aviso de venta: {e}")


# =============================================================
# CUENTA DE ADMINISTRADOR: alta, login, recuperar contraseña
# =============================================================
@app.route("/admin/setup", methods=["GET", "POST"])
def admin_setup():
    # Si ya existe un administrador, esta pantalla no se usa más.
    if any_admin_exists():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        question = request.form.get("security_question", "").strip()
        answer = request.form.get("security_answer", "").strip()

        if not all([name, email, username, password, question, answer]):
            flash("Completá todos los campos")
        elif password != password2:
            flash("Las contraseñas no coinciden")
        elif len(password) < 6:
            flash("La contraseña tiene que tener al menos 6 caracteres")
        else:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO admins
                       (name, email, username, password_hash, security_question, security_answer_hash)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        name, email, username,
                        generate_password_hash(password),
                        question,
                        generate_password_hash(answer.lower()),
                    ),
                )
                conn.commit()
                admin_id = cursor.lastrowid
                cursor.close()
                conn.close()

                session["admin_id"] = admin_id
                session["admin_name"] = name
                flash("Cuenta creada correctamente")
                return redirect(url_for("admin_dashboard"))
            except MySQLError as e:
                flash(f"No se pudo crear la cuenta (¿mail o usuario repetido?): {e}")

    return render_template("admin_setup.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not any_admin_exists():
        return redirect(url_for("admin_setup"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM admins WHERE username = %s OR email = %s",
            (identifier, identifier),
        )
        admin = cursor.fetchone()
        cursor.close()
        conn.close()

        if admin and check_password_hash(admin["password_hash"], password):
            session["admin_id"] = admin["id"]
            session["admin_name"] = admin["name"]
            return redirect(url_for("admin_dashboard"))
        flash("Usuario/mail o contraseña incorrectos")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin/forgot", methods=["GET", "POST"])
def admin_forgot():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, security_question FROM admins WHERE username = %s OR email = %s",
            (identifier, identifier),
        )
        admin = cursor.fetchone()
        cursor.close()
        conn.close()

        if admin:
            session["reset_admin_id"] = admin["id"]
            return redirect(url_for("admin_forgot_question"))
        flash("No encontramos una cuenta con ese usuario o mail")

    return render_template("admin_forgot.html")


@app.route("/admin/forgot/pregunta", methods=["GET", "POST"])
def admin_forgot_question():
    admin_id = session.get("reset_admin_id")
    if not admin_id:
        return redirect(url_for("admin_forgot"))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
    admin = cursor.fetchone()
    cursor.close()
    conn.close()

    if not admin:
        session.pop("reset_admin_id", None)
        return redirect(url_for("admin_forgot"))

    if request.method == "POST":
        answer = request.form.get("security_answer", "").strip().lower()
        if check_password_hash(admin["security_answer_hash"], answer):
            session["reset_verified"] = True
            return redirect(url_for("admin_forgot_reset"))
        flash("Respuesta incorrecta")

    return render_template("admin_forgot_question.html", question=admin["security_question"])


@app.route("/admin/forgot/nueva", methods=["GET", "POST"])
def admin_forgot_reset():
    admin_id = session.get("reset_admin_id")
    if not admin_id or not session.get("reset_verified"):
        return redirect(url_for("admin_forgot"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if password != password2:
            flash("Las contraseñas no coinciden")
        elif len(password) < 6:
            flash("La contraseña tiene que tener al menos 6 caracteres")
        else:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE admins SET password_hash = %s WHERE id = %s",
                (generate_password_hash(password), admin_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
            session.pop("reset_admin_id", None)
            session.pop("reset_verified", None)
            flash("Contraseña actualizada, ya podés ingresar")
            return redirect(url_for("admin_login"))

    return render_template("admin_forgot_reset.html")


# =============================================================
# PANEL DE ADMINISTRACIÓN (/admin) — protegido con login
# =============================================================
@app.route("/admin")
@login_required
def admin_dashboard():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT p.*, cat.slug AS category, cat.name AS category_name "
            "FROM products p JOIN categories cat ON p.category_id = cat.id "
            "ORDER BY cat.sort_order, p.created_at DESC"
        )
        products = cursor.fetchall()

        stock_by_product = {}
        flavor_count_by_product = {}
        try:
            cursor.execute("SELECT id, product_id, stock FROM product_flavors")
            all_flavors = cursor.fetchall()
            flavor_count_by_product = {}
            for c in all_flavors:
                flavor_count_by_product[c["product_id"]] = flavor_count_by_product.get(c["product_id"], 0) + 1

            # Si un sabor tiene pesos propios (stock por combinación
            # sabor+peso), ESO es el stock real de ese sabor — el campo
            # .stock plano del sabor queda sin usarse en ese caso.
            flavor_weight_stock = {}
            if all_flavors:
                flavor_ids = [c["id"] for c in all_flavors]
                fplaceholders = ",".join(["%s"] * len(flavor_ids))
                try:
                    cursor.execute(
                        f"SELECT product_flavor_id, SUM(stock) AS total_stock FROM product_weights "
                        f"WHERE product_flavor_id IN ({fplaceholders}) GROUP BY product_flavor_id",
                        tuple(flavor_ids),
                    )
                    flavor_weight_stock = {row["product_flavor_id"]: row["total_stock"] for row in cursor.fetchall()}
                except MySQLError as e:
                    if not _table_missing(e):
                        raise

            for c in all_flavors:
                effective = flavor_weight_stock.get(c["id"], c["stock"])
                stock_by_product[c["product_id"]] = stock_by_product.get(c["product_id"], 0) + effective
        except MySQLError as e:
            if not _table_missing(e):
                raise
            app.logger.warning("Falta la migración de sabores (product_flavors) — ver README sección 6.")

        # Mismo criterio para pesos "sueltos" (sin sabor): si el producto
        # tiene pesos cargados, el stock "de verdad" es la suma de cada
        # peso, no el campo general del producto.
        weight_stock_by_product = {}
        weight_count_by_product = {}
        try:
            cursor.execute(
                "SELECT product_id, SUM(stock) AS total_stock FROM product_weights "
                "WHERE product_flavor_id IS NULL GROUP BY product_id"
            )
            weight_stock_by_product = {row["product_id"]: row["total_stock"] for row in cursor.fetchall()}
            cursor.execute(
                "SELECT product_id, COUNT(*) AS n FROM product_weights "
                "WHERE product_flavor_id IS NULL GROUP BY product_id"
            )
            weight_count_by_product = {row["product_id"]: row["n"] for row in cursor.fetchall()}
        except MySQLError as e:
            if not _table_missing(e):
                raise
            app.logger.warning("Falta la migración de pesos (product_weights) — ver README sección 21.")

        for p in products:
            p["price"] = to_float(p["price"])
            p["discount_percent"] = to_float(p["discount_percent"])
            p["flavor_count"] = flavor_count_by_product.get(p["id"], 0)
            p["weight_count"] = weight_count_by_product.get(p["id"], 0)
            if p["flavor_count"]:
                p["stock"] = stock_by_product.get(p["id"], 0)
            elif p["weight_count"]:
                p["stock"] = weight_stock_by_product.get(p["id"], 0)
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"Error al leer productos: {e}")
        products = []
    return render_template("admin_dashboard.html", products=products)


def get_categories(active_only=True):
    """Categorías del catálogo (Proteínas, Creatina, Barritas, etc.),
    cargadas y administradas desde /admin/categorias — no están fijas en
    el código, así que el equipo puede sumar, renombrar, pausar, borrar
    y reordenar categorías sin tocar nada de acá."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    where = "WHERE active = 1" if active_only else ""
    cursor.execute(f"SELECT * FROM categories {where} ORDER BY sort_order, name")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_category_by_slug(slug, active_only=False):
    for c in get_categories(active_only=active_only):
        if c["slug"] == slug:
            return c
    return None


def valid_category_slugs(include_todos=False):
    slugs = {c["slug"] for c in get_categories(active_only=False)}
    if include_todos:
        slugs.add("todos")
    return slugs


def slugify_subcategory(text):
    """Convierte un nombre de subcategoría (ej: "Whey y Isolate") en un
    slug simple sin espacios ni acentos (ej: "whey-y-isolate"), que es lo
    que se guarda en products.subcategory."""
    import unicodedata
    normalized = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "otros"


def get_subcategories(category_id=None, active_only=True):
    """Subcategorías cargadas desde /admin/subcategorias (ej: "Whey" e
    "Isolate" dentro de Proteínas). Si `category_id` no se pasa, trae las
    de todas las categorías juntas. Si la tabla todavía no existe (falta
    correr la migración), devuelve lista vacía en vez de romper la
    página."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    rows = []
    try:
        conditions = []
        params = []
        if category_id:
            conditions.append("category_id = %s")
            params.append(category_id)
        if active_only:
            conditions.append("active = 1")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cursor.execute(f"SELECT * FROM subcategories {where} ORDER BY sort_order, name", tuple(params))
        rows = cursor.fetchall()
    except MySQLError as e:
        if not _table_missing(e):
            raise
    cursor.close()
    conn.close()
    return rows


def get_subcategories_by_category_slug(category_slug, active_only=True):
    """Igual que get_subcategories, pero recibe el slug de la categoría
    (?category=proteinas) en vez de su id — lo usa la tienda pública."""
    cat = get_category_by_slug(category_slug) if category_slug else None
    if category_slug and not cat:
        return []
    return get_subcategories(cat["id"] if cat else None, active_only=active_only)


def fetch_stock_rows(categoria, q):
    """Arma la lista de filas de /admin/stock (una por producto, con sus
    sabores/pesos anidados) para el filtro dado. La usan tanto la vista
    como la exportación a PDF, para que ambas muestren siempre lo mismo."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    query = (
        "SELECT p.id, p.name, cat.slug AS category, cat.name AS category_name, p.image_url, p.stock "
        "FROM products p JOIN categories cat ON p.category_id = cat.id"
    )
    conditions = []
    params = []
    if categoria and categoria != "todos":
        conditions.append("cat.slug = %s")
        params.append(categoria)
    if q:
        conditions.append("p.name LIKE %s")
        params.append(f"%{q}%")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY p.name ASC"
    cursor.execute(query, tuple(params))
    products = cursor.fetchall()

    flavors_by_product = {}
    weights_by_product = {}
    if products:
        product_ids = [p["id"] for p in products]
        placeholders = ",".join(["%s"] * len(product_ids))
        all_flavors = []
        try:
            cursor.execute(
                f"SELECT id, product_id, flavor_name, flavor_color_hex, stock FROM product_flavors "
                f"WHERE product_id IN ({placeholders}) ORDER BY flavor_name ASC",
                tuple(product_ids),
            )
            all_flavors = cursor.fetchall()
            for c in all_flavors:
                c["sizes"] = []
                flavors_by_product.setdefault(c["product_id"], []).append(c)
        except MySQLError as e:
            if not _table_missing(e):
                raise

        # Pesos "sueltos" (sin sabor): solo estos van en la lista
        # plana del producto. Los que sí pertenecen a un sabor se
        # anidan dentro de ese sabor más abajo.
        try:
            cursor.execute(
                f"SELECT id, product_id, weight_label, stock FROM product_weights "
                f"WHERE product_id IN ({placeholders}) AND product_flavor_id IS NULL "
                f"ORDER BY weight_label ASC",
                tuple(product_ids),
            )
            for s in cursor.fetchall():
                weights_by_product.setdefault(s["product_id"], []).append(s)
        except MySQLError as e:
            if not _table_missing(e):
                raise

        # Pesos que sí pertenecen a un sabor: cada sabor tiene su
        # propio stock por peso (ej: 2 de Rosa viejo en L, 1 de
        # Beige en L), separado del de los demás sabores.
        if all_flavors:
            flavor_ids = [c["id"] for c in all_flavors]
            fplaceholders = ",".join(["%s"] * len(flavor_ids))
            try:
                cursor.execute(
                    f"SELECT id, product_flavor_id, weight_label, stock FROM product_weights "
                    f"WHERE product_flavor_id IN ({fplaceholders}) ORDER BY weight_label ASC",
                    tuple(flavor_ids),
                )
                weights_by_flavor = {}
                for s in cursor.fetchall():
                    weights_by_flavor.setdefault(s["product_flavor_id"], []).append(s)
                for c in all_flavors:
                    c["sizes"] = weights_by_flavor.get(c["id"], [])
            except MySQLError as e:
                if not _table_missing(e):
                    raise

    # Una fila por producto (no una por variante): sabores y pesos
    # quedan como listas adentro de esa misma fila. Si un sabor
    # tiene pesos propios, van anidados en c.sizes.
    rows = []
    for p in products:
        rows.append({
            "product_id": p["id"], "product_name": p["name"],
            "category": p["category"], "category_name": p["category_name"], "image_url": p["image_url"],
            "stock": p["stock"],
            "colors": flavors_by_product.get(p["id"], []),
            "sizes": weights_by_product.get(p["id"], []),
        })

    cursor.close()
    conn.close()
    return rows


@app.route("/admin/stock")
@login_required
def admin_stock():
    """Vista de stock en forma de lista: una sola fila por producto (sin
    repetir la foto), y si tiene sabores o pesos, todos esos campos de
    cantidad aparecen a la par dentro de esa misma fila. No trae nada de
    la base de datos hasta que se elija una categoría o se busque por
    nombre — igual criterio que /admin/pedidos."""
    categorias = get_categories(active_only=False)
    categoria = request.args.get("categoria")
    if categoria is not None and categoria not in valid_category_slugs(include_todos=True):
        categoria = None
    q = (request.args.get("q") or "").strip()
    filtered = categoria is not None or bool(q)

    rows = []
    if filtered:
        try:
            rows = fetch_stock_rows(categoria, q)
        except MySQLError as e:
            flash(f"Error al leer el stock: {e}")
            rows = []

    return render_template(
        "admin_stock.html", rows=rows, q=q, categoria=categoria, filtered=filtered, categorias=categorias,
    )


@app.route("/admin/stock/exportar")
@login_required
def admin_export_stock():
    """Exporta a PDF el stock del mismo filtro que se esté viendo en
    /admin/stock (categoría y/o búsqueda por nombre): nombre del producto,
    sabor, peso y cantidad — sin fotos."""
    categoria = request.args.get("categoria")
    if categoria is not None and categoria not in valid_category_slugs(include_todos=True):
        categoria = None
    q = (request.args.get("q") or "").strip()
    if categoria is None and not q:
        flash("Elegí primero una categoría o buscá un nombre para exportar")
        return redirect(url_for("admin_stock"))

    try:
        stock_rows = fetch_stock_rows(categoria, q)
    except MySQLError as e:
        flash(f"Error al leer el stock: {e}")
        return redirect(url_for("admin_stock"))

    rows = []
    for r in stock_rows:
        if r["colors"]:
            for c in r["colors"]:
                if c["sizes"]:
                    for s in c["sizes"]:
                        rows.append([r["product_name"], r["category_name"], c["flavor_name"], s["weight_label"], str(s["stock"])])
                else:
                    rows.append([r["product_name"], r["category_name"], c["flavor_name"], "—", str(c["stock"])])
        elif r["sizes"]:
            for s in r["sizes"]:
                rows.append([r["product_name"], r["category_name"], "—", s["weight_label"], str(s["stock"])])
        else:
            rows.append([r["product_name"], r["category_name"], "—", "—", str(r["stock"])])

    subtitulo = f"Categoría: {categoria or 'todas'}" + (f" · Búsqueda: \"{q}\"" if q else "")
    try:
        response = build_pdf_response(
            filename=f"stock_{date.today().isoformat()}.pdf",
            title="BrainSuplementos — Stock",
            subtitle=subtitulo,
            sections=[{
                "headers": ["Producto", "Categoría", "Sabor", "Peso", "Cantidad"],
                "rows": rows,
                "col_widths": [80, 35, 35, 25, 25],
            }],
        )
    except Exception as e:
        app.logger.error(f"Error al generar el PDF de stock: {e}")
        flash("No se pudo generar el PDF de stock. Probá de nuevo; si sigue fallando, avisame.")
        return redirect(url_for("admin_stock"))
    if response is None:
        flash("Para exportar a PDF hay que instalar la librería reportlab (pip install reportlab)")
        return redirect(url_for("admin_stock"))
    return response


def parse_discount_percent():
    """Lee discount_percent del formulario (ej: 20 = 20% off). Devuelve
    (valor_o_None, ok). Si no lo completaron, es válido y no hay descuento."""
    raw = (request.form.get("discount_percent") or "").strip()
    if not raw:
        return None, True
    try:
        percent = Decimal(raw)
    except Exception:
        flash("El % de descuento no es un número válido")
        return None, False
    if percent <= 0 or percent >= 100:
        flash("El % de descuento tiene que ser mayor a 0 y menor a 100")
        return None, False
    return percent, True


def parse_cost_price():
    """Precio de costo (opcional): si viene vacío o inválido, guardamos
    None — es un campo informativo para el reporte de ganancias, no afecta
    la venta ni el precio que ve el cliente."""
    raw = (request.form.get("cost_price") or "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
        return value if value >= 0 else None
    except Exception:
        return None


def parse_barcode():
    """Código de barras/SKU (opcional): lo escanea la lectora en Caja para
    encontrar el producto rápido. Vacío = None (no todos los productos
    necesitan tener uno)."""
    raw = (request.form.get("barcode") or "").strip()
    return raw or None


def parse_base_stock():
    """Lee el stock general del formulario de producto. Como ahora es
    opcional (el stock real puede vivir en sabores/pesos), si viene vacío
    o con algo raro asumimos 0 en vez de romper el guardado."""
    raw = (request.form.get("stock") or "").strip()
    try:
        value = int(raw)
        return value if value >= 0 else 0
    except (TypeError, ValueError):
        return 0


def parse_subcategory(category_id):
    """La subcategoría elegida tiene que ser una de las cargadas y activas
    para esa categoría en /admin/subcategorias. Si llega algo que no está
    en la lista (por ejemplo se borró esa subcategoría después de armar el
    formulario), guardamos None para que el filtro de la tienda no se
    rompa con valores sueltos. Devuelve el id de la subcategoría (o None)."""
    raw = (request.form.get("subcategory") or "").strip()
    if not raw:
        return None
    for s in get_subcategories(category_id):
        if s["slug"] == raw or str(s["id"]) == raw:
            return s["id"]
    return None


@app.route("/api/categories", methods=["GET"])
def list_categories():
    """Categorías activas del catálogo (Proteínas, Creatina, etc), en el
    orden en que se administran desde /admin/categorias. Las usa la
    tienda para armar las tarjetas de "Comprá por categoría" y los
    botones de filtro del catálogo, sin tener ninguna categoría fija
    escrita en el HTML."""
    try:
        rows = get_categories(active_only=True)
        return jsonify([
            {"id": c["id"], "name": c["name"], "slug": c["slug"], "icon": c["icon"], "image_url": c.get("image_url")}
            for c in rows
        ])
    except MySQLError as e:
        app.logger.error(f"Error al listar categorías: {e}")
        return jsonify([]), 500


@app.route("/api/menu-categories", methods=["GET"])
def list_menu_categories():
    """Categorías activas con sus subcategorías ya anidadas, en un solo
    pedido — la usa el mega-menú del header (desplegable de "Productos")
    para no tener que pedir las subcategorías una por una por cada
    categoría."""
    try:
        cats = get_categories(active_only=True)
        all_subs = get_subcategories()
        subs_by_category = {}
        for s in all_subs:
            subs_by_category.setdefault(s["category_id"], []).append({"name": s["name"], "slug": s["slug"]})
        return jsonify([
            {
                "id": c["id"], "name": c["name"], "slug": c["slug"], "icon": c["icon"],
                "subcategories": subs_by_category.get(c["id"], []),
            }
            for c in cats
        ])
    except MySQLError as e:
        app.logger.error(f"Error al listar categorías para el menú: {e}")
        return jsonify([])


@app.route("/api/subcategories", methods=["GET"])
def list_subcategories():
    """Subcategorías activas, opcionalmente filtradas por categoría
    (?category=proteinas, el slug). Las usa la tienda para armar los
    chips de filtro y el panel para el selector del formulario de
    producto."""
    category = request.args.get("category")
    rows = get_subcategories_by_category_slug(category) if category else get_subcategories()
    return jsonify([{"name": r["name"], "slug": r["slug"]} for r in rows])


@app.route("/admin/categorias")
@login_required
def admin_categories():
    categories = get_categories(active_only=False)
    return render_template("admin_categories.html", categories=categories)


@app.route("/admin/categorias/nueva", methods=["POST"])
@login_required
def admin_new_category():
    name = (request.form.get("name") or "").strip()
    icon = (request.form.get("icon") or "").strip()[:10]
    if not name:
        flash("Ponele un nombre a la categoría")
        return redirect(url_for("admin_categories"))
    image_url = save_uploaded_image(request.files.get("image"))
    slug = slugify_subcategory(name)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) FROM categories")
        next_order = cursor.fetchone()[0] + 1
        cursor.execute(
            "INSERT INTO categories (name, slug, icon, image_url, sort_order) VALUES (%s, %s, %s, %s, %s)",
            (name, slug, icon or None, image_url, next_order),
        )
        conn.commit()
        flash(f'Categoría "{name}" agregada')
    except MySQLError as e:
        if e.errno == 1062:
            flash("Ya existe una categoría con ese nombre (o uno muy parecido)")
        else:
            flash(f"No se pudo agregar: {e}")
    cursor.close()
    conn.close()
    return redirect(url_for("admin_categories"))


@app.route("/admin/categorias/<int:category_id>/editar", methods=["GET", "POST"])
@login_required
def admin_edit_category(category_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM categories WHERE id = %s", (category_id,))
    category = cursor.fetchone()
    cursor.close()

    if not category:
        conn.close()
        flash("Esa categoría no existe")
        return redirect(url_for("admin_categories"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        icon = (request.form.get("icon") or "").strip()[:10]
        if not name:
            flash("Ponele un nombre a la categoría")
            conn.close()
            return redirect(url_for("admin_edit_category", category_id=category_id))

        new_image = save_uploaded_image(request.files.get("image"))
        remove_image = request.form.get("remove_image") == "1"

        cursor = conn.cursor()
        try:
            if new_image:
                delete_image_file(category["image_url"])
                cursor.execute(
                    "UPDATE categories SET name = %s, icon = %s, image_url = %s WHERE id = %s",
                    (name, icon or None, new_image, category_id),
                )
            elif remove_image:
                delete_image_file(category["image_url"])
                cursor.execute(
                    "UPDATE categories SET name = %s, icon = %s, image_url = NULL WHERE id = %s",
                    (name, icon or None, category_id),
                )
            else:
                cursor.execute(
                    "UPDATE categories SET name = %s, icon = %s WHERE id = %s",
                    (name, icon or None, category_id),
                )
            conn.commit()
            flash(f'Categoría "{name}" actualizada')
        except MySQLError as e:
            flash(f"No se pudo guardar: {e}")
        cursor.close()
        conn.close()
        return redirect(url_for("admin_categories"))

    conn.close()
    return render_template("admin_category_edit.html", category=category)


@app.route("/admin/categorias/<int:category_id>/toggle", methods=["POST"])
@login_required
def admin_toggle_category(category_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT active FROM categories WHERE id = %s", (category_id,))
    row = cursor.fetchone()
    if row is not None:
        cursor.execute("UPDATE categories SET active = %s WHERE id = %s", (0 if row[0] else 1, category_id))
        conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("admin_categories"))


@app.route("/admin/categorias/<int:category_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_category(category_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT image_url FROM categories WHERE id = %s", (category_id,))
    existing = cursor.fetchone()
    cursor.close()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM categories WHERE id = %s", (category_id,))
        conn.commit()
        if existing:
            delete_image_file(existing["image_url"])
        flash("Categoría eliminada")
    except MySQLError as e:
        if e.errno == 1451:
            flash("No se puede borrar: todavía hay productos cargados en esta categoría. Movelos a otra categoría primero (o pausala en vez de borrarla).")
        else:
            flash(f"No se pudo eliminar: {e}")
    cursor.close()
    conn.close()
    return redirect(url_for("admin_categories"))


@app.route("/admin/subcategorias")
@login_required
def admin_subcategories():
    categories = get_categories(active_only=False)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT sub.*, cat.name AS category_name, cat.slug AS category_slug "
            "FROM subcategories sub JOIN categories cat ON sub.category_id = cat.id "
            "ORDER BY cat.sort_order, sub.sort_order, sub.name"
        )
        rows = cursor.fetchall()
    except MySQLError as e:
        if not _table_missing(e):
            raise
        rows = []
        flash("Corré migracion_subcategorias_admin.sql para poder administrar las subcategorías (ver README)")
    cursor.close()
    conn.close()
    grouped = {cat["id"]: [r for r in rows if r["category_id"] == cat["id"]] for cat in categories}
    return render_template("admin_subcategories.html", grouped=grouped, categories=categories)


@app.route("/admin/subcategorias/nueva", methods=["POST"])
@login_required
def admin_new_subcategory():
    try:
        category_id = int(request.form.get("category_id", ""))
    except (TypeError, ValueError):
        category_id = None
    name = (request.form.get("name") or "").strip()
    if not category_id or not name:
        flash("Completá la categoría y el nombre")
        return redirect(url_for("admin_subcategories"))
    slug = slugify_subcategory(name)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM subcategories WHERE category_id = %s", (category_id,)
        )
        next_order = cursor.fetchone()[0] + 1
        cursor.execute(
            "INSERT INTO subcategories (category_id, name, slug, sort_order) VALUES (%s, %s, %s, %s)",
            (category_id, name, slug, next_order),
        )
        conn.commit()
        flash(f'Subcategoría "{name}" agregada')
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_subcategorias_admin.sql antes de agregar subcategorías (ver README)")
        elif e.errno == 1062:
            flash(f'Ya existe una subcategoría con ese nombre en esta categoría')
        else:
            flash(f"No se pudo agregar: {e}")
    cursor.close()
    conn.close()
    return redirect(url_for("admin_subcategories"))


@app.route("/admin/subcategorias/<int:subcategory_id>/toggle", methods=["POST"])
@login_required
def admin_toggle_subcategory(subcategory_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT active FROM subcategories WHERE id = %s", (subcategory_id,))
    row = cursor.fetchone()
    if row is not None:
        cursor.execute("UPDATE subcategories SET active = %s WHERE id = %s", (0 if row[0] else 1, subcategory_id))
        conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("admin_subcategories"))


@app.route("/admin/subcategorias/<int:subcategory_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_subcategory(subcategory_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subcategories WHERE id = %s", (subcategory_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash("Subcategoría eliminada (los productos que ya la tenían puesta no se modifican, solo deja de aparecer para elegirla de nuevo)")
    return redirect(url_for("admin_subcategories"))


@app.route("/admin/products/new", methods=["GET", "POST"])
@login_required
def admin_new_product():
    categories = get_categories(active_only=False)
    if request.method == "POST":
        image_url = save_uploaded_image(request.files.get("image"))
        price = request.form["price"]
        try:
            category_id = int(request.form["category"])
        except (TypeError, ValueError, KeyError):
            category_id = None
        discount_percent, ok = parse_discount_percent()
        if not ok or not category_id:
            if not category_id:
                flash("Elegí una categoría (si no ves ninguna, cargá una primero en /admin/categorias)")
            return render_template("admin_product_form.html", product=None, flavor_count=0, weight_count=0, subcategories=get_subcategories(category_id), extra_images=[], categories=categories)
        try:
            conn = get_connection()
            cursor = conn.cursor()
            values = {
                "name": request.form["name"],
                "category_id": category_id,
                "subcategory_id": parse_subcategory(category_id),
                "price": price,
                "discount_percent": discount_percent,
                "cost_price": parse_cost_price(),
                "barcode": parse_barcode(),
                "stock": parse_base_stock(),
                "image_url": image_url,
                "description": request.form.get("description", ""),
                "active": 1 if request.form.get("active") == "on" else 0,
                "show_low_stock_badge": 1 if request.form.get("show_low_stock_badge") == "on" else 0,
            }
            required = {"name", "category_id", "price", "stock", "description", "active"}
            try:
                _, dropped = insert_with_optional_columns(cursor, "products", values, required)
            except MySQLError as e:
                if e.errno == 1062:
                    conn.rollback()
                    cursor.close()
                    conn.close()
                    flash("Ya existe otro producto con ese código de barras")
                    return render_template("admin_product_form.html", product=None, flavor_count=0, weight_count=0, subcategories=get_subcategories(category_id), extra_images=[], categories=categories)
                raise
            new_id = cursor.lastrowid
            conn.commit()
            cursor.close()
            conn.close()
            hint = migration_hint_for(dropped)
            flash(f"Producto agregado {hint}" if hint else "Producto agregado. Ahora agregá los sabores, pesos y fotos (o dejalo así si no tiene). La cantidad de stock se carga después desde Stock.")
            return redirect(url_for("admin_product_flavors", product_id=new_id))
        except MySQLError as e:
            flash(f"Error al guardar: {e}")
    default_category_id = categories[0]["id"] if categories else None
    return render_template("admin_product_form.html", product=None, flavor_count=0, weight_count=0, subcategories=get_subcategories(default_category_id), extra_images=[], categories=categories)


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_product(product_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        new_image = save_uploaded_image(request.files.get("image"))
        price = request.form["price"]
        try:
            category_id = int(request.form["category"])
        except (TypeError, ValueError, KeyError):
            category_id = None
        subcategory_id = parse_subcategory(category_id)
        discount_percent, ok = parse_discount_percent()
        if not ok or not category_id:
            cursor.close()
            conn.close()
            if not category_id:
                flash("Elegí una categoría")
            return redirect(url_for("admin_edit_product", product_id=product_id))
        cost_price = parse_cost_price()
        barcode = parse_barcode()
        description = request.form.get("description", "")
        active = 1 if request.form.get("active") == "on" else 0
        show_low_stock_badge = 1 if request.form.get("show_low_stock_badge") == "on" else 0
        name = request.form["name"]
        try:
            # El stock ya no se edita desde este formulario (se carga siempre
            # desde Stock), así que no lo tocamos acá para no pisarlo con 0.
            values = {
                "name": name, "category_id": category_id, "subcategory_id": subcategory_id,
                "price": price, "discount_percent": discount_percent, "cost_price": cost_price,
                "barcode": barcode, "description": description, "active": active,
                "show_low_stock_badge": show_low_stock_badge,
            }
            if new_image:
                values["image_url"] = new_image
            required = {"name", "category_id", "price", "description", "active"}
            try:
                dropped = update_with_optional_columns(cursor, "products", values, "id", product_id, required)
            except MySQLError as e:
                if e.errno == 1062:
                    conn.rollback()
                    cursor.close()
                    conn.close()
                    flash("Ya existe otro producto con ese código de barras")
                    return redirect(url_for("admin_edit_product", product_id=product_id))
                raise
            conn.commit()
            cursor.close()
            conn.close()
            check_stock_notify(product_id)
            hint = migration_hint_for(dropped)
            flash(f"Producto actualizado {hint}" if hint else "Producto actualizado")
            return redirect(url_for("admin_dashboard"))
        except MySQLError as e:
            flash(f"Error al actualizar: {e}")

    categories = get_categories(active_only=False)
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()

    # Para avisar en el formulario si el stock general ya no se usa porque
    # el producto tiene sabores o pesos cargados (el stock real vive ahí).
    flavor_count = 0
    weight_count = 0
    if product:
        try:
            cursor.execute("SELECT COUNT(*) AS n FROM product_flavors WHERE product_id = %s", (product_id,))
            flavor_count = cursor.fetchone()["n"]
        except MySQLError as e:
            if not _table_missing(e):
                raise
        try:
            cursor.execute("SELECT COUNT(*) AS n FROM product_weights WHERE product_id = %s", (product_id,))
            weight_count = cursor.fetchone()["n"]
        except MySQLError as e:
            if not _table_missing(e):
                raise

    cursor.close()
    conn.close()
    if product:
        product["price"] = to_float(product["price"])
        product["discount_percent"] = to_float(product["discount_percent"])
        if "cost_price" in product:
            product["cost_price"] = to_float(product["cost_price"])
    extra_images = get_images_for_product(product_id) if product else []
    default_category_id = categories[0]["id"] if categories else None
    return render_template(
        "admin_product_form.html", product=product, flavor_count=flavor_count, weight_count=weight_count,
        subcategories=get_subcategories(product["category_id"] if product else default_category_id),
        extra_images=extra_images, categories=categories,
    )


@app.route("/admin/products/<int:product_id>/toggle", methods=["POST"])
@login_required
def admin_toggle_product(product_id):
    """Pausa o reactiva un producto sin borrarlo: mientras está pausado
    (active=0) no aparece en la tienda ni en el catálogo, pero sigue
    guardado con todos sus sabores, pesos, fotos y pedidos asociados —
    así se puede volver a mostrar más adelante sin tener que cargarlo de
    nuevo."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT active FROM products WHERE id = %s", (product_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.close()
        conn.close()
        flash("No se encontró el producto")
        return redirect(url_for("admin_dashboard"))
    new_active = 0 if row[0] else 1
    cursor.execute("UPDATE products SET active = %s WHERE id = %s", (new_active, product_id))
    conn.commit()
    cursor.close()
    conn.close()
    flash("Producto reactivado y visible en la tienda" if new_active else "Producto sacado del catálogo (sigue guardado, lo podés reactivar cuando quieras)")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
@login_required
def admin_delete_product(product_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Producto eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar (puede tener pedidos asociados): {e}")
    return redirect(url_for("admin_dashboard"))


def get_products_for_set(set_id):
    """Productos que forman un combo, en el orden en que se cargaron.
    El precio de cada producto es el que se cargó puntualmente para ESTE
    combo (columna price de product_set_items) — se ignora por completo
    el precio y el descuento que tenga ese producto en el catálogo
    normal. Si todavía no corriste la migración que agrega esa columna,
    cae al precio de catálogo de siempre para no romper combos viejos."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT p.id, p.name, p.image_url, p.active, si.price AS set_price
               FROM product_set_items si
               JOIN products p ON p.id = si.product_id
               WHERE si.set_id = %s
               ORDER BY si.sort_order, si.id""",
            (set_id,),
        )
        items = cursor.fetchall()
        has_custom_price = True
    except MySQLError as e:
        if not _table_missing(e):
            raise
        cursor.execute(
            """SELECT p.id, p.name, p.price, p.discount_percent, p.image_url, p.active
               FROM product_set_items si
               JOIN products p ON p.id = si.product_id
               WHERE si.set_id = %s
               ORDER BY si.sort_order, si.id""",
            (set_id,),
        )
        items = cursor.fetchall()
        has_custom_price = False
    cursor.close()
    conn.close()
    for it in items:
        if has_custom_price:
            it["price"] = to_float(it.get("set_price")) if it.get("set_price") is not None else 0.0
            it["discount_percent"] = None
        else:
            it["price"] = to_float(it["price"])
            it["discount_percent"] = to_float(it["discount_percent"])
    return items


@app.route("/admin/combos")
@login_required
def admin_sets():
    sets = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM product_sets ORDER BY sort_order, created_at DESC")
        sets = cursor.fetchall()
        cursor.close()
        conn.close()
        for s in sets:
            s["items"] = get_products_for_set(s["id"])
    except MySQLError as e:
        if _table_missing(e):
            flash("Todavía no corriste la migración de combos (ver migracion_conjuntos.sql y README sección 11).")
        else:
            flash(f"Error al leer los combos: {e}")
        sets = []
    return render_template("admin_sets.html", sets=sets)


def parse_set_discount_price():
    """Precio especial opcional para el combo entero (por si la dueña
    lo quiere vender más barato que comprando cada producto por separado).
    Si lo dejan vacío, el combo se sigue mostrando con la suma normal
    de sus productos, sin ningún descuento."""
    raw = (request.form.get("discount_price") or "").strip()
    if not raw:
        return None, True
    try:
        price = Decimal(raw)
    except Exception:
        flash("El precio especial del combo no es un número válido")
        return None, False
    if price <= 0:
        flash("El precio especial del combo tiene que ser mayor a 0")
        return None, False
    return price, True


@app.route("/admin/combos/nuevo", methods=["GET", "POST"])
@login_required
def admin_new_set():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, image_url FROM products WHERE active = 1 ORDER BY name ASC")
        all_products = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"Error al leer productos: {e}")
        all_products = []

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        product_ids = request.form.getlist("product_ids")
        active = 1 if request.form.get("active") == "on" else 0
        image_url = save_uploaded_image(request.files.get("image"))

        discount_price, price_ok = parse_set_discount_price()

        if not name:
            flash("Ponele un nombre al combo")
        elif len(product_ids) < 2:
            flash("Elegí al menos 2 productos para armar el combo")
        elif not price_ok:
            pass
        else:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "INSERT INTO product_sets (name, description, image_url, discount_price, active) VALUES (%s, %s, %s, %s, %s)",
                        (name, description, image_url, discount_price, active),
                    )
                except MySQLError as e:
                    if not _table_missing(e):
                        raise
                    cursor.execute(
                        "INSERT INTO product_sets (name, description, image_url, active) VALUES (%s, %s, %s, %s)",
                        (name, description, image_url, active),
                    )
                    flash("Nota: corré migracion_precio_conjunto.sql para poder ponerle un precio especial al combo — ver README")

                set_id = cursor.lastrowid
                has_price_column = _column_exists("product_set_items", "price")
                for i, pid in enumerate(product_ids):
                    if has_price_column:
                        price_raw = (request.form.get(f"price_{pid}") or "").strip()
                        try:
                            item_price = Decimal(price_raw) if price_raw else Decimal("0")
                        except Exception:
                            item_price = Decimal("0")
                        cursor.execute(
                            "INSERT INTO product_set_items (set_id, product_id, sort_order, price) VALUES (%s, %s, %s, %s)",
                            (set_id, pid, i, item_price),
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO product_set_items (set_id, product_id, sort_order) VALUES (%s, %s, %s)",
                            (set_id, pid, i),
                        )
                conn.commit()
                cursor.close()
                conn.close()
                if not has_price_column:
                    flash("Combo creado (corré migracion_precio_combos.sql para poder cargar un precio propio por producto — ver README)")
                else:
                    flash("Combo creado")
                return redirect(url_for("admin_sets"))
            except MySQLError as e:
                flash(f"No se pudo crear el combo: {e}")

    return render_template("admin_set_form.html", set=None, all_products=all_products, selected_ids=[], selected_prices={})


@app.route("/admin/combos/<int:set_id>/editar", methods=["GET", "POST"])
@login_required
def admin_edit_set(set_id):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, image_url FROM products WHERE active = 1 ORDER BY name ASC")
        all_products = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"Error al leer productos: {e}")
        all_products = []

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        product_ids = request.form.getlist("product_ids")
        active = 1 if request.form.get("active") == "on" else 0
        new_image = save_uploaded_image(request.files.get("image"))

        discount_price, price_ok = parse_set_discount_price()

        if not name:
            flash("Ponele un nombre al combo")
        elif len(product_ids) < 2:
            flash("Elegí al menos 2 productos para armar el combo")
        elif not price_ok:
            pass
        else:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    if new_image:
                        cursor.execute(
                            "UPDATE product_sets SET name=%s, description=%s, image_url=%s, discount_price=%s, active=%s WHERE id=%s",
                            (name, description, new_image, discount_price, active, set_id),
                        )
                    else:
                        cursor.execute(
                            "UPDATE product_sets SET name=%s, description=%s, discount_price=%s, active=%s WHERE id=%s",
                            (name, description, discount_price, active, set_id),
                        )
                except MySQLError as e:
                    if not _table_missing(e):
                        raise
                    if new_image:
                        cursor.execute(
                            "UPDATE product_sets SET name=%s, description=%s, image_url=%s, active=%s WHERE id=%s",
                            (name, description, new_image, active, set_id),
                        )
                    else:
                        cursor.execute(
                            "UPDATE product_sets SET name=%s, description=%s, active=%s WHERE id=%s",
                            (name, description, active, set_id),
                        )
                    flash("Nota: corré migracion_precio_conjunto.sql para poder ponerle un precio especial al combo — ver README")

                cursor.execute("DELETE FROM product_set_items WHERE set_id = %s", (set_id,))
                has_price_column = _column_exists("product_set_items", "price")
                for i, pid in enumerate(product_ids):
                    if has_price_column:
                        price_raw = (request.form.get(f"price_{pid}") or "").strip()
                        try:
                            item_price = Decimal(price_raw) if price_raw else Decimal("0")
                        except Exception:
                            item_price = Decimal("0")
                        cursor.execute(
                            "INSERT INTO product_set_items (set_id, product_id, sort_order, price) VALUES (%s, %s, %s, %s)",
                            (set_id, pid, i, item_price),
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO product_set_items (set_id, product_id, sort_order) VALUES (%s, %s, %s)",
                            (set_id, pid, i),
                        )
                conn.commit()
                cursor.close()
                conn.close()
                if not has_price_column:
                    flash("Combo actualizado (corré migracion_precio_combos.sql para poder cargar un precio propio por producto — ver README)")
                else:
                    flash("Combo actualizado")
                return redirect(url_for("admin_sets"))
            except MySQLError as e:
                flash(f"No se pudo actualizar el combo: {e}")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM product_sets WHERE id = %s", (set_id,))
    product_set = cursor.fetchone()
    cursor.close()
    conn.close()
    if not product_set:
        flash("No encontramos ese combo")
        return redirect(url_for("admin_sets"))

    items = get_products_for_set(set_id)
    selected_ids = [it["id"] for it in items]
    selected_prices = {it["id"]: it["price"] for it in items}
    return render_template(
        "admin_set_form.html", set=product_set, all_products=all_products,
        selected_ids=selected_ids, selected_prices=selected_prices,
    )


@app.route("/admin/combos/<int:set_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_set(set_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM product_sets WHERE id = %s", (set_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Combo eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar: {e}")
    return redirect(url_for("admin_sets"))


# =============================================================
# CUPONES DE DESCUENTO (panel admin)
# =============================================================
@app.route("/admin/cupones")
@login_required
def admin_coupons():
    coupons = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM coupons ORDER BY created_at DESC")
        coupons = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if _table_missing(e):
            flash("Todavía no corriste la migración de cupones (ver migracion_funciones_nuevas.sql y README).")
        else:
            flash(f"Error al leer los cupones: {e}")
        coupons = []
    return render_template("admin_coupons.html", coupons=coupons, today=date.today())


@app.route("/admin/cupones/nuevo", methods=["POST"])
@login_required
def admin_new_coupon():
    code = (request.form.get("code") or "").strip().upper()
    percent_off = request.form.get("percent_off")
    expires_at = request.form.get("expires_at") or None
    usage_limit = request.form.get("usage_limit") or None

    if not code:
        flash("Ponele un código al cupón")
        return redirect(url_for("admin_coupons"))
    try:
        percent_off = Decimal(percent_off)
        if percent_off <= 0 or percent_off > 100:
            raise ValueError
    except Exception:
        flash("El % de descuento tiene que ser un número entre 1 y 100")
        return redirect(url_for("admin_coupons"))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO coupons (code, percent_off, expires_at, usage_limit)
               VALUES (%s, %s, %s, %s)""",
            (code, percent_off, expires_at, usage_limit),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Cupón «{code}» creado")
    except MySQLError as e:
        if e.errno == 1062:
            flash(f"Ya existe un cupón con el código «{code}»")
        elif _table_missing(e):
            flash("Corré migracion_funciones_nuevas.sql para poder crear cupones — ver README")
        else:
            flash(f"No se pudo crear el cupón: {e}")
    return redirect(url_for("admin_coupons"))


@app.route("/admin/cupones/<int:coupon_id>/toggle", methods=["POST"])
@login_required
def admin_toggle_coupon(coupon_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE coupons SET active = NOT active WHERE id = %s", (coupon_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo actualizar: {e}")
    return redirect(url_for("admin_coupons"))


@app.route("/admin/cupones/<int:coupon_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_coupon(coupon_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM coupons WHERE id = %s", (coupon_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Cupón eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar: {e}")
    return redirect(url_for("admin_coupons"))


# =============================================================
# POPUP DE BIENVENIDA: lista de quienes dejaron nombre/mail/cumpleaños
# a cambio del cupón de la primera compra.
# =============================================================
@app.route("/admin/bienvenida")
@login_required
def admin_welcome_signups():
    signups = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM welcome_signups ORDER BY created_at DESC")
        signups = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if _table_missing(e):
            flash("Todavía no corriste la migración del popup de bienvenida (ver migracion_bienvenida.sql y README).")
        else:
            flash(f"Error al leer los registros: {e}")
        signups = []
    return render_template("admin_welcome_signups.html", signups=signups)


@app.route("/admin/bienvenida/<int:signup_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_welcome_signup(signup_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM welcome_signups WHERE id = %s", (signup_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Registro eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar: {e}")
    return redirect(url_for("admin_welcome_signups"))


@app.route("/admin/bienvenida/exportar")
@login_required
def admin_export_welcome_signups():
    """Descarga un CSV con nombre/mail/cumpleaños de todos los que se
    anotaron — útil para mandarles ofertas de cumpleaños o novedades."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM welcome_signups ORDER BY created_at DESC")
        signups = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo exportar: {e}")
        return redirect(url_for("admin_welcome_signups"))

    lines = ["Nombre,Email,Cumpleaños,Cupón,Fecha de registro"]
    for s in signups:
        birthday = s["birthday"].strftime("%d/%m/%Y") if s.get("birthday") else ""
        created = s["created_at"].strftime("%d/%m/%Y %H:%M") if s.get("created_at") else ""
        row = [s["name"], s["email"], birthday, s.get("coupon_code") or "", created]
        lines.append(",".join(f'"{str(v).replace(chr(34), chr(34)*2)}"' for v in row))
    csv_data = "﻿" + "\n".join(lines)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=suscriptores_bienvenida.csv"},
    )


# =============================================================
# ENVÍOS: zonas de envío con costo real (reemplaza la vista previa que
# no cobraba nada — ahora el precio que carga la dueña acá es el que se
# le cobra de verdad al cliente en el checkout).
# =============================================================
@app.route("/admin/envios")
@login_required
def admin_shipping_zones():
    zones = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM shipping_zones ORDER BY sort_order ASC, id ASC")
        zones = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if _table_missing(e):
            flash("Todavía no corriste la migración de envíos (ver migracion_envios.sql y README).")
        else:
            flash(f"Error al leer las zonas de envío: {e}")
        zones = []
    return render_template("admin_shipping_zones.html", zones=zones)


@app.route("/admin/envios/nuevo", methods=["POST"])
@login_required
def admin_new_shipping_zone():
    name = (request.form.get("name") or "").strip()
    price = request.form.get("price")
    free_from = request.form.get("free_from") or None
    sort_order = request.form.get("sort_order") or 0

    if not name:
        flash("Ponele un nombre a la zona (ej: CABA, GBA, Interior)")
        return redirect(url_for("admin_shipping_zones"))
    try:
        price = Decimal(price)
        if price < 0:
            raise ValueError
    except Exception:
        flash("El precio de envío tiene que ser un número válido")
        return redirect(url_for("admin_shipping_zones"))

    if free_from is not None:
        try:
            free_from = Decimal(free_from)
        except Exception:
            flash("El monto de 'envío gratis a partir de' no es un número válido")
            return redirect(url_for("admin_shipping_zones"))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO shipping_zones (name, price, free_from, sort_order)
               VALUES (%s, %s, %s, %s)""",
            (name, price, free_from, sort_order or 0),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Zona «{name}» agregada")
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_envios.sql para poder crear zonas de envío — ver README")
        else:
            flash(f"No se pudo crear la zona: {e}")
    return redirect(url_for("admin_shipping_zones"))


@app.route("/admin/envios/<int:zone_id>/toggle", methods=["POST"])
@login_required
def admin_toggle_shipping_zone(zone_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE shipping_zones SET active = NOT active WHERE id = %s", (zone_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo actualizar: {e}")
    return redirect(url_for("admin_shipping_zones"))


@app.route("/admin/envios/<int:zone_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_shipping_zone(zone_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM shipping_zones WHERE id = %s", (zone_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Zona eliminada")
    except MySQLError as e:
        flash(f"No se pudo eliminar: {e}")
    return redirect(url_for("admin_shipping_zones"))


@app.route("/api/shipping-zones")
def list_shipping_zones():
    """Zonas de envío activas, para mostrar en el paso de entrega del
    checkout con el precio real (o "Envío gratis" si el pedido ya supera
    el mínimo de esa zona)."""
    zones = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, price, free_from FROM shipping_zones "
            "WHERE active = 1 ORDER BY sort_order ASC, id ASC"
        )
        zones = cursor.fetchall()
        cursor.close()
        conn.close()
        for z in zones:
            z["price"] = to_float(z["price"])
            z["free_from"] = to_float(z["free_from"]) if z["free_from"] is not None else None
    except MySQLError as e:
        if not _table_missing(e):
            app.logger.error(f"Error al leer zonas de envío: {e}")
        zones = []
    return jsonify(zones)


# Rangos de fecha para no traer toda la tabla de pedidos de una: cada uno
# devuelve desde cuándo mostrar pedidos (None = sin límite, "todos").
ORDER_RANGES = ("hoy", "semana", "mes", "todos")

def get_order_range_start(rango):
    hoy = date.today()
    if rango == "hoy":
        return datetime.combine(hoy, dt_time.min)
    if rango == "semana":
        inicio_semana = hoy - timedelta(days=hoy.weekday())  # lunes de esta semana
        return datetime.combine(inicio_semana, dt_time.min)
    if rango == "mes":
        return datetime(hoy.year, hoy.month, 1)
    return None  # "todos"


def parse_order_range_params():
    """Lee y valida rango/desde/hasta de la URL (?rango=hoy o ?desde=...&
    hasta=...). Se usa tanto en /admin/pedidos como en la exportación a
    Excel, para que ambos filtren exactamente igual."""
    rango = request.args.get("rango")
    if rango is not None and rango not in ORDER_RANGES:
        rango = None

    desde_str = (request.args.get("desde") or "").strip()
    hasta_str = (request.args.get("hasta") or "").strip()
    custom_range = bool(desde_str or hasta_str)

    desde_dt = None
    hasta_dt = None
    date_error = False
    if custom_range:
        # El rango de fechas a mano tiene prioridad sobre las pestañas
        # rápidas: si cargó algo acá, ignoramos "rango".
        rango = None
        try:
            if desde_str:
                desde_dt = datetime.combine(datetime.strptime(desde_str, "%Y-%m-%d").date(), dt_time.min)
            if hasta_str:
                hasta_dt = datetime.combine(datetime.strptime(hasta_str, "%Y-%m-%d").date(), dt_time.max)
        except ValueError:
            date_error = True

    filtered = rango is not None or custom_range
    return {
        "rango": rango, "desde_str": desde_str, "hasta_str": hasta_str,
        "custom_range": custom_range, "desde_dt": desde_dt, "hasta_dt": hasta_dt,
        "date_error": date_error, "filtered": filtered,
    }


def fetch_orders_in_range(custom_range, desde_dt, hasta_dt, rango):
    """Trae los pedidos (con sus items) que caen dentro del filtro ya
    parseado por parse_order_range_params(). Puede levantar MySQLError."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    base_select = """
        SELECT o.id, o.payment_status, o.delivery_status, o.cancelled, o.total, o.payment_method, o.delivery_method,
               o.delivery_address, o.created_at, c.name AS customer_name, c.phone AS customer_phone{extra}
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
    """
    conditions = []
    params = []
    if custom_range:
        if desde_dt is not None:
            conditions.append("o.created_at >= %s")
            params.append(desde_dt)
        if hasta_dt is not None:
            conditions.append("o.created_at <= %s")
            params.append(hasta_dt)
    elif rango is not None:
        desde = get_order_range_start(rango)
        if desde is not None:
            conditions.append("o.created_at >= %s")
            params.append(desde)
    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    order_clause = " ORDER BY o.created_at DESC"

    try:
        query = base_select.format(extra=", o.shipping_zone, o.shipping_cost") + where_clause + order_clause
        cursor.execute(query, tuple(params))
        orders = cursor.fetchall()
        for o in orders:
            o["shipping_cost"] = to_float(o["shipping_cost"]) if o.get("shipping_cost") is not None else 0.0
    except MySQLError as e:
        if not _table_missing(e):
            raise
        # Todavía no corrieron la migración de envíos — mismos pedidos,
        # sin esos dos campos (quedan como None/0 en vez de romper la lista).
        query = base_select.format(extra="") + where_clause + order_clause
        cursor.execute(query, tuple(params))
        orders = cursor.fetchall()
        for o in orders:
            o["shipping_zone"] = None
            o["shipping_cost"] = 0.0

    for o in orders:
        o["total"] = to_float(o["total"])
        o["items"] = []

    # Traemos todos los items de todos los pedidos en una sola consulta
    # (evita reutilizar el mismo cursor con consultas anidadas).
    if orders:
        order_ids = [o["id"] for o in orders]
        placeholders = ",".join(["%s"] * len(order_ids))
        cursor.execute(
            f"SELECT order_id, product_name, unit_price, qty, flavor_name, weight_label FROM order_items "
            f"WHERE order_id IN ({placeholders})",
            tuple(order_ids),
        )
        items_by_order = {}
        for it in cursor.fetchall():
            it["unit_price"] = to_float(it["unit_price"])
            items_by_order.setdefault(it["order_id"], []).append(it)
        for o in orders:
            o["items"] = items_by_order.get(o["id"], [])

    cursor.close()
    conn.close()
    return orders


@app.route("/admin/pedidos")
@login_required
def admin_orders():
    # Sin ningún filtro elegido en la URL todavía no se eligió nada: no
    # consultamos la base de datos y el template solo muestra los filtros.
    p = parse_order_range_params()

    orders = []
    if p["filtered"] and not p["date_error"]:
        try:
            orders = fetch_orders_in_range(p["custom_range"], p["desde_dt"], p["hasta_dt"], p["rango"])
        except MySQLError as e:
            flash(f"Error al leer pedidos: {e}")
            orders = []
    elif p["date_error"]:
        flash("Las fechas ingresadas no son válidas.")

    return render_template(
        "admin_orders.html",
        orders=orders,
        rango=p["rango"],
        filtered=p["filtered"],
        custom_range=p["custom_range"],
        desde=p["desde_str"],
        hasta=p["hasta_str"],
    )


def build_pdf_response(filename, title, subtitle, sections):
    """Arma un PDF simple (con reportlab) para los distintos "Exportar a
    PDF" del panel (Pedidos, Stock, Caja, Reportes, Estadísticas).

    `sections` es una lista de dicts, cada uno un bloque del PDF:
      {"heading": "Texto arriba de la tabla" (opcional, o None),
       "headers": ["Col1", "Col2", ...] (opcional: sin encabezado si no se pasa),
       "rows": [[...], [...], ...],
       "col_widths": [...] (opcional, en mm)}
    Devuelve la respuesta Flask lista para el `return` de la vista, o
    None si no está instalada la librería (el llamador debe flashear el
    aviso y redirigir en ese caso)."""
    try:
        from xml.sax.saxutils import escape as _xml_escape

        from reportlab.lib import colors as rl_colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        return None

    def _cell_paragraph(value, style):
        # Las celdas se arman como Paragraph (no texto plano) para que el
        # texto largo se ajuste ("wrap") dentro del ancho de la columna en
        # vez de dibujarse por encima de las columnas vecinas. Se escapan
        # los caracteres especiales de XML antes de convertir los saltos
        # de línea en <br/>, que sí soporta Paragraph.
        text = "" if value is None else str(value)
        text = _xml_escape(text).replace("\n", "<br/>")
        return Paragraph(text, style)

    buffer = BytesIO()
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("PdfBody", parent=styles["Normal"], fontSize=8, leading=10)
    number_style = ParagraphStyle("PdfBodyRight", parent=body_style, alignment=TA_RIGHT)
    header_style = ParagraphStyle(
        "PdfHeader", parent=body_style, fontName="Helvetica-Bold",
        textColor=rl_colors.HexColor("#4a3728"),
    )
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=16 * mm, bottomMargin=14 * mm, leftMargin=14 * mm, rightMargin=14 * mm,
        title=title,
    )
    elements = [Paragraph(_xml_escape(title), styles["Title"])]
    if subtitle:
        elements.append(Paragraph(_xml_escape(subtitle), styles["Normal"]))
    elements.append(Spacer(1, 10))

    for section in sections:
        heading = section.get("heading")
        if heading:
            elements.append(Paragraph(_xml_escape(heading), styles["Heading3"]))
            elements.append(Spacer(1, 4))
        rows = section.get("rows")
        if rows:
            headers = section.get("headers") or []
            # La última columna de cada fila suele ser un monto ($...): se
            # alinea a la derecha para que se lea más claro.
            wrapped_rows = [
                [
                    _cell_paragraph(cell, number_style if i == len(row) - 1 and str(cell).strip().startswith("$") else body_style)
                    for i, cell in enumerate(row)
                ]
                for row in rows
            ]
            wrapped_headers = [_cell_paragraph(h, header_style) for h in headers] if headers else None
            data = ([wrapped_headers] + wrapped_rows) if wrapped_headers else wrapped_rows
            col_widths = [w * mm for w in section["col_widths"]] if section.get("col_widths") else None
            table = Table(data, colWidths=col_widths, repeatRows=1 if headers else 0)
            style_cmds = [
                ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#d8cdbf")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
            if headers:
                style_cmds += [
                    ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#efe3d3")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#faf5ec")]),
                ]
            table.setStyle(TableStyle(style_cmds))
            elements.append(table)
        elements.append(Spacer(1, 14))

    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.route("/admin/pedidos/exportar")
@login_required
def admin_export_orders():
    """Exporta a PDF los pedidos del mismo período que se esté viendo en
    /admin/pedidos (mismos parámetros ?rango= o ?desde=&hasta=)."""
    p = parse_order_range_params()
    if p["date_error"]:
        flash("Las fechas ingresadas no son válidas.")
        return redirect(url_for("admin_orders"))
    if not p["filtered"]:
        flash("Elegí primero un período para exportar")
        return redirect(url_for("admin_orders"))

    try:
        orders = fetch_orders_in_range(p["custom_range"], p["desde_dt"], p["hasta_dt"], p["rango"])
    except MySQLError as e:
        flash(f"Error al leer pedidos: {e}")
        return redirect(url_for("admin_orders"))

    try:
        rows = _build_orders_pdf_rows(orders)
    except Exception as e:
        app.logger.error(f"Error al armar el PDF de pedidos: {e}")
        flash("No se pudo generar el PDF de pedidos. Probá de nuevo; si sigue fallando, avisame.")
        return redirect(url_for("admin_orders"))

    subtitulo = f"Período: {p['rango']}" if p["rango"] else (
        f"Del {p['desde_str'] or '...'} al {p['hasta_str'] or '...'}" if p["custom_range"] else "Todos"
    )
    try:
        response = build_pdf_response(
            filename=f"pedidos_{p['rango'] or 'rango'}_{date.today().isoformat()}.pdf",
            title="BrainSuplementos — Pedidos",
            subtitle=subtitulo,
            sections=[{
                "headers": ["Pedido", "Fecha", "Cliente", "Producto", "Cant.", "Precio unit.", "Entrega", "Pago", "Estado", "Total"],
                "rows": rows,
                "col_widths": [14, 22, 32, 45, 10, 18, 42, 30, 20, 20],
            }],
        )
    except Exception as e:
        app.logger.error(f"Error al generar el PDF de pedidos: {e}")
        flash("No se pudo generar el PDF de pedidos. Probá de nuevo; si sigue fallando, avisame.")
        return redirect(url_for("admin_orders"))
    if response is None:
        flash("Para exportar a PDF hay que instalar la librería reportlab (pip install reportlab)")
        return redirect(url_for("admin_orders"))
    return response


def _build_orders_pdf_rows(orders):
    rows = []
    for o in orders:
        items = o["items"] or [{}]
        entrega = o["delivery_method"] or ""
        if o["delivery_address"]:
            entrega += f"\n{o['delivery_address']}"
        if o.get("shipping_zone"):
            entrega += f"\n{o['shipping_zone']} (${o.get('shipping_cost') or 0:.2f})"
        for i, it in enumerate(items):
            producto = it.get("product_name", "")
            variante = ", ".join(filter(None, [it.get("flavor_name"), it.get("weight_label")]))
            if variante:
                producto += f" ({variante})"
            rows.append([
                f"#{o['id']}" if i == 0 else "",
                o["created_at"].strftime("%d/%m/%Y %H:%M") if o["created_at"] and i == 0 else "",
                f"{o['customer_name']}\n{o['customer_phone'] or ''}" if i == 0 else "",
                producto,
                str(it.get("qty", "")),
                f"${it.get('unit_price', 0):.2f}" if it.get("unit_price") is not None else "",
                entrega if i == 0 else "",
                o["payment_method"] if i == 0 else "",
                order_status_label(o) if i == 0 else "",
                f"${o['total']:.2f}" if i == 0 else "",
            ])
    return rows


@app.route("/admin/clientes")
@login_required
def admin_customers():
    q = (request.args.get("q") or "").strip()
    customers = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        where = ""
        params = []
        if q:
            where = " WHERE c.name LIKE %s OR c.email LIKE %s OR c.phone LIKE %s"
            like = f"%{q}%"
            params = [like, like, like]
        try:
            query = f"""
                SELECT c.id, c.name, c.email, c.phone, c.address, c.auth_provider,
                       c.created_at, c.is_exclusive, c.discount_percent, COUNT(o.id) AS order_count
                FROM customers c
                LEFT JOIN orders o ON o.customer_id = c.id
                {where} GROUP BY c.id ORDER BY c.created_at DESC
            """
            cursor.execute(query, tuple(params))
            customers = cursor.fetchall()
            for c in customers:
                c["discount_percent"] = to_float(c["discount_percent"]) if c.get("discount_percent") is not None else 0
        except MySQLError as e:
            if not _table_missing(e):
                raise
            # Todavía no corriste la migración de clientes exclusivos.
            query = f"""
                SELECT c.id, c.name, c.email, c.phone, c.address, c.auth_provider,
                       c.created_at, COUNT(o.id) AS order_count
                FROM customers c
                LEFT JOIN orders o ON o.customer_id = c.id
                {where} GROUP BY c.id ORDER BY c.created_at DESC
            """
            cursor.execute(query, tuple(params))
            customers = cursor.fetchall()
            for c in customers:
                c["is_exclusive"] = 0
                c["discount_percent"] = 0
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"Error al leer clientes: {e}")
        customers = []
    return render_template("admin_customers.html", customers=customers, q=q)


@app.route("/admin/clientes/<int:customer_id>/exclusivo", methods=["POST"])
@login_required
def admin_update_customer_exclusive(customer_id):
    """Marca/desmarca a un cliente como exclusivo (ej: atleta sponsoreado)
    y le guarda el % de descuento que se le aplica automático cuando se lo
    elige en una venta de Caja."""
    is_exclusive = 1 if request.form.get("is_exclusive") == "1" else 0
    raw_pct = (request.form.get("discount_percent") or "0").replace(",", ".")
    try:
        discount_percent = max(0, min(100, float(raw_pct)))
    except ValueError:
        discount_percent = 0
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE customers SET is_exclusive = %s, discount_percent = %s WHERE id = %s",
            (is_exclusive, discount_percent, customer_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Cliente actualizado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el cliente: {e}")
    return redirect(url_for("admin_customers", q=request.form.get("q", "")))


@app.route("/admin/resenas")
@login_required
def admin_reviews():
    """Lista de todas las reseñas de todos los productos, para poder
    borrar alguna inapropiada. Si todavía no corriste la migración,
    se muestra vacío en vez de romper la página."""
    reviews = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT r.id, r.rating, r.comment, r.created_at,
                      p.id AS product_id, p.name AS product_name,
                      c.name AS customer_name
               FROM product_reviews r
               JOIN products p ON p.id = r.product_id
               JOIN customers c ON c.id = r.customer_id
               ORDER BY r.created_at DESC"""
        )
        reviews = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if not _table_missing(e):
            flash(f"Error al leer reseñas: {e}")
        reviews = []
    return render_template("admin_reviews.html", reviews=reviews)


@app.route("/admin/resenas/<int:review_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_review(review_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM product_reviews WHERE id = %s", (review_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Reseña eliminada")
    except MySQLError as e:
        flash(f"No se pudo eliminar: {e}")
    return redirect(url_for("admin_reviews"))


# =============================================================
# CUENTA CORRIENTE (fiado) — deuda de los clientes que compran a cuenta
# =============================================================

def get_customer_balances():
    """Devuelve una fila por cliente que alguna vez tuvo un cargo o pago
    (SUM(cargo) - SUM(pago) = saldo que te debe). Los que nunca usaron
    cuenta corriente ni aparecen acá."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT c.id, c.name, c.phone,
                  COALESCE(SUM(CASE WHEN m.movement_type = 'cargo' THEN m.amount ELSE 0 END), 0)
                  - COALESCE(SUM(CASE WHEN m.movement_type = 'pago' THEN m.amount ELSE 0 END), 0) AS balance
           FROM account_movements m
           JOIN customers c ON c.id = m.customer_id
           GROUP BY c.id
           ORDER BY balance DESC"""
    )
    rows = cursor.fetchall()
    for r in rows:
        r["balance"] = to_float(r["balance"])
    cursor.close()
    conn.close()
    return rows


@app.route("/admin/cuenta-corriente")
@login_required
def admin_cuenta_corriente():
    balances = []
    try:
        balances = get_customer_balances()
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_gastos_cuenta_pedidos.sql para poder usar Cuenta corriente (ver README)")
        else:
            flash(f"Error al leer cuenta corriente: {e}")
    total_deuda = sum(b["balance"] for b in balances)
    return render_template("admin_cuenta_corriente.html", balances=balances, total_deuda=total_deuda)


@app.route("/admin/cuenta-corriente/<int:customer_id>")
@login_required
def admin_cuenta_corriente_detalle(customer_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, phone, email FROM customers WHERE id = %s", (customer_id,))
    customer = cursor.fetchone()
    if not customer:
        cursor.close()
        conn.close()
        flash("Ese cliente no existe")
        return redirect(url_for("admin_cuenta_corriente"))
    cursor.execute(
        "SELECT * FROM account_movements WHERE customer_id = %s ORDER BY created_at DESC",
        (customer_id,),
    )
    movements = cursor.fetchall()
    balance = Decimal("0")
    for m in movements:
        m["amount"] = to_float(m["amount"])
        balance += Decimal(str(m["amount"])) * (1 if m["movement_type"] == "cargo" else -1)
    cursor.close()
    conn.close()
    return render_template(
        "admin_cuenta_corriente_detalle.html", customer=customer, movements=movements, balance=float(balance),
    )


@app.route("/admin/cuenta-corriente/<int:customer_id>/movimiento", methods=["POST"])
@login_required
def admin_nuevo_movimiento_cuenta(customer_id):
    movement_type = request.form.get("movement_type")
    if movement_type not in ("cargo", "pago"):
        flash("Tipo de movimiento inválido")
        return redirect(url_for("admin_cuenta_corriente_detalle", customer_id=customer_id))
    try:
        amount = Decimal(str(request.form.get("amount") or "0"))
    except Exception:
        amount = Decimal("0")
    if amount <= 0:
        flash("El monto tiene que ser mayor a 0")
        return redirect(url_for("admin_cuenta_corriente_detalle", customer_id=customer_id))
    description = (request.form.get("description") or "").strip() or None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO account_movements (customer_id, movement_type, amount, description) VALUES (%s,%s,%s,%s)",
            (customer_id, movement_type, amount, description),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Movimiento registrado")
    except MySQLError as e:
        flash(f"No se pudo registrar el movimiento: {e}")
    return redirect(url_for("admin_cuenta_corriente_detalle", customer_id=customer_id))


@app.route("/admin/api/clientes-buscar")
@login_required
def admin_search_customers():
    """Busca clientes registrados por nombre/teléfono, para elegir uno en
    Caja (aplicarle su % de exclusivo, o cargarle una venta a cuenta
    corriente)."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT id, name, phone, is_exclusive, discount_percent
               FROM customers WHERE name LIKE %s OR phone LIKE %s LIMIT 15""",
            (f"%{q}%", f"%{q}%"),
        )
        rows = cursor.fetchall()
        for r in rows:
            r["discount_percent"] = to_float(r["discount_percent"]) if r.get("discount_percent") is not None else 0
    except MySQLError as e:
        if not _table_missing(e):
            raise
        cursor.execute("SELECT id, name, phone FROM customers WHERE name LIKE %s OR phone LIKE %s LIMIT 15",
                        (f"%{q}%", f"%{q}%"))
        rows = cursor.fetchall()
        for r in rows:
            r["is_exclusive"] = 0
            r["discount_percent"] = 0
    cursor.close()
    conn.close()
    return jsonify(rows)


# =============================================================
# CAJA — ventas presenciales en el local (aparte de la tienda online)
# =============================================================

# Los gastos de Proveedores y de Servicios (luz, alquiler, wifi, sueldos)
# ahora se cargan aparte en /admin/gastos (tabla business_expenses), no
# acá. Esto de Caja queda solo para gastos chicos del día (comida,
# merienda, algún insumo puntual), que siguen viviendo en cash_expenses
# porque están atados a la caja de ese día.
EXPENSE_CATEGORIES = ("Comida/merienda", "Insumo menor", "Otro gasto chico")


def get_open_cash_register():
    """La caja abierta ahora mismo (si hay), o None. Si todavía no se
    corrió migracion_caja.sql, devuelve None en vez de romper la página."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    row = None
    try:
        cursor.execute("SELECT * FROM cash_registers WHERE status = 'abierta' ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
    except MySQLError as e:
        if not _table_missing(e):
            raise
    cursor.close()
    conn.close()
    return row


@app.route("/admin/caja")
@login_required
def admin_caja():
    """Pantalla principal de caja: si no hay ninguna abierta, invita a
    abrirla; si hay una, muestra las ventas y gastos de esta caja, el
    efectivo esperado (apertura + ventas en efectivo - gastos) y el
    buscador para vender directo sin salir de esta pantalla. El historial
    de cajas anteriores se muestra siempre acá mismo, en vez de quedar
    escondido detrás de un link aparte."""
    register = None
    sales = []
    expenses = []
    registers = []
    initial_products = []
    totals = {"ventas_efectivo": 0.0, "ventas_otras": 0.0, "gastos": 0.0, "esperado": 0.0}
    try:
        register = get_open_cash_register()
        if register:
            conn = get_connection()
            cursor = conn.cursor(dictionary=True)
            try:
                # Si la venta se cargó a un cliente registrado (sin nombre
                # libre), mostramos su nombre acá en vez de "Consumidor
                # final" — así se ve a quién se le vendió, no solo el ticket.
                cursor.execute(
                    """SELECT ps.*, c.name AS registered_customer_name
                       FROM pos_sales ps LEFT JOIN customers c ON c.id = ps.customer_id
                       WHERE ps.cash_register_id = %s ORDER BY ps.created_at DESC""",
                    (register["id"],),
                )
            except MySQLError as e:
                if not _table_missing(e):
                    raise
                cursor.execute(
                    "SELECT * FROM pos_sales WHERE cash_register_id = %s ORDER BY created_at DESC",
                    (register["id"],),
                )
            sales = cursor.fetchall()
            for s in sales:
                s["total"] = to_float(s["total"])
            cursor.execute(
                "SELECT * FROM cash_expenses WHERE cash_register_id = %s ORDER BY created_at DESC",
                (register["id"],),
            )
            expenses = cursor.fetchall()
            for e in expenses:
                e["amount"] = to_float(e["amount"])
            cursor.close()
            conn.close()

            # Las ventas canceladas (venta cargada por error) no suman en
            # los totales de la caja, pero se siguen mostrando en la lista
            # de abajo con su cartel de "Cancelada" para que quede el rastro.
            ventas_efectivo = sum(s["total"] for s in sales if s.get("status") != "cancelada" and s["payment_method"] == "Efectivo")
            ventas_otras = sum(s["total"] for s in sales if s.get("status") != "cancelada" and s["payment_method"] != "Efectivo")
            gastos = sum(e["amount"] for e in expenses)
            totals = {
                "ventas_efectivo": ventas_efectivo,
                "ventas_otras": ventas_otras,
                "gastos": gastos,
                "esperado": to_float(register["opening_amount"]) + ventas_efectivo - gastos,
            }
            register["opening_amount"] = to_float(register["opening_amount"])
            # El buscador de productos (para vender) solo hace falta cuando
            # hay una caja abierta — se manda ya resuelto desde acá para
            # que la pantalla lo muestre desde el primer instante.
            initial_products = _pos_search_products()
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_caja.sql para poder usar la Caja (ver README)")
        else:
            flash(f"Error al leer la caja: {e}")

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM cash_registers ORDER BY id DESC LIMIT 15")
        registers = cursor.fetchall()
        cursor.close()
        conn.close()
        for r in registers:
            r["opening_amount"] = to_float(r["opening_amount"])
            r["closing_amount"] = to_float(r["closing_amount"]) if r["closing_amount"] is not None else None
            r["expected_amount"] = to_float(r["expected_amount"]) if r["expected_amount"] is not None else None
            r["difference"] = to_float(r["difference"]) if r["difference"] is not None else None
    except MySQLError as e:
        if not _table_missing(e):
            flash(f"Error al leer el historial de caja: {e}")
        registers = []

    return render_template(
        "admin_caja.html", register=register, sales=sales, expenses=expenses,
        totals=totals, expense_categories=EXPENSE_CATEGORIES, registers=registers,
        initial_products=initial_products,
    )


@app.route("/admin/caja/exportar")
@login_required
def admin_export_caja():
    """Exporta a PDF las ventas y gastos de la caja abierta ahora mismo,
    con los mismos totales que se ven en /admin/caja."""
    try:
        register = get_open_cash_register()
    except MySQLError as e:
        flash(f"Error al leer la caja: {e}")
        return redirect(url_for("admin_caja"))
    if not register:
        flash("No hay ninguna caja abierta para exportar")
        return redirect(url_for("admin_caja"))

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """SELECT ps.*, c.name AS registered_customer_name
                   FROM pos_sales ps LEFT JOIN customers c ON c.id = ps.customer_id
                   WHERE ps.cash_register_id = %s ORDER BY ps.created_at DESC""",
                (register["id"],),
            )
        except MySQLError as e:
            if not _table_missing(e):
                raise
            cursor.execute(
                "SELECT * FROM pos_sales WHERE cash_register_id = %s ORDER BY created_at DESC",
                (register["id"],),
            )
        sales = cursor.fetchall()
        for s in sales:
            s["total"] = to_float(s["total"])
        cursor.execute(
            "SELECT * FROM cash_expenses WHERE cash_register_id = %s ORDER BY created_at DESC",
            (register["id"],),
        )
        expenses = cursor.fetchall()
        for e in expenses:
            e["amount"] = to_float(e["amount"])
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"Error al leer la caja: {e}")
        return redirect(url_for("admin_caja"))

    try:
        ventas_efectivo = sum(s["total"] for s in sales if s.get("status") != "cancelada" and s["payment_method"] == "Efectivo")
        ventas_otras = sum(s["total"] for s in sales if s.get("status") != "cancelada" and s["payment_method"] != "Efectivo")
        gastos = sum(e["amount"] for e in expenses)
        opening = to_float(register["opening_amount"])
        esperado = opening + ventas_efectivo - gastos

        sales_rows = [
            [
                s["created_at"].strftime("%H:%M"),
                s.get("customer_name") or s.get("registered_customer_name") or "Consumidor final",
                s["payment_method"],
                "Cancelada" if s.get("status") == "cancelada" else "Ok",
                f"${s['total']:.2f}",
            ]
            for s in sales
        ]
        expense_rows = [
            [e["created_at"].strftime("%H:%M"), e["category"], e["description"] or "—", f"${e['amount']:.2f}"]
            for e in expenses
        ]
        totales_rows = [
            ["Monto inicial", f"${opening:.2f}"],
            ["Ventas en efectivo", f"${ventas_efectivo:.2f}"],
            ["Ventas con otro medio", f"${ventas_otras:.2f}"],
            ["Gastos", f"${gastos:.2f}"],
            ["Efectivo esperado en caja", f"${esperado:.2f}"],
        ]

        response = build_pdf_response(
            filename=f"caja_{date.today().isoformat()}.pdf",
            title="BrainSuplementos — Caja",
            subtitle=f"Abierta desde {register['opened_at'].strftime('%d/%m/%Y %H:%M')}",
            sections=[
                {"heading": "Totales", "headers": None, "rows": totales_rows, "col_widths": [70, 40]},
                {"heading": "Ventas", "headers": ["Hora", "Cliente", "Medio de pago", "Estado", "Total"], "rows": sales_rows, "col_widths": [20, 55, 45, 25, 25]},
                {"heading": "Gastos", "headers": ["Hora", "Categoría", "Descripción", "Monto"], "rows": expense_rows, "col_widths": [20, 35, 75, 25]},
            ],
        )
    except Exception as e:
        app.logger.error(f"Error al generar el PDF de caja: {e}")
        flash("No se pudo generar el PDF de la caja. Probá de nuevo; si sigue fallando, avisame.")
        return redirect(url_for("admin_caja"))
    if response is None:
        flash("Para exportar a PDF hay que instalar la librería reportlab (pip install reportlab)")
        return redirect(url_for("admin_caja"))
    return response


@app.route("/admin/caja/abrir", methods=["POST"])
@login_required
def admin_abrir_caja():
    if get_open_cash_register():
        flash("Ya hay una caja abierta")
        return redirect(url_for("admin_caja"))
    try:
        opening_amount = Decimal(str(request.form.get("opening_amount") or "0"))
        if opening_amount < 0:
            opening_amount = Decimal("0")
    except Exception:
        opening_amount = Decimal("0")
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO cash_registers (opening_amount) VALUES (%s)", (opening_amount,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Caja abierta")
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_caja.sql antes de abrir la caja (ver README)")
        else:
            flash(f"No se pudo abrir la caja: {e}")
    return redirect(url_for("admin_caja"))


@app.route("/admin/caja/cerrar", methods=["POST"])
@login_required
def admin_cerrar_caja():
    register = get_open_cash_register()
    if not register:
        flash("No hay ninguna caja abierta")
        return redirect(url_for("admin_caja"))
    try:
        closing_amount = Decimal(str(request.form.get("closing_amount") or "0"))
    except Exception:
        closing_amount = Decimal("0")
    notes = (request.form.get("notes") or "").strip()

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Las ventas canceladas no cuentan para el efectivo esperado.
            cursor.execute(
                "SELECT COALESCE(SUM(total),0) AS t FROM pos_sales WHERE cash_register_id = %s "
                "AND payment_method = 'Efectivo' AND status != 'cancelada'",
                (register["id"],),
            )
        except MySQLError as e:
            if not _table_missing(e):
                raise
            # Todavía no corrieron migracion_cancelar_venta.sql: seguimos
            # contando todas las ventas en efectivo como antes.
            cursor.execute(
                "SELECT COALESCE(SUM(total),0) AS t FROM pos_sales WHERE cash_register_id = %s AND payment_method = 'Efectivo'",
                (register["id"],),
            )
        ventas_efectivo = Decimal(str(cursor.fetchone()["t"]))
        cursor.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM cash_expenses WHERE cash_register_id = %s",
            (register["id"],),
        )
        gastos = Decimal(str(cursor.fetchone()["t"]))
        expected = Decimal(str(register["opening_amount"])) + ventas_efectivo - gastos
        difference = closing_amount - expected

        cursor2 = conn.cursor()
        cursor2.execute(
            """UPDATE cash_registers SET status='cerrada', closed_at=NOW(), closing_amount=%s,
               expected_amount=%s, difference=%s, notes=%s WHERE id=%s""",
            (closing_amount, expected, difference, notes, register["id"]),
        )
        conn.commit()
        cursor.close()
        cursor2.close()
        conn.close()
        signo = "sobran" if difference > 0 else ("faltan" if difference < 0 else "coincide")
        flash(f"Caja cerrada. {'Coincide con lo esperado' if difference == 0 else f'Diferencia: ${abs(difference):.2f} ({signo})'}")
    except MySQLError as e:
        flash(f"No se pudo cerrar la caja: {e}")
    return redirect(url_for("admin_caja_historial"))


@app.route("/admin/caja/gasto", methods=["POST"])
@login_required
def admin_nuevo_gasto():
    register = get_open_cash_register()
    category = request.form.get("category") or "Otro gasto chico"
    if category not in EXPENSE_CATEGORIES:
        category = "Otro gasto chico"
    description = (request.form.get("description") or "").strip()
    try:
        amount = Decimal(str(request.form.get("amount") or "0"))
    except Exception:
        amount = Decimal("0")
    if amount <= 0:
        flash("El monto del gasto tiene que ser mayor a 0")
        return redirect(url_for("admin_caja"))
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cash_expenses (cash_register_id, category, description, amount) VALUES (%s,%s,%s,%s)",
            (register["id"] if register else None, category, description, amount),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Gasto registrado")
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_caja.sql para poder registrar gastos (ver README)")
        else:
            flash(f"No se pudo registrar el gasto: {e}")
    return redirect(url_for("admin_caja"))


SERVICE_EXPENSE_CATEGORIES = ("Alquiler", "Luz", "Agua", "Internet/Wifi", "Sueldos", "Otro servicio")


@app.route("/admin/gastos")
@login_required
def admin_gastos():
    """Gastos del negocio aparte de los chicos de Caja: compras a
    proveedores (con o sin detalle de productos) y gastos fijos de
    servicios (alquiler, luz, wifi, sueldos, etc)."""
    expenses = []
    total_mes = 0.0
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT e.*, COUNT(i.id) AS item_count
               FROM business_expenses e
               LEFT JOIN business_expense_items i ON i.expense_id = e.id
               GROUP BY e.id ORDER BY e.expense_date DESC, e.id DESC LIMIT 200"""
        )
        expenses = cursor.fetchall()
        for e in expenses:
            e["amount"] = to_float(e["amount"])
        cursor.execute(
            """SELECT COALESCE(SUM(amount),0) AS t FROM business_expenses
               WHERE expense_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')"""
        )
        total_mes = to_float(cursor.fetchone()["t"])
        cursor.close()
        conn.close()
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_gastos_cuenta_pedidos.sql para poder usar Gastos (ver README)")
        else:
            flash(f"Error al leer gastos: {e}")

    all_products = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name FROM products WHERE active = 1 ORDER BY name")
        all_products = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError:
        all_products = []

    return render_template(
        "admin_gastos.html", expenses=expenses, total_mes=total_mes, all_products=all_products,
        service_categories=SERVICE_EXPENSE_CATEGORIES, today=date.today().isoformat(),
    )


@app.route("/admin/gastos/nuevo", methods=["POST"])
@login_required
def admin_nuevo_gasto_negocio():
    expense_type = request.form.get("expense_type")
    if expense_type not in ("proveedor", "servicio"):
        flash("Elegí si es una compra a proveedor o un gasto de servicio")
        return redirect(url_for("admin_gastos"))

    expense_date = (request.form.get("expense_date") or "").strip() or date.today().isoformat()
    description = (request.form.get("description") or "").strip() or None
    try:
        amount = Decimal(str(request.form.get("amount") or "0"))
    except Exception:
        amount = Decimal("0")
    if amount <= 0:
        flash("El monto tiene que ser mayor a 0")
        return redirect(url_for("admin_gastos"))

    provider_name = None
    service_category = None
    if expense_type == "proveedor":
        provider_name = (request.form.get("provider_name") or "").strip()
        if not provider_name:
            flash("Cargá el nombre del proveedor")
            return redirect(url_for("admin_gastos"))
    else:
        service_category = request.form.get("service_category") or "Otro servicio"
        if service_category not in SERVICE_EXPENSE_CATEGORIES:
            service_category = "Otro servicio"

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO business_expenses (expense_type, provider_name, service_category, description, amount, expense_date)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (expense_type, provider_name, service_category, description, amount, expense_date),
        )
        expense_id = cursor.lastrowid

        # Líneas de detalle (opcionales, solo tienen sentido para proveedor):
        # se ignora cualquier fila vacía, así no hace falta completar las 20
        # si no hay tiempo — con el monto total de arriba alcanza.
        item_product_ids = request.form.getlist("item_product_id")
        item_names = request.form.getlist("item_product_name")
        item_qtys = request.form.getlist("item_qty")
        item_costs = request.form.getlist("item_unit_cost")
        for pid, name, qty_raw, cost_raw in zip(item_product_ids, item_names, item_qtys, item_costs):
            name = (name or "").strip()
            if not name and not pid:
                continue
            try:
                qty = int(qty_raw)
                unit_cost = Decimal(str(cost_raw or "0"))
            except Exception:
                continue
            if qty <= 0:
                continue
            product_id = int(pid) if pid else None
            cursor.execute(
                """INSERT INTO business_expense_items (expense_id, product_id, product_name, qty, unit_cost)
                   VALUES (%s, %s, %s, %s, %s)""",
                (expense_id, product_id, name or f"Producto #{product_id}", qty, unit_cost),
            )
            # Si la línea está vinculada a un producto real del catálogo,
            # de paso le actualizamos el costo — así a futuro "Ganancias"
            # calcula el costo de mercadería con un dato más fresco, sin
            # tener que ir a tocarlo a mano en el producto.
            if product_id:
                cursor.execute("UPDATE products SET cost_price = %s WHERE id = %s", (unit_cost, product_id))

        conn.commit()
        cursor.close()
        conn.close()
        flash("Gasto registrado")
    except MySQLError as e:
        flash(f"No se pudo registrar el gasto: {e}")
    return redirect(url_for("admin_gastos"))


@app.route("/admin/gastos/<int:expense_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_gasto_negocio(expense_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM business_expenses WHERE id = %s", (expense_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Gasto eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar el gasto: {e}")
    return redirect(url_for("admin_gastos"))


@app.route("/admin/gastos/<int:expense_id>")
@login_required
def admin_gasto_detalle(expense_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM business_expenses WHERE id = %s", (expense_id,))
    expense = cursor.fetchone()
    if not expense:
        cursor.close()
        conn.close()
        flash("Ese gasto no existe")
        return redirect(url_for("admin_gastos"))
    expense["amount"] = to_float(expense["amount"])
    cursor.execute("SELECT * FROM business_expense_items WHERE expense_id = %s", (expense_id,))
    items = cursor.fetchall()
    for it in items:
        it["unit_cost"] = to_float(it["unit_cost"])
    cursor.close()
    conn.close()
    return render_template("admin_gasto_detalle.html", expense=expense, items=items)


@app.route("/admin/caja/historial")
@login_required
def admin_caja_historial():
    registers = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM cash_registers ORDER BY id DESC LIMIT 60")
        registers = cursor.fetchall()
        cursor.close()
        conn.close()
        for r in registers:
            r["opening_amount"] = to_float(r["opening_amount"])
            r["closing_amount"] = to_float(r["closing_amount"]) if r["closing_amount"] is not None else None
            r["expected_amount"] = to_float(r["expected_amount"]) if r["expected_amount"] is not None else None
            r["difference"] = to_float(r["difference"]) if r["difference"] is not None else None
    except MySQLError as e:
        if not _table_missing(e):
            flash(f"Error al leer el historial de caja: {e}")
    return render_template("admin_caja_historial.html", registers=registers)


@app.route("/admin/api/productos-buscar")
@login_required
def admin_search_products():
    q = (request.args.get("q") or "").strip()
    codigo = (request.args.get("codigo") or "").strip()
    return jsonify(_pos_search_products(q=q, codigo=codigo))


def _pos_search_products(q="", codigo=""):
    """Productos activos para armar una venta presencial, con sus
    sabores/pesos y stock real (lo usa /admin/caja/venta/nueva).

    - Sin ningún parámetro: trae todos los productos activos (hasta 200),
      para que se puedan elegir sin tener que escribir nada.
    - `q`: busca por nombre (parcial) o código de barras (exacto).
    - `codigo`: búsqueda exacta solo por código de barras — la usa el
      escaneo con lectora, que necesita saber si hay una coincidencia
      única para agregarlo directo al carrito."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    if codigo:
        try:
            cursor.execute(
                "SELECT * FROM products WHERE active = 1 AND barcode = %s LIMIT 1", (codigo,)
            )
            rows = cursor.fetchall()
        except MySQLError as e:
            if not _table_missing(e):
                raise
            rows = []  # todavía no corrieron migracion_codigo_barras.sql
    elif q:
        try:
            cursor.execute(
                "SELECT * FROM products WHERE active = 1 AND (name LIKE %s OR barcode = %s) ORDER BY name LIMIT 40",
                (f"%{q}%", q),
            )
            rows = cursor.fetchall()
        except MySQLError as e:
            if not _table_missing(e):
                raise
            cursor.execute(
                "SELECT * FROM products WHERE active = 1 AND name LIKE %s ORDER BY name LIMIT 40",
                (f"%{q}%",),
            )
            rows = cursor.fetchall()
    else:
        cursor.execute("SELECT * FROM products WHERE active = 1 ORDER BY name LIMIT 200")
        rows = cursor.fetchall()

    # Sabores y pesos de TODOS los productos de este resultado en 3
    # consultas en total (en vez de 2-3 consultas POR PRODUCTO, que era
    # lo que hacía que "Nueva venta" tardara mucho en mostrar la lista
    # completa: con 40 productos activos eran 100+ idas y vueltas a la
    # base, una por una).
    product_ids = [p["id"] for p in rows]
    colors_by_product = {}
    weights_by_flavor = {}
    weights_by_product = {}

    if product_ids:
        placeholders = ",".join(["%s"] * len(product_ids))
        try:
            cursor.execute(
                f"SELECT * FROM product_flavors WHERE product_id IN ({placeholders}) ORDER BY product_id, sort_order, id",
                tuple(product_ids),
            )
            flavor_rows = cursor.fetchall()
        except MySQLError as e:
            if not _table_missing(e):
                raise
            flavor_rows = []

        for c in flavor_rows:
            colors_by_product.setdefault(c["product_id"], []).append(c)

        flavor_ids = [c["id"] for c in flavor_rows]
        if flavor_ids:
            fplaceholders = ",".join(["%s"] * len(flavor_ids))
            try:
                cursor.execute(
                    f"SELECT * FROM product_weights WHERE product_flavor_id IN ({fplaceholders}) ORDER BY sort_order, id",
                    tuple(flavor_ids),
                )
                for s in cursor.fetchall():
                    weights_by_flavor.setdefault(s["product_flavor_id"], []).append(s)
            except MySQLError as e:
                if not _table_missing(e):
                    raise

        for c in flavor_rows:
            c["sizes"] = weights_by_flavor.get(c["id"], [])

        try:
            cursor.execute(
                f"SELECT * FROM product_weights WHERE product_id IN ({placeholders}) AND product_flavor_id IS NULL "
                f"ORDER BY sort_order, id",
                tuple(product_ids),
            )
            for s in cursor.fetchall():
                weights_by_product.setdefault(s["product_id"], []).append(s)
        except MySQLError as e:
            if not _table_missing(e):
                raise

    cursor.close()
    conn.close()

    result = []
    for p in rows:
        colors = colors_by_product.get(p["id"], [])
        sizes = weights_by_product.get(p["id"], [])
        # Igual que en la tienda: si un sabor tiene pesos propios, su
        # stock real es la suma de esos pesos (el stock plano del sabor
        # ya no se usa una vez que tiene pesos propios cargados) — si no
        # lo recalculamos acá, la búsqueda de Caja mostraba "stock 0"
        # aunque el peso sí tuviera unidades cargadas en Stock.
        for c in colors:
            if c.get("sizes"):
                c["stock"] = sum(s["stock"] for s in c["sizes"])
        total_stock = sum(c["stock"] for c in colors) if colors else p["stock"]
        hasDiscount = p["discount_percent"] is not None
        price = to_float(p["price"])
        final_price = round(price * (1 - to_float(p["discount_percent"]) / 100)) if hasDiscount else price
        result.append({
            "id": p["id"],
            "name": p["name"],
            "price": final_price,
            "image_url": p["image_url"],
            "stock": total_stock,
            "barcode": p.get("barcode"),
            "colors": [
                {
                    "id": c["id"], "name": c["flavor_name"], "hex": c["flavor_color_hex"], "stock": c["stock"],
                    "sizes": [{"id": s["id"], "name": s["weight_label"], "stock": s["stock"]} for s in c.get("sizes", [])],
                }
                for c in colors
            ],
            "sizes": [{"id": s["id"], "name": s["weight_label"], "stock": s["stock"]} for s in sizes],
        })
    return result


@app.route("/admin/caja/venta/nueva", methods=["GET", "POST"])
@login_required
def admin_nueva_venta():
    register = get_open_cash_register()

    if request.method == "POST":
        if not register:
            return jsonify({"error": "Primero tenés que abrir la caja"}), 400
        data = request.get_json(force=True, silent=True) or {}
        raw_items = data.get("items") or []
        payment_method = (data.get("payment_method") or "Efectivo").strip() or "Efectivo"
        customer_name = (data.get("customer_name") or "").strip() or None

        if not raw_items:
            return jsonify({"error": "Agregá al menos un producto"}), 400

        try:
            conn = get_connection()
            dcursor = conn.cursor(dictionary=True)

            # Cliente registrado (opcional): si es exclusivo, su % de
            # descuento se aplica acá mismo del lado del servidor (no
            # confiamos en lo que mande el navegador para esto), y si el
            # medio de pago es "Cuenta corriente" hace falta sí o sí un
            # cliente para poder cargarle el fiado.
            customer_id = data.get("customer_id")
            try:
                customer_id = int(customer_id) if customer_id else None
            except (TypeError, ValueError):
                customer_id = None
            customer_discount_percent = Decimal("0")
            if customer_id:
                dcursor.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
                customer_row = dcursor.fetchone()
                if not customer_row:
                    dcursor.close()
                    conn.close()
                    return jsonify({"error": "Cliente no encontrado"}), 400
                if customer_row.get("is_exclusive") and customer_row.get("discount_percent"):
                    customer_discount_percent = Decimal(str(customer_row["discount_percent"]))

            if payment_method == "Cuenta corriente" and not customer_id:
                dcursor.close()
                conn.close()
                return jsonify({"error": "Para vender a cuenta corriente primero elegí un cliente registrado"}), 400

            items = []
            total = Decimal("0")
            for it in raw_items:
                product_id = it.get("product_id")
                dcursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
                product = dcursor.fetchone()
                if not product:
                    dcursor.close()
                    conn.close()
                    return jsonify({"error": "Producto no encontrado"}), 400
                qty = max(1, int(it.get("qty") or 1))
                try:
                    unit_price = Decimal(str(it.get("unit_price")))
                except Exception:
                    unit_price = Decimal(str(product["price"]))
                if customer_discount_percent > 0:
                    unit_price = (unit_price * (Decimal("100") - customer_discount_percent) / Decimal("100")).quantize(Decimal("0.01"))
                total += unit_price * qty
                items.append({
                    "product_id": product_id, "name": product["name"], "qty": qty,
                    "flavor_id": it.get("flavor_id") or None, "flavor_name": it.get("flavor_name") or None,
                    "weight_id": it.get("weight_id") or None, "weight_label": it.get("weight_label") or None,
                    "unit_price": unit_price,
                })
            dcursor.close()

            cursor = conn.cursor()
            try:
                low_stock_alerts = decrement_stock_or_raise(cursor, items)
            except InsufficientStockError as e:
                conn.rollback()
                cursor.close()
                conn.close()
                return jsonify({"error": e.message}), 409

            try:
                cursor.execute(
                    "INSERT INTO pos_sales (cash_register_id, total, payment_method, customer_name, customer_id) VALUES (%s,%s,%s,%s,%s)",
                    (register["id"], total, payment_method, customer_name, customer_id),
                )
            except MySQLError as e:
                if not _table_missing(e):
                    raise
                # Todavía no corriste migracion_gastos_cuenta_pedidos.sql:
                # seguimos permitiendo vender, pero sin ligar la venta a
                # un cliente registrado.
                cursor.execute(
                    "INSERT INTO pos_sales (cash_register_id, total, payment_method, customer_name) VALUES (%s,%s,%s,%s)",
                    (register["id"], total, payment_method, customer_name),
                )
            sale_id = cursor.lastrowid
            for it in items:
                cursor.execute(
                    """INSERT INTO pos_sale_items (sale_id, product_id, product_name, unit_price, qty,
                       product_flavor_id, flavor_name, product_weight_id, weight_label)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (sale_id, it["product_id"], it["name"], it["unit_price"], it["qty"],
                     it["flavor_id"], it["flavor_name"], it["weight_id"], it["weight_label"]),
                )

            # Venta a cuenta corriente: se carga como deuda del cliente.
            if payment_method == "Cuenta corriente" and customer_id:
                try:
                    cursor.execute(
                        "INSERT INTO account_movements (customer_id, movement_type, amount, description, pos_sale_id) "
                        "VALUES (%s, 'cargo', %s, %s, %s)",
                        (customer_id, total, f"Venta en Caja #{sale_id}", sale_id),
                    )
                except MySQLError as e:
                    if not _table_missing(e):
                        raise
                    # Todavía no corriste la migración: la venta se guarda
                    # igual, pero avisamos que el fiado no quedó registrado.
                    conn.commit()
                    cursor.close()
                    conn.close()
                    send_low_stock_alerts(low_stock_alerts)
                    return jsonify({
                        "ok": True, "sale_id": sale_id,
                        "warning": "La venta se guardó, pero no se pudo cargar a cuenta corriente (corré migracion_gastos_cuenta_pedidos.sql).",
                    })

            conn.commit()
            cursor.close()
            conn.close()
            send_low_stock_alerts(low_stock_alerts)
            return jsonify({"ok": True, "sale_id": sale_id})
        except MySQLError as e:
            if _table_missing(e):
                return jsonify({"error": "Corré migracion_caja.sql antes de vender (ver README)"}), 500
            app.logger.error(f"Error al registrar venta presencial: {e}")
            return jsonify({"error": "No se pudo registrar la venta"}), 500

    # La pantalla de venta ahora vive adentro de /admin/caja (buscador +
    # carrito integrados ahí), así que un GET a esta URL vieja solo puede
    # llegar por un bookmark o un link guardado — lo mandamos de vuelta.
    return redirect(url_for("admin_caja"))


@app.route("/admin/caja/venta/<int:sale_id>/cancelar", methods=["POST"])
@login_required
def admin_cancel_pos_sale(sale_id):
    """Cancela una venta presencial cargada por error: le devuelve el
    stock vendido a cada producto/sabor/peso y marca la venta como
    'cancelada' para que deje de sumar en los totales de Caja y Reportes.
    No borra la venta ni el ticket, así queda el historial de que existió
    y se canceló."""
    next_url = request.form.get("next")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM pos_sales WHERE id = %s", (sale_id,))
        sale = cursor.fetchone()
        if not sale:
            cursor.close()
            conn.close()
            flash("Venta no encontrada")
            return redirect(next_url or url_for("admin_caja"))
        if sale.get("status") == "cancelada":
            cursor.close()
            conn.close()
            flash("Esa venta ya estaba cancelada")
            return redirect(next_url or url_for("admin_caja"))

        cursor.execute("SELECT * FROM pos_sale_items WHERE sale_id = %s", (sale_id,))
        items = cursor.fetchall()

        plain_cursor = conn.cursor()
        restore_stock_for_pos_sale_items(plain_cursor, items)
        plain_cursor.execute("UPDATE pos_sales SET status = 'cancelada' WHERE id = %s", (sale_id,))
        conn.commit()
        plain_cursor.close()
        cursor.close()
        conn.close()
        flash("Venta cancelada y stock devuelto")
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_cancelar_venta.sql para poder cancelar ventas (ver README)")
        else:
            flash(f"No se pudo cancelar la venta: {e}")
    return redirect(next_url or url_for("admin_caja"))


@app.route("/admin/caja/venta/<int:sale_id>/ticket")
@login_required
def admin_ticket_venta(sale_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM pos_sales WHERE id = %s", (sale_id,))
    sale = cursor.fetchone()
    if not sale:
        cursor.close()
        conn.close()
        flash("Venta no encontrada")
        return redirect(url_for("admin_caja"))
    sale["total"] = to_float(sale["total"])
    cursor.execute("SELECT * FROM pos_sale_items WHERE sale_id = %s", (sale_id,))
    items = cursor.fetchall()
    for it in items:
        it["unit_price"] = to_float(it["unit_price"])
    cursor.close()
    conn.close()
    return render_template("admin_ticket.html", sale=sale, items=items)


def compute_reportes(params):
    """Calcula el reporte de ganancias y gastos (ventas online + presenciales
    - gastos - costo de mercadería) para el rango/fechas de `params` (el
    dict que devuelve parse_order_range_params()). Lo usan tanto la vista
    de Reportes como su exportación a PDF, para que ambas den lo mismo."""
    # Un solo rango de fechas (desde/hasta como datetime, o None = sin
    # límite) que se aplica igual a pedidos online, ventas presenciales y
    # gastos, para que los tres números salgan del mismo período.
    desde_dt = None
    hasta_dt = None
    if params["custom_range"]:
        desde_dt = params["desde_dt"]
        hasta_dt = params["hasta_dt"]
    elif params["rango"] is not None:
        desde_dt = get_order_range_start(params["rango"])

    def date_filter(column):
        conditions = []
        values = []
        if desde_dt is not None:
            conditions.append(f"{column} >= %s")
            values.append(desde_dt)
        if hasta_dt is not None:
            conditions.append(f"{column} <= %s")
            values.append(hasta_dt)
        return conditions, values

    report = {
        "ventas_online": 0.0, "ventas_local": 0.0, "gastos": 0.0,
        "gastos_chicos": 0.0, "gastos_negocio": 0.0,
        "costo_mercaderia": 0.0, "costo_incompleto": False, "resultado": 0.0,
    }
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Ventas online (mismo criterio que Estadísticas: solo pedidos ya
        # cobrados y no cancelados)
        conditions, values = date_filter("created_at")
        conditions.append("payment_status = 'pagado'")
        conditions.append("cancelled = 0")
        where = " AND " + " AND ".join(conditions)
        cursor.execute(
            f"SELECT COALESCE(SUM(total),0) AS t FROM orders WHERE 1=1 {where}",
            tuple(values),
        )
        report["ventas_online"] = to_float(cursor.fetchone()["t"])

        try:
            # Ventas presenciales (las canceladas no cuentan; una venta
            # "Cuenta corriente" sí es una venta reconocida, aunque el
            # cliente todavía no la haya pagado en efectivo — ese saldo se
            # sigue viendo aparte en Cuenta corriente).
            conditions, values = date_filter("created_at")
            conditions.append("status != 'cancelada'")
            where = "WHERE " + " AND ".join(conditions)
            cursor.execute(f"SELECT COALESCE(SUM(total),0) AS t FROM pos_sales {where}", tuple(values))
            report["ventas_local"] = to_float(cursor.fetchone()["t"])

            # Gastos: los chicos del día a día (cash_expenses, cargados
            # desde Caja) más las compras a proveedores y los gastos de
            # servicios (business_expenses, cargados desde Gastos). Se
            # calculan por separado para que, si todavía no corriste la
            # migración de Gastos, los chicos de Caja se sigan sumando bien
            # en vez de perderse junto con el intento fallido.
            conditions, values = date_filter("created_at")
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            cursor.execute(f"SELECT COALESCE(SUM(amount),0) AS t FROM cash_expenses {where}", tuple(values))
            gastos_chicos = to_float(cursor.fetchone()["t"])

            gastos_negocio = 0.0
            try:
                conditions, values = date_filter("expense_date")
                where = "WHERE " + " AND ".join(conditions) if conditions else ""
                cursor.execute(f"SELECT COALESCE(SUM(amount),0) AS t FROM business_expenses {where}", tuple(values))
                gastos_negocio = to_float(cursor.fetchone()["t"])
            except MySQLError as e:
                if not _table_missing(e):
                    raise

            report["gastos"] = gastos_chicos + gastos_negocio
            report["gastos_chicos"] = gastos_chicos
            report["gastos_negocio"] = gastos_negocio

            # Costo de mercadería vendida: qty * cost_price de cada item
            # vendido (online + local) en el período, solo contando los
            # productos que tienen cost_price cargado (los que no, no suman
            # costo — por eso el resultado puede quedar marcado incompleto).
            conditions, values = date_filter("o.created_at")
            where = " AND " + " AND ".join(conditions) if conditions else ""
            cursor.execute(
                f"""SELECT COALESCE(SUM(oi.qty * p.cost_price),0) AS t
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    JOIN products p ON p.id = oi.product_id
                    WHERE o.payment_status = 'pagado' AND o.cancelled = 0 AND p.cost_price IS NOT NULL {where}""",
                tuple(values),
            )
            costo_online = to_float(cursor.fetchone()["t"])

            conditions, values = date_filter("ps.created_at")
            where = " AND " + " AND ".join(conditions) if conditions else ""
            cursor.execute(
                f"""SELECT COALESCE(SUM(psi.qty * p.cost_price),0) AS t
                    FROM pos_sale_items psi
                    JOIN pos_sales ps ON ps.id = psi.sale_id
                    JOIN products p ON p.id = psi.product_id
                    WHERE p.cost_price IS NOT NULL AND ps.status != 'cancelada' {where}""",
                tuple(values),
            )
            costo_local = to_float(cursor.fetchone()["t"])
            report["costo_mercaderia"] = costo_online + costo_local

            # Si hay algún producto activo sin cost_price cargado, el costo
            # (y por lo tanto la ganancia) puede quedar incompleto — se lo
            # avisamos a la dueña en vez de mostrar un número que parece
            # exacto pero no lo es.
            cursor.execute("SELECT COUNT(*) AS n FROM products WHERE active = 1 AND cost_price IS NULL")
            report["costo_incompleto"] = cursor.fetchone()["n"] > 0
        except MySQLError as e:
            if not _table_missing(e):
                raise

        cursor.close()
        conn.close()
        report["resultado"] = (
            report["ventas_online"] + report["ventas_local"] - report["gastos"] - report["costo_mercaderia"]
        )
    except MySQLError as e:
        flash(f"Error al calcular el reporte: {e}")

    return report


@app.route("/admin/reportes")
@login_required
def admin_reportes():
    """Ganancias y gastos: junta las ventas online (orders) con las
    presenciales (pos_sales) y les resta los gastos (cash_expenses) del
    mismo período. El costo de mercadería vendida solo se descuenta de
    los productos que tengan cargado products.cost_price — si falta en
    alguno, el resultado queda marcado como estimado."""
    params = parse_order_range_params()
    if params["date_error"]:
        flash("Revisá las fechas (formato AAAA-MM-DD)")
    report = compute_reportes(params)
    return render_template("admin_reportes.html", report=report, **params)


@app.route("/admin/reportes/exportar")
@login_required
def admin_export_reportes():
    """Exporta a PDF el reporte de ganancias y gastos del mismo período
    que se esté viendo en /admin/reportes."""
    params = parse_order_range_params()
    if params["date_error"]:
        flash("Revisá las fechas (formato AAAA-MM-DD)")
        return redirect(url_for("admin_reportes"))
    report = compute_reportes(params)

    subtitulo = f"Período: {params['rango']}" if params["rango"] else (
        f"Del {params['desde_str'] or '...'} al {params['hasta_str'] or '...'}" if params["custom_range"] else "Todos los períodos"
    )
    rows = [
        ["Ventas online", f"${report['ventas_online']:.2f}"],
        ["Ventas presenciales (Caja)", f"${report['ventas_local']:.2f}"],
        ["Gastos", f"${report['gastos']:.2f}"],
        ["  Gastos chicos (Caja)", f"${report['gastos_chicos']:.2f}"],
        ["  Proveedores y servicios", f"${report['gastos_negocio']:.2f}"],
        ["Costo de mercadería vendida" + (" (estimado, falta cargar costo en algún producto)" if report["costo_incompleto"] else ""), f"${report['costo_mercaderia']:.2f}"],
        ["Resultado", f"${report['resultado']:.2f}"],
    ]
    try:
        response = build_pdf_response(
            filename=f"reportes_{params['rango'] or 'periodo'}_{date.today().isoformat()}.pdf",
            title="BrainSuplementos — Ganancias y gastos",
            subtitle=subtitulo,
            sections=[{"headers": None, "rows": rows, "col_widths": [140, 40]}],
        )
    except Exception as e:
        app.logger.error(f"Error al generar el PDF de reportes: {e}")
        flash("No se pudo generar el PDF de reportes. Probá de nuevo; si sigue fallando, avisame.")
        return redirect(url_for("admin_reportes"))
    if response is None:
        flash("Para exportar a PDF hay que instalar la librería reportlab (pip install reportlab)")
        return redirect(url_for("admin_reportes"))
    return response


def compute_stats():
    """Calcula los números de /admin/estadisticas. Lo usan tanto la vista
    como su exportación a PDF, para que ambas den lo mismo."""
    stats = {
        "total_ingresos": 0.0,
        "por_estado": [],
        "top_productos": [],
        "por_mes": [],
    }
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT COALESCE(SUM(total), 0) AS total FROM orders "
            "WHERE payment_status = 'pagado' AND cancelled = 0"
        )
        stats["total_ingresos"] = to_float(cursor.fetchone()["total"])

        # El pago y la entrega son dos cosas independientes (y "cancelado"
        # es aparte de las dos), así que en vez de un único "estado" se
        # muestran los 5 conteos por separado.
        cursor.execute(
            """SELECT
                 SUM(payment_status = 'pendiente') AS pendientes,
                 SUM(payment_status = 'pagado') AS pagados,
                 SUM(delivery_status = 'no_entregado') AS no_entregados,
                 SUM(delivery_status = 'entregado') AS entregados,
                 SUM(cancelled = 1) AS cancelados
               FROM orders"""
        )
        counts = cursor.fetchone() or {}
        stats["por_estado"] = [
            {"status": "pendiente (pago)", "n": int(counts.get("pendientes") or 0)},
            {"status": "pagado", "n": int(counts.get("pagados") or 0)},
            {"status": "no entregado", "n": int(counts.get("no_entregados") or 0)},
            {"status": "entregado", "n": int(counts.get("entregados") or 0)},
            {"status": "cancelado", "n": int(counts.get("cancelados") or 0)},
        ]

        cursor.execute(
            """SELECT product_name, SUM(qty) AS total_qty
               FROM order_items GROUP BY product_name
               ORDER BY total_qty DESC LIMIT 5"""
        )
        stats["top_productos"] = cursor.fetchall()

        cursor.execute(
            """SELECT DATE_FORMAT(created_at, '%%Y-%%m') AS mes, SUM(total) AS total
               FROM orders WHERE payment_status = 'pagado' AND cancelled = 0
               GROUP BY mes ORDER BY mes DESC LIMIT 6"""
        )
        por_mes = cursor.fetchall()
        for m in por_mes:
            m["total"] = to_float(m["total"])
        stats["por_mes"] = list(reversed(por_mes))  # orden cronológico para el gráfico

        cursor.close()
        conn.close()

        max_mes = max((m["total"] for m in stats["por_mes"]), default=0)
        for m in stats["por_mes"]:
            m["pct"] = round((m["total"] / max_mes) * 100) if max_mes else 0
    except MySQLError as e:
        flash(f"Error al leer estadísticas: {e}")

    return stats


@app.route("/admin/estadisticas")
@login_required
def admin_stats():
    stats = compute_stats()
    return render_template("admin_stats.html", stats=stats)


@app.route("/admin/estadisticas/exportar")
@login_required
def admin_export_stats():
    """Exporta a PDF las estadísticas generales de ventas online."""
    stats = compute_stats()

    resumen_rows = [["Ingresos totales (pedidos pagados/enviados/entregados)", f"${stats['total_ingresos']:.2f}"]]
    estado_rows = [[e["status"], str(e["n"])] for e in stats["por_estado"]]
    top_rows = [[p["product_name"], str(int(p["total_qty"]))] for p in stats["top_productos"]]
    mes_rows = [[m["mes"], f"${m['total']:.2f}"] for m in stats["por_mes"]]

    try:
        response = build_pdf_response(
            filename=f"estadisticas_{date.today().isoformat()}.pdf",
            title="BrainSuplementos — Estadísticas",
            subtitle="Ventas online (la tienda)",
            sections=[
                {"heading": "Resumen", "headers": None, "rows": resumen_rows, "col_widths": [140, 40]},
                {"heading": "Pedidos por estado", "headers": ["Estado", "Cantidad"], "rows": estado_rows, "col_widths": [80, 40]},
                {"heading": "Top 5 productos más vendidos", "headers": ["Producto", "Unidades vendidas"], "rows": top_rows, "col_widths": [100, 50]},
                {"heading": "Ventas por mes", "headers": ["Mes", "Total"], "rows": mes_rows, "col_widths": [50, 50]},
            ],
        )
    except Exception as e:
        app.logger.error(f"Error al generar el PDF de estadísticas: {e}")
        flash("No se pudo generar el PDF de estadísticas. Probá de nuevo; si sigue fallando, avisame.")
        return redirect(url_for("admin_stats"))
    if response is None:
        flash("Para exportar a PDF hay que instalar la librería reportlab (pip install reportlab)")
        return redirect(url_for("admin_stats"))
    return response


@app.route("/admin/pedidos/<int:order_id>/estado", methods=["POST"])
@login_required
def admin_update_order_status(order_id):
    # "next" trae de vuelta al mismo período/página que se estaba viendo
    # en Pedidos (si no viene, /admin/pedidos solo (sin filtro) igual
    # funciona, solo que pide elegir un período de nuevo).
    next_url = request.form.get("next") or url_for("admin_orders")
    new_payment_status = request.form.get("payment_status", "")
    if new_payment_status not in ("pendiente", "pagado"):
        flash("Estado de pago inválido")
        return redirect(next_url)

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET payment_status = %s WHERE id = %s", (new_payment_status, order_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Pedido #{order_id}: pago actualizado a «{new_payment_status}»")
        if new_payment_status == "pagado":
            notify_order_event(order_id, "pagado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el pedido: {e}")

    return redirect(next_url)


@app.route("/admin/pedidos/<int:order_id>/entrega", methods=["POST"])
@login_required
def admin_update_order_delivery(order_id):
    next_url = request.form.get("next") or url_for("admin_orders")
    new_delivery_status = request.form.get("delivery_status", "")
    if new_delivery_status not in ("no_entregado", "entregado"):
        flash("Estado de entrega inválido")
        return redirect(next_url)

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET delivery_status = %s WHERE id = %s", (new_delivery_status, order_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Pedido #{order_id}: entrega actualizada a «{new_delivery_status}»")
        if new_delivery_status == "entregado":
            notify_order_event(order_id, "entregado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el pedido: {e}")

    return redirect(next_url)


@app.route("/admin/pedidos/<int:order_id>/cancelado", methods=["POST"])
@login_required
def admin_update_order_cancelled(order_id):
    next_url = request.form.get("next") or url_for("admin_orders")
    cancelled = 1 if request.form.get("cancelled") == "1" else 0

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET cancelled = %s WHERE id = %s", (cancelled, order_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Pedido #{order_id} {'cancelado' if cancelled else 'reactivado (ya no está cancelado)'}")
        if cancelled:
            notify_order_event(order_id, "cancelado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el pedido: {e}")

    return redirect(next_url)


@app.route("/admin/pedidos/<int:order_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_order(order_id):
    """Borra un pedido entero (y sus items, por el ON DELETE CASCADE de
    order_items). Es un borrado real, sin vuelta atrás — se usa para
    limpiar pedidos de prueba o cargados por error, no para devoluciones
    (para eso está cancelar, que deja el registro)."""
    next_url = request.form.get("next") or url_for("admin_orders")
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Pedido #{order_id} eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar el pedido: {e}")
    return redirect(next_url)


@app.route("/admin/pedidos/<int:order_id>/editar", methods=["GET", "POST"])
@login_required
def admin_edit_order(order_id):
    """Editar un pedido ya cargado: cambiar cantidades o sacar productos
    (por una devolución parcial), y ajustar los datos de entrega. El total
    se recalcula solo a partir de los items que queden. No permite agregar
    productos nuevos al pedido (para eso es más simple cargar uno nuevo)."""
    # "next" trae de vuelta al mismo período/página de Pedidos desde donde
    # se entró a editar, en vez de mandar siempre a /admin/pedidos "pelado"
    # (que pide elegir un período de nuevo).
    next_url = request.form.get("next") or request.args.get("next") or url_for("admin_orders")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT o.*, c.name AS customer_name, c.phone AS customer_phone
           FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.id = %s""",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        cursor.close()
        conn.close()
        flash("Ese pedido no existe")
        return redirect(next_url)

    if request.method == "POST":
        item_ids = request.form.getlist("item_id")
        item_qtys = request.form.getlist("item_qty")
        delivery_method = request.form.get("delivery_method", order["delivery_method"])
        delivery_address = request.form.get("delivery_address", order["delivery_address"])
        try:
            plain = conn.cursor()
            new_total = Decimal("0")
            for iid, qty_raw in zip(item_ids, item_qtys):
                qty = max(0, int(qty_raw or 0))
                if qty == 0:
                    plain.execute("DELETE FROM order_items WHERE id = %s AND order_id = %s", (iid, order_id))
                else:
                    plain.execute(
                        "UPDATE order_items SET qty = %s WHERE id = %s AND order_id = %s",
                        (qty, iid, order_id),
                    )
            cursor.execute(
                "SELECT COALESCE(SUM(unit_price * qty), 0) AS t FROM order_items WHERE order_id = %s",
                (order_id,),
            )
            new_total = cursor.fetchone()["t"] or Decimal("0")
            discount = order["discount_amount"] or Decimal("0")
            shipping = order["shipping_cost"] or Decimal("0")
            new_total = new_total - discount + shipping
            plain.execute(
                "UPDATE orders SET delivery_method = %s, delivery_address = %s, total = %s WHERE id = %s",
                (delivery_method, delivery_address, new_total, order_id),
            )
            conn.commit()
            plain.close()
            cursor.close()
            conn.close()
            flash(f"Pedido #{order_id} actualizado")
            return redirect(next_url)
        except (MySQLError, ValueError) as e:
            conn.rollback()
            flash(f"No se pudo guardar el pedido: {e}")

    cursor.execute("SELECT * FROM order_items WHERE order_id = %s", (order_id,))
    items = cursor.fetchall()
    for it in items:
        it["unit_price"] = to_float(it["unit_price"])
    order["total"] = to_float(order["total"])
    cursor.close()
    conn.close()
    return render_template("admin_edit_order.html", order=order, items=items, next_url=next_url)


ORDER_EVENT_MESSAGES = {
    "pagado": "¡Tu pago se acreditó! Ya estamos preparando tu pedido.",
    "entregado": "Tu pedido fue entregado. ¡Gracias por elegirnos!",
    "cancelado": "Tu pedido fue cancelado. Si no lo esperabas o tenés dudas, escribinos por WhatsApp.",
}


def order_status_label(o):
    """Arma un texto corto y legible para PDF/exports a partir de los tres
    campos de estado (antes era una sola columna `status`)."""
    if o.get("cancelled"):
        return "Cancelado"
    pago = "Pagado" if o.get("payment_status") == "pagado" else "Pendiente"
    entrega = "Entregado" if o.get("delivery_status") == "entregado" else "No entregado"
    return f"{pago} · {entrega}"


def notify_order_event(order_id, event):
    """Le manda un mail al cliente avisándole que pasó algo con su pedido
    (se pagó, se entregó, o se canceló). No hace nada (sin romper el
    cambio) si SMTP no está configurado o si el cliente no tiene mail
    cargado."""
    if event not in ORDER_EVENT_MESSAGES or not smtp_configured():
        return
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT c.name AS customer_name, c.email
               FROM orders o JOIN customers c ON c.id = o.customer_id
               WHERE o.id = %s""",
            (order_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row or not row["email"]:
            return
        send_email(
            row["email"],
            f"Novedades de tu pedido #{order_id} · BrainSuplementos",
            f"Hola {row['customer_name']},\n\n"
            f"{ORDER_EVENT_MESSAGES[event]}\n\n"
            f"Podés ver el detalle de tu pedido entrando a /cuenta en la web.",
        )
    except MySQLError as e:
        app.logger.error(f"No se pudo mandar el aviso de estado de pedido: {e}")


def save_uploaded_image(file_storage):
    """Guarda la imagen subida en static/img y devuelve la ruta pública, o None si no se subió nada"""
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        flash("Formato de imagen no permitido (usá jpg, png, webp o gif)")
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filename = secure_filename(filename)
    file_storage.save(os.path.join(UPLOAD_FOLDER, filename))
    return f"/static/img/{filename}"


def delete_image_file(image_url):
    """Borra del disco una imagen guardada en static/img, si existe."""
    if not image_url or not image_url.startswith("/static/img/"):
        return
    path = image_url.lstrip("/")
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _table_missing(error):
    """True si el error de MySQL es porque falta una migración del README:
    la tabla no existe (1146) o le falta una columna nueva (1054, ej:
    product_weights.product_flavor_id de la migración de pesos por sabor)."""
    return getattr(error, "errno", None) in (1146, 1054)


def _missing_column_name(error):
    """Si el error de MySQL es "columna desconocida" (1054), intenta sacar
    el nombre de esa columna del mensaje (ej: "Unknown column 'cost_price'
    in 'field list'" -> "cost_price")."""
    m = re.search(r"Unknown column '([\w.]+)'", str(error))
    if not m:
        return None
    return m.group(1).split(".")[-1]


def _column_exists(table, column):
    """True si esa columna ya existe en la tabla (para saber si corriste
    una migración sin tener que esperar a que falle un INSERT/SELECT)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
            (DB_CONFIG["database"], table, column),
        )
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return count > 0
    except MySQLError:
        return False


def insert_with_optional_columns(cursor, table, values, required):
    """INSERT adaptativo: si alguna columna opcional (no está en
    `required`) todavía no existe en la tabla porque falta correr una
    migración, la saca del INSERT y reintenta, en vez de romper el
    guardado entero. `values` es un dict columna->valor. Devuelve
    (lastrowid, columnas_que_tuvo_que_sacar)."""
    cols = dict(values)
    dropped = []
    while True:
        names = list(cols.keys())
        sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})"
        try:
            cursor.execute(sql, tuple(cols[c] for c in names))
            return cursor.lastrowid, dropped
        except MySQLError as e:
            if not _table_missing(e):
                raise
            missing = _missing_column_name(e)
            if not missing or missing not in cols or missing in required:
                raise
            cols.pop(missing)
            dropped.append(missing)


def update_with_optional_columns(cursor, table, values, where_col, where_val, required):
    """Igual que insert_with_optional_columns pero para UPDATE ... WHERE
    where_col = where_val. Devuelve la lista de columnas que tuvo que
    sacar por no existir todavía."""
    cols = dict(values)
    dropped = []
    while True:
        names = list(cols.keys())
        set_clause = ", ".join(f"{c}=%s" for c in names)
        sql = f"UPDATE {table} SET {set_clause} WHERE {where_col}=%s"
        try:
            cursor.execute(sql, tuple(cols[c] for c in names) + (where_val,))
            return dropped
        except MySQLError as e:
            if not _table_missing(e):
                raise
            missing = _missing_column_name(e)
            if not missing or missing not in cols or missing in required:
                raise
            cols.pop(missing)
            dropped.append(missing)


COLUMN_MIGRATION_HINTS = {
    "subcategory": "migracion_subcategorias.sql",
    "cost_price": "migracion_caja.sql",
    "barcode": "migracion_codigo_barras.sql",
    "show_low_stock_badge": "migracion_aviso_stock_bajo.sql",
}


def migration_hint_for(dropped_columns):
    """Arma el mensaje de aviso ("corré tal migración") para las columnas
    que insert/update_with_optional_columns tuvo que sacar."""
    if not dropped_columns:
        return None
    files = sorted({COLUMN_MIGRATION_HINTS.get(c, c) for c in dropped_columns})
    return f"(corré {', '.join(files)} para poder usar {', '.join(dropped_columns)} — ver README)"


DEFAULT_PAYMENT_SETTINGS = {
    "efectivo": True,
    "transferencia": True,
    "tarjeta_credito": True,
    "tarjeta_debito": True,
    "mercado_pago": True,
    "tarjetas_aceptadas": "",
    "recargo_cuotas_pct": 0,
}


def get_payment_settings():
    """Lee qué medios de pago acepta la tienda. Si la tabla todavía no
    existe (falta la migración) o no tiene la fila, devuelve todo
    habilitado por defecto — así el checkout nunca se rompe."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM payment_settings WHERE id = 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return dict(DEFAULT_PAYMENT_SETTINGS)
        return {
            "efectivo": bool(row["efectivo"]),
            "transferencia": bool(row["transferencia"]),
            "tarjeta_credito": bool(row["tarjeta_credito"]),
            "tarjeta_debito": bool(row["tarjeta_debito"]),
            "mercado_pago": bool(row["mercado_pago"]),
            "tarjetas_aceptadas": row.get("tarjetas_aceptadas") or "",
            "recargo_cuotas_pct": float(row["recargo_cuotas_pct"]) if row.get("recargo_cuotas_pct") is not None else 0,
        }
    except MySQLError as e:
        if not _table_missing(e):
            app.logger.error(f"Error al leer medios de pago: {e}")
        return dict(DEFAULT_PAYMENT_SETTINGS)


def get_flavors_for_product(product_id):
    """Devuelve la lista de sabores de un producto, cada uno con su galería
    de fotos y, si tiene, sus propios pesos con stock (product_flavor_id
    apuntando a ese sabor) — así "2 de Rosa viejo peso L" y "1 de Beige
    peso L" quedan totalmente separados. Lista vacía si el producto no
    tiene sabores cargados, o si todavía no corriste la migración."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM product_flavors WHERE product_id = %s ORDER BY sort_order, id",
            (product_id,),
        )
        colors = cursor.fetchall()

        if colors:
            flavor_ids = [c["id"] for c in colors]
            placeholders = ",".join(["%s"] * len(flavor_ids))
            cursor.execute(
                f"SELECT * FROM product_flavor_images WHERE flavor_id IN ({placeholders}) "
                f"ORDER BY sort_order, id",
                tuple(flavor_ids),
            )
            images_by_flavor = {}
            for img in cursor.fetchall():
                images_by_flavor.setdefault(img["flavor_id"], []).append(img)
            for c in colors:
                c["images"] = images_by_flavor.get(c["id"], [])

            try:
                cursor.execute(
                    f"SELECT * FROM product_weights WHERE product_flavor_id IN ({placeholders}) "
                    f"ORDER BY sort_order, id",
                    tuple(flavor_ids),
                )
                weights_by_flavor = {}
                for s in cursor.fetchall():
                    weights_by_flavor.setdefault(s["product_flavor_id"], []).append(s)
                for c in colors:
                    c["sizes"] = weights_by_flavor.get(c["id"], [])
            except MySQLError as e:
                if not _table_missing(e):
                    raise
                for c in colors:
                    c["sizes"] = []

        cursor.close()
        conn.close()
        return colors
    except MySQLError as e:
        if _table_missing(e):
            app.logger.warning("Falta la migración de sabores (product_flavors) — ver README sección 6.")
            return []
        raise


def get_weights_for_product(product_id):
    """Devuelve los pesos del producto que NO pertenecen a ningún sabor en
    particular (product_flavor_id NULL) — los pesos propios de cada sabor
    se piden por separado, en get_flavors_for_product. Lista vacía si no
    tiene, o si todavía no corriste la migración que crea product_weights."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM product_weights WHERE product_id = %s AND product_flavor_id IS NULL "
            "ORDER BY sort_order, id",
            (product_id,),
        )
        sizes = cursor.fetchall()
        cursor.close()
        conn.close()
        return sizes
    except MySQLError as e:
        if _table_missing(e):
            app.logger.warning("Falta la migración de pesos (product_weights) — ver README sección 6.")
            return []
        raise


def get_images_for_product(product_id):
    """Fotos extra del producto (ej: frente y espalda), independientes de
    los sabores. Lista vacía si no tiene, o si todavía no corriste la
    migración que crea product_images."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM product_images WHERE product_id = %s ORDER BY sort_order, id",
            (product_id,),
        )
        images = cursor.fetchall()
        cursor.close()
        conn.close()
        return images
    except MySQLError as e:
        if _table_missing(e):
            app.logger.warning("Falta la migración de galería de fotos (product_images) — ver README.")
            return []
        raise


def get_reviews_for_product(product_id):
    """Reseñas de un producto, con el nombre del cliente y si es una
    'compra verificada' (tiene al menos un pedido con ese producto).
    Lista vacía si no hay, o si todavía no corriste la migración."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT r.*, c.name AS customer_name FROM product_reviews r
               JOIN customers c ON c.id = r.customer_id
               WHERE r.product_id = %s ORDER BY r.created_at DESC""",
            (product_id,),
        )
        reviews = cursor.fetchall()
        if reviews:
            customer_ids = list({r["customer_id"] for r in reviews})
            placeholders = ",".join(["%s"] * len(customer_ids))
            cursor.execute(
                f"""SELECT DISTINCT o.customer_id FROM orders o
                    JOIN order_items oi ON oi.order_id = o.id
                    WHERE oi.product_id = %s AND o.customer_id IN ({placeholders})""",
                tuple([product_id] + customer_ids),
            )
            verified_ids = {row["customer_id"] for row in cursor.fetchall()}
            for r in reviews:
                r["verified"] = r["customer_id"] in verified_ids
        cursor.close()
        conn.close()
        return reviews
    except MySQLError as e:
        if _table_missing(e):
            return []
        raise


# =============================================================
# COLORES Y GALERÍA DE FOTOS POR PRODUCTO (panel admin)
# =============================================================
@app.route("/admin/products/<int:product_id>/colors")
@login_required
def admin_product_flavors(product_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    cursor.close()
    conn.close()

    if not product:
        flash("Ese producto no existe")
        return redirect(url_for("admin_dashboard"))

    colors = get_flavors_for_product(product_id)
    return render_template("admin_product_flavors.html", product=product, colors=colors)


@app.route("/admin/products/<int:product_id>/colors/new", methods=["POST"])
@login_required
def admin_add_flavor(product_id):
    name = request.form.get("flavor_name", "").strip()
    flavor_hex = request.form.get("flavor_color_hex", "#cccccc").strip()
    stock = request.form.get("stock", 0)
    files = [f for f in request.files.getlist("images") if f and f.filename]

    if not name:
        flash("Ponele un nombre al sabor")
        return redirect(url_for("admin_product_flavors", product_id=product_id))
    # La foto es opcional: si no cargan ninguna, ese sabor se muestra con
    # la foto principal del producto (ver currentGalleryImages() en
    # caro.js) — se puede agregar después desde acá mismo si quieren.

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO product_flavors (product_id, flavor_name, flavor_color_hex, stock) VALUES (%s, %s, %s, %s)",
            (product_id, name, flavor_hex, stock or 0),
        )
        flavor_id = cursor.lastrowid
        for i, f in enumerate(files):
            url = save_uploaded_image(f)
            if url:
                cursor.execute(
                    "INSERT INTO product_flavor_images (flavor_id, image_url, sort_order) VALUES (%s, %s, %s)",
                    (flavor_id, url, i),
                )
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Sabor «{name}» agregado")
    except MySQLError as e:
        flash(f"No se pudo agregar el sabor: {e}")

    return redirect(url_for("admin_product_flavors", product_id=product_id))


@app.route("/admin/flavors/<int:flavor_id>/stock", methods=["POST"])
@login_required
def admin_update_flavor_stock(flavor_id):
    stock = request.form.get("stock", 0)
    product_id = request.form.get("product_id")
    next_url = request.form.get("next")
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE product_flavors SET stock = %s WHERE id = %s", (stock, flavor_id))
        conn.commit()
        cursor.close()
        conn.close()
        check_stock_notify(product_id, product_flavor_id=flavor_id)
        flash("Stock actualizado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el stock: {e}")
    return redirect(next_url or url_for("admin_product_flavors", product_id=product_id))


@app.route("/admin/flavors/<int:flavor_id>/images/new", methods=["POST"])
@login_required
def admin_add_flavor_images(flavor_id):
    product_id = request.form.get("product_id")
    files = [f for f in request.files.getlist("images") if f and f.filename]
    if not files:
        flash("No se subió ninguna foto")
        return redirect(url_for("admin_product_flavors", product_id=product_id))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM product_flavor_images WHERE flavor_id = %s",
            (flavor_id,),
        )
        next_order = cursor.fetchone()[0] + 1
        for i, f in enumerate(files):
            url = save_uploaded_image(f)
            if url:
                cursor.execute(
                    "INSERT INTO product_flavor_images (flavor_id, image_url, sort_order) VALUES (%s, %s, %s)",
                    (flavor_id, url, next_order + i),
                )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Fotos agregadas")
    except MySQLError as e:
        flash(f"No se pudieron agregar las fotos: {e}")

    return redirect(url_for("admin_product_flavors", product_id=product_id))


@app.route("/admin/flavors/<int:flavor_id>/delete", methods=["POST"])
@login_required
def admin_delete_flavor(flavor_id):
    product_id = request.form.get("product_id")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM product_flavor_images WHERE flavor_id = %s", (flavor_id,))
        images = cursor.fetchall()
        cursor.execute("DELETE FROM product_flavors WHERE id = %s", (flavor_id,))
        conn.commit()
        cursor.close()
        conn.close()
        for img in images:
            delete_image_file(img["image_url"])
        flash("Sabor eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar el sabor (puede tener pedidos asociados): {e}")
    return redirect(url_for("admin_product_flavors", product_id=product_id))


@app.route("/admin/flavors/images/<int:image_id>/delete", methods=["POST"])
@login_required
def admin_delete_flavor_image(image_id):
    product_id = request.form.get("product_id")
    flavor_id = request.form.get("flavor_id")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM product_flavor_images WHERE id = %s", (image_id,))
        row = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*) AS n FROM product_flavor_images WHERE flavor_id = %s", (flavor_id,)
        )
        remaining = cursor.fetchone()["n"]
        if remaining <= 1:
            flash("No se puede borrar: cada sabor necesita al menos una foto. Subí otra antes de borrar esta.")
        else:
            cursor.execute("DELETE FROM product_flavor_images WHERE id = %s", (image_id,))
            conn.commit()
            if row:
                delete_image_file(row["image_url"])
            flash("Foto eliminada")
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo eliminar la foto: {e}")
    return redirect(url_for("admin_product_flavors", product_id=product_id))


# =============================================================
# GALERÍA DE FOTOS DEL PRODUCTO (frente/espalda/detalle, sin sabor)
# =============================================================
@app.route("/admin/products/<int:product_id>/images/new", methods=["POST"])
@login_required
def admin_add_product_images(product_id):
    """Sube una o varias fotos extra para el producto (ej: frente y
    espalda), independientes de las de cada sabor."""
    files = [f for f in request.files.getlist("images") if f and f.filename]
    if not files:
        flash("No se subió ninguna foto")
        return redirect(url_for("admin_edit_product", product_id=product_id))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM product_images WHERE product_id = %s",
            (product_id,),
        )
        next_order = cursor.fetchone()[0] + 1
        for i, f in enumerate(files):
            url = save_uploaded_image(f)
            if url:
                cursor.execute(
                    "INSERT INTO product_images (product_id, image_url, sort_order) VALUES (%s, %s, %s)",
                    (product_id, url, next_order + i),
                )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Fotos agregadas")
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_galeria_producto.sql para poder subir varias fotos por producto — ver README")
        else:
            flash(f"No se pudieron agregar las fotos: {e}")

    return redirect(url_for("admin_edit_product", product_id=product_id))


@app.route("/admin/products/images/<int:image_id>/delete", methods=["POST"])
@login_required
def admin_delete_product_image(image_id):
    product_id = request.form.get("product_id")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM product_images WHERE id = %s", (image_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("DELETE FROM product_images WHERE id = %s", (image_id,))
            conn.commit()
            delete_image_file(row["image_url"])
            flash("Foto eliminada")
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo eliminar la foto: {e}")
    return redirect(url_for("admin_edit_product", product_id=product_id))


# =============================================================
# PESOS POR PRODUCTO (panel admin)
# =============================================================
@app.route("/admin/products/<int:product_id>/sizes")
@login_required
def admin_product_weights(product_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()

    # Si el producto ya tiene sabores, los pesos se cargan por sabor
    # (desde la página de Sabores) para poder llevar el stock de cada
    # combinación por separado — acá solo mostramos pesos "sueltos", si
    # quedó alguno de antes de cargar sabores.
    flavor_count = 0
    if product:
        try:
            cursor.execute("SELECT COUNT(*) AS n FROM product_flavors WHERE product_id = %s", (product_id,))
            flavor_count = cursor.fetchone()["n"]
        except MySQLError as e:
            if not _table_missing(e):
                raise
    cursor.close()
    conn.close()

    if not product:
        flash("Ese producto no existe")
        return redirect(url_for("admin_dashboard"))

    sizes = get_weights_for_product(product_id)
    return render_template(
        "admin_product_weights.html", product=product, sizes=sizes, flavor_count=flavor_count,
    )


@app.route("/admin/products/<int:product_id>/sizes/new", methods=["POST"])
@login_required
def admin_add_weight(product_id):
    raw = request.form.get("weight_label", "").strip()
    stock = request.form.get("stock", 0)

    # Si escribió varios separados por coma (ej: "500g, 1kg, 2kg"), los
    # cargamos como pesos independientes en vez de uno solo llamado así.
    names = [n.strip() for n in raw.split(",") if n.strip()]

    if not names:
        flash("Ponele un nombre al peso")
        return redirect(url_for("admin_product_weights", product_id=product_id))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        new_weight_ids = []
        for name in names:
            cursor.execute(
                "INSERT INTO product_weights (product_id, weight_label, stock) VALUES (%s, %s, %s)",
                (product_id, name, stock or 0),
            )
            new_weight_ids.append(cursor.lastrowid)
        conn.commit()
        cursor.close()
        conn.close()
        for weight_id in new_weight_ids:
            check_stock_notify(product_id, product_weight_id=weight_id)
        if len(names) > 1:
            flash(f"Pesos agregados: {', '.join(names)}")
        else:
            flash(f"Peso «{names[0]}» agregado")
    except MySQLError as e:
        flash(f"No se pudo agregar el peso: {e}")

    return redirect(url_for("admin_product_weights", product_id=product_id))


@app.route("/admin/weights/<int:weight_id>/stock", methods=["POST"])
@login_required
def admin_update_weight_stock(weight_id):
    stock = request.form.get("stock", 0)
    product_id = request.form.get("product_id")
    next_url = request.form.get("next")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT product_flavor_id FROM product_weights WHERE id = %s", (weight_id,))
        row = cursor.fetchone()
        flavor_id = row["product_flavor_id"] if row else None
        plain_cursor = conn.cursor()
        plain_cursor.execute("UPDATE product_weights SET stock = %s WHERE id = %s", (stock, weight_id))
        conn.commit()
        plain_cursor.close()
        cursor.close()
        conn.close()
        check_stock_notify(product_id, product_flavor_id=flavor_id, product_weight_id=weight_id)
        flash("Stock actualizado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el stock: {e}")
    return redirect(next_url or url_for("admin_product_weights", product_id=product_id))


@app.route("/admin/products/<int:product_id>/stock", methods=["POST"])
@login_required
def admin_update_product_stock(product_id):
    """Igual que admin_update_flavor_stock / admin_update_weight_stock, pero
    para el stock general del producto (los que no tienen sabores ni
    pesos cargados). Se usa desde la página /admin/stock."""
    stock = parse_base_stock()
    next_url = request.form.get("next")
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE products SET stock = %s WHERE id = %s", (stock, product_id))
        conn.commit()
        cursor.close()
        conn.close()
        check_stock_notify(product_id)
        flash("Stock actualizado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el stock: {e}")
    return redirect(next_url or url_for("admin_stock"))


@app.route("/admin/stock/fila/<int:product_id>", methods=["POST"])
@login_required
def admin_update_stock_row(product_id):
    """Guarda de una sola vez todas las cantidades de stock de un producto
    en /admin/stock (pesos de cada sabor, sabores sin peso propio, pesos
    sueltos, o el stock general si no tiene sabores ni pesos), para no
    tener que apretar 'Guardar' peso por peso."""
    next_url = request.form.get("next")
    weight_ids = request.form.getlist("weight_id")
    weight_stocks = request.form.getlist("weight_stock")
    flavor_ids = request.form.getlist("flavor_id")
    flavor_stocks = request.form.getlist("flavor_stock")
    product_stock = request.form.get("product_stock")

    def as_stock(raw):
        try:
            value = int(raw)
            return value if value >= 0 else 0
        except (TypeError, ValueError):
            return 0

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        changed_weights = []
        for wid, stock in zip(weight_ids, weight_stocks):
            cursor.execute("SELECT product_flavor_id FROM product_weights WHERE id = %s", (wid,))
            row = cursor.fetchone()
            flavor_id = row["product_flavor_id"] if row else None
            plain = conn.cursor()
            plain.execute("UPDATE product_weights SET stock = %s WHERE id = %s", (as_stock(stock), wid))
            plain.close()
            changed_weights.append((int(wid), flavor_id))

        changed_flavors = []
        for cid, stock in zip(flavor_ids, flavor_stocks):
            plain = conn.cursor()
            plain.execute("UPDATE product_flavors SET stock = %s WHERE id = %s", (as_stock(stock), cid))
            plain.close()
            changed_flavors.append(int(cid))

        updated_product_stock = False
        if product_stock is not None and product_stock != "":
            plain = conn.cursor()
            plain.execute("UPDATE products SET stock = %s WHERE id = %s", (as_stock(product_stock), product_id))
            plain.close()
            updated_product_stock = True

        conn.commit()
        cursor.close()
        conn.close()

        for wid, flavor_id in changed_weights:
            check_stock_notify(product_id, product_flavor_id=flavor_id, product_weight_id=wid)
        for cid in changed_flavors:
            check_stock_notify(product_id, product_flavor_id=cid)
        if updated_product_stock:
            check_stock_notify(product_id)

        flash("Stock actualizado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el stock: {e}")
    return redirect(next_url or url_for("admin_stock"))


@app.route("/admin/stock/guardar-todo", methods=["POST"])
@login_required
def admin_update_stock_bulk():
    """Guarda de una sola vez el stock de TODA la lista que se ve en
    /admin/stock (productos simples, sabores y pesos mezclados), para no
    tener que ir fila por fila apretando "Guardar" — un solo botón al
    final de la página guarda todos los campos que se hayan tocado."""
    next_url = request.form.get("next")
    weight_ids = request.form.getlist("weight_id")
    weight_stocks = request.form.getlist("weight_stock")
    flavor_ids = request.form.getlist("flavor_id")
    flavor_stocks = request.form.getlist("flavor_stock")
    simple_product_ids = request.form.getlist("simple_product_id")
    simple_product_stocks = request.form.getlist("simple_product_stock")

    def as_stock(raw):
        try:
            value = int(raw)
            return value if value >= 0 else 0
        except (TypeError, ValueError):
            return 0

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        changed_weights = []
        for wid, stock in zip(weight_ids, weight_stocks):
            cursor.execute("SELECT product_id, product_flavor_id FROM product_weights WHERE id = %s", (wid,))
            row = cursor.fetchone()
            if not row:
                continue
            plain = conn.cursor()
            plain.execute("UPDATE product_weights SET stock = %s WHERE id = %s", (as_stock(stock), wid))
            plain.close()
            changed_weights.append((int(wid), row["product_id"], row["product_flavor_id"]))

        changed_flavors = []
        for cid, stock in zip(flavor_ids, flavor_stocks):
            cursor.execute("SELECT product_id FROM product_flavors WHERE id = %s", (cid,))
            row = cursor.fetchone()
            if not row:
                continue
            plain = conn.cursor()
            plain.execute("UPDATE product_flavors SET stock = %s WHERE id = %s", (as_stock(stock), cid))
            plain.close()
            changed_flavors.append((int(cid), row["product_id"]))

        changed_products = []
        for pid, stock in zip(simple_product_ids, simple_product_stocks):
            plain = conn.cursor()
            plain.execute("UPDATE products SET stock = %s WHERE id = %s", (as_stock(stock), pid))
            plain.close()
            changed_products.append(int(pid))

        conn.commit()
        cursor.close()
        conn.close()

        for wid, pid, flavor_id in changed_weights:
            check_stock_notify(pid, product_flavor_id=flavor_id, product_weight_id=wid)
        for cid, pid in changed_flavors:
            check_stock_notify(pid, product_flavor_id=cid)
        for pid in changed_products:
            check_stock_notify(pid)

        total = len(changed_weights) + len(changed_flavors) + len(changed_products)
        if total:
            flash(f"Stock actualizado ({total} campo{'s' if total != 1 else ''})")
        else:
            flash("No había ningún campo de stock para guardar")
    except MySQLError as e:
        flash(f"No se pudo actualizar el stock: {e}")
    return redirect(next_url or url_for("admin_stock"))


@app.route("/admin/flavors/<int:flavor_id>/sizes/new", methods=["POST"])
@login_required
def admin_add_flavor_weight(flavor_id):
    """Igual que admin_add_weight, pero el peso queda atado a un sabor en
    particular (product_flavor_id): así "2 de Rosa viejo peso L" y "1 de
    Beige peso L" se cargan y se descuentan por separado."""
    raw = request.form.get("weight_label", "").strip()
    stock = request.form.get("stock", 0)
    next_url = request.form.get("next")
    names = [n.strip() for n in raw.split(",") if n.strip()]

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT product_id FROM product_flavors WHERE id = %s", (flavor_id,))
    sabor = cursor.fetchone()
    if not sabor:
        cursor.close()
        conn.close()
        flash("Ese sabor no existe")
        return redirect(url_for("admin_dashboard"))
    product_id = sabor["product_id"]

    if not names:
        cursor.close()
        conn.close()
        flash("Ponele un nombre al peso")
        return redirect(next_url or url_for("admin_product_flavors", product_id=product_id))

    try:
        cursor = conn.cursor()
        new_weight_ids = []
        for name in names:
            cursor.execute(
                "INSERT INTO product_weights (product_id, product_flavor_id, weight_label, stock) VALUES (%s, %s, %s, %s)",
                (product_id, flavor_id, name, stock or 0),
            )
            new_weight_ids.append(cursor.lastrowid)
        conn.commit()
        cursor.close()
        conn.close()
        for weight_id in new_weight_ids:
            check_stock_notify(product_id, product_flavor_id=flavor_id, product_weight_id=weight_id)
        if len(names) > 1:
            flash(f"Pesos agregados: {', '.join(names)}")
        else:
            flash(f"Peso «{names[0]}» agregado")
    except MySQLError as e:
        conn.close()
        flash(f"No se pudo agregar el peso (¿corriste la migración de pesos por sabor? Ver README): {e}")

    return redirect(next_url or url_for("admin_product_flavors", product_id=product_id))


@app.route("/admin/weights/<int:weight_id>/delete", methods=["POST"])
@login_required
def admin_delete_weight(weight_id):
    product_id = request.form.get("product_id")
    next_url = request.form.get("next")
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM product_weights WHERE id = %s", (weight_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Peso eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar el peso (puede tener pedidos asociados): {e}")
    return redirect(next_url or url_for("admin_product_weights", product_id=product_id))


# =============================================================
# CARRUSEL DE PORTADA (hero_slides) — panel admin
# =============================================================
@app.route("/admin/hero")
@login_required
def admin_hero():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM hero_slides ORDER BY sort_order, id")
        slides = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if not _table_missing(e):
            flash(f"Error al leer el carrusel: {e}")
        slides = []
    # Categorías reales para el desplegable de "a dónde lleva el botón"
    # (sale directo de /admin/categorias).
    try:
        categories = get_categories(active_only=True)
    except MySQLError:
        categories = []
    return render_template("admin_hero.html", slides=slides, categories=categories)


@app.route("/admin/hero/new", methods=["POST"])
@login_required
def admin_add_hero_slide():
    image_url = save_uploaded_image(request.files.get("image"))
    if not image_url:
        flash("Subí una imagen para el slide")
        return redirect(url_for("admin_hero"))

    # Imagen alternativa para celular (opcional): si no se sube ninguna,
    # el celular sigue usando la misma imagen que la compu (no rompe nada
    # de lo que ya había antes de este campo).
    mobile_image_url = save_uploaded_image(request.files.get("mobile_image"))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) FROM hero_slides")
        next_order = cursor.fetchone()[0] + 1
        try:
            cursor.execute(
                """INSERT INTO hero_slides
                   (image_url, mobile_image_url, title, subtitle, button_text, button_link, sort_order, active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    image_url,
                    mobile_image_url,
                    request.form.get("title", "").strip() or None,
                    request.form.get("subtitle", "").strip() or None,
                    request.form.get("button_text", "").strip() or None,
                    request.form.get("button_link", "").strip() or None,
                    next_order,
                    1 if request.form.get("active") == "on" else 0,
                ),
            )
        except MySQLError as e:
            if not _table_missing(e):
                raise
            # Todavía no corriste el ALTER TABLE que agrega
            # mobile_image_url: guardamos el slide igual, sin esa columna.
            cursor.execute(
                """INSERT INTO hero_slides
                   (image_url, title, subtitle, button_text, button_link, sort_order, active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    image_url,
                    request.form.get("title", "").strip() or None,
                    request.form.get("subtitle", "").strip() or None,
                    request.form.get("button_text", "").strip() or None,
                    request.form.get("button_link", "").strip() or None,
                    next_order,
                    1 if request.form.get("active") == "on" else 0,
                ),
            )
            flash("Nota: corré el ALTER TABLE de mobile_image_url para poder usar la imagen de celular")
        conn.commit()
        cursor.close()
        conn.close()
        flash("Imagen agregada al carrusel")
    except MySQLError as e:
        flash(f"No se pudo agregar la imagen: {e}")

    return redirect(url_for("admin_hero"))


@app.route("/admin/hero/<int:slide_id>/edit", methods=["POST"])
@login_required
def admin_edit_hero_slide(slide_id):
    new_image = save_uploaded_image(request.files.get("image"))
    new_mobile_image = save_uploaded_image(request.files.get("mobile_image"))
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT image_url, mobile_image_url FROM hero_slides WHERE id = %s", (slide_id,))
            current = cursor.fetchone()
        except MySQLError as e:
            if not _table_missing(e):
                raise
            cursor.execute("SELECT image_url FROM hero_slides WHERE id = %s", (slide_id,))
            current = cursor.fetchone()
            if current is not None:
                current["mobile_image_url"] = None

        fields = {
            "title": request.form.get("title", "").strip() or None,
            "subtitle": request.form.get("subtitle", "").strip() or None,
            "button_text": request.form.get("button_text", "").strip() or None,
            "button_link": request.form.get("button_link", "").strip() or None,
            "active": 1 if request.form.get("active") == "on" else 0,
        }
        if new_image:
            fields["image_url"] = new_image
        if new_mobile_image:
            fields["mobile_image_url"] = new_mobile_image

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        try:
            cursor.execute(
                f"UPDATE hero_slides SET {set_clause} WHERE id = %s",
                (*fields.values(), slide_id),
            )
        except MySQLError as e:
            if not _table_missing(e):
                raise
            # Todavía no corriste el ALTER TABLE de mobile_image_url: se
            # actualiza el resto de los campos igual, sin esa columna.
            fields.pop("mobile_image_url", None)
            set_clause = ", ".join(f"{k} = %s" for k in fields)
            cursor.execute(
                f"UPDATE hero_slides SET {set_clause} WHERE id = %s",
                (*fields.values(), slide_id),
            )
            flash("Nota: corré el ALTER TABLE de mobile_image_url para poder usar la imagen de celular")
        conn.commit()
        cursor.close()
        conn.close()
        if new_image and current:
            delete_image_file(current["image_url"])
        if new_mobile_image and current and current.get("mobile_image_url"):
            delete_image_file(current["mobile_image_url"])
        flash("Slide actualizado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el slide: {e}")
    return redirect(url_for("admin_hero"))


@app.route("/admin/hero/<int:slide_id>/delete", methods=["POST"])
@login_required
def admin_delete_hero_slide(slide_id):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM hero_slides WHERE id = %s", (slide_id,))
        row = cursor.fetchone()
        cursor.execute("DELETE FROM hero_slides WHERE id = %s", (slide_id,))
        conn.commit()
        cursor.close()
        conn.close()
        if row:
            delete_image_file(row["image_url"])
        flash("Slide eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar el slide: {e}")
    return redirect(url_for("admin_hero"))


@app.route("/admin/hero/<int:slide_id>/move", methods=["POST"])
@login_required
def admin_move_hero_slide(slide_id):
    direction = request.form.get("direction")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM hero_slides ORDER BY sort_order, id")
        slides = cursor.fetchall()
        idx = next((i for i, s in enumerate(slides) if s["id"] == slide_id), None)
        if idx is not None:
            swap_idx = idx - 1 if direction == "up" else idx + 1
            if 0 <= swap_idx < len(slides):
                a, b = slides[idx], slides[swap_idx]
                cursor.execute("UPDATE hero_slides SET sort_order = %s WHERE id = %s", (b["sort_order"], a["id"]))
                cursor.execute("UPDATE hero_slides SET sort_order = %s WHERE id = %s", (a["sort_order"], b["id"]))
                conn.commit()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo reordenar: {e}")
    return redirect(url_for("admin_hero"))


# =============================================================
# BANNERS MOTIVACIONALES (goal_banners) — panel admin. Mismo patrón que
# el carrusel de portada (hero_slides): imagen + título + a dónde lleva
# al hacer click, reutilizando el mismo desplegable de categorías.
# =============================================================
@app.route("/admin/banners")
@login_required
def admin_banners():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM goal_banners ORDER BY sort_order, id")
        banners = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if not _table_missing(e):
            flash(f"Error al leer los banners: {e}")
        banners = []
    try:
        categories = get_categories(active_only=True)
    except MySQLError:
        categories = []
    return render_template("admin_banners.html", banners=banners, categories=categories)


@app.route("/admin/banners/new", methods=["POST"])
@login_required
def admin_add_banner():
    image_url = save_uploaded_image(request.files.get("image"))
    if not image_url:
        flash("Subí una imagen para el banner")
        return redirect(url_for("admin_banners"))
    title = request.form.get("title", "").strip()

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) FROM goal_banners")
        next_order = cursor.fetchone()[0] + 1
        cursor.execute(
            """INSERT INTO goal_banners (image_url, title, button_link, sort_order, active)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                image_url,
                title,
                request.form.get("button_link", "").strip() or None,
                next_order,
                1 if request.form.get("active") == "on" else 0,
            ),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Banner agregado")
    except MySQLError as e:
        if _table_missing(e):
            flash("Corré migracion_banners.sql para poder cargar banners — ver README")
        else:
            flash(f"No se pudo agregar el banner: {e}")
    return redirect(url_for("admin_banners"))


@app.route("/admin/banners/<int:banner_id>/edit", methods=["POST"])
@login_required
def admin_edit_banner(banner_id):
    new_image = save_uploaded_image(request.files.get("image"))
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM goal_banners WHERE id = %s", (banner_id,))
        current = cursor.fetchone()

        # El título es obligatorio: si lo mandaron vacío por error, dejamos
        # el que ya tenía en vez de guardar un banner sin texto.
        new_title = request.form.get("title", "").strip()
        if not new_title:
            cursor.execute("SELECT title FROM goal_banners WHERE id = %s", (banner_id,))
            new_title = cursor.fetchone()["title"]

        fields = {
            "title": new_title,
            "button_link": request.form.get("button_link", "").strip() or None,
            "active": 1 if request.form.get("active") == "on" else 0,
        }
        if new_image:
            fields["image_url"] = new_image

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(
            f"UPDATE goal_banners SET {set_clause} WHERE id = %s",
            (*fields.values(), banner_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        if new_image and current:
            delete_image_file(current["image_url"])
        flash("Banner actualizado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el banner: {e}")
    return redirect(url_for("admin_banners"))


@app.route("/admin/banners/<int:banner_id>/delete", methods=["POST"])
@login_required
def admin_delete_banner(banner_id):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM goal_banners WHERE id = %s", (banner_id,))
        row = cursor.fetchone()
        cursor.execute("DELETE FROM goal_banners WHERE id = %s", (banner_id,))
        conn.commit()
        cursor.close()
        conn.close()
        if row:
            delete_image_file(row["image_url"])
        flash("Banner eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar el banner: {e}")
    return redirect(url_for("admin_banners"))


@app.route("/admin/banners/<int:banner_id>/move", methods=["POST"])
@login_required
def admin_move_banner(banner_id):
    direction = request.form.get("direction")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM goal_banners ORDER BY sort_order, id")
        banners = cursor.fetchall()
        idx = next((i for i, b in enumerate(banners) if b["id"] == banner_id), None)
        if idx is not None:
            swap_idx = idx - 1 if direction == "up" else idx + 1
            if 0 <= swap_idx < len(banners):
                a, b = banners[idx], banners[swap_idx]
                cursor.execute("UPDATE goal_banners SET sort_order = %s WHERE id = %s", (b["sort_order"], a["id"]))
                cursor.execute("UPDATE goal_banners SET sort_order = %s WHERE id = %s", (a["sort_order"], b["id"]))
                conn.commit()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo reordenar: {e}")
    return redirect(url_for("admin_banners"))


# =============================================================
# MARCAS CON LAS QUE TRABAJAN (brands) — franja animada de la home
# =============================================================
@app.route("/admin/marcas")
@login_required
def admin_brands():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM brands ORDER BY sort_order, id")
        brands = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if not _table_missing(e):
            flash(f"Error al leer las marcas: {e}")
        else:
            flash("Todavía falta crear la tabla 'brands' — ver README sección 6 (correr la migración en MySQL Workbench).")
        brands = []
    return render_template("admin_brands.html", brands=brands)


@app.route("/admin/marcas/nueva", methods=["POST"])
@login_required
def admin_add_brand():
    name = (request.form.get("name") or "").strip()
    image_url = save_uploaded_image(request.files.get("image"))
    if not name or not image_url:
        flash("Ponele un nombre y subí el logo de la marca")
        return redirect(url_for("admin_brands"))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) FROM brands")
        next_order = cursor.fetchone()[0] + 1
        cursor.execute(
            "INSERT INTO brands (name, image_url, link, sort_order, active) VALUES (%s, %s, %s, %s, %s)",
            (name, image_url, request.form.get("link", "").strip() or None, next_order, 1 if request.form.get("active") == "on" else 0),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Marca agregada")
    except MySQLError as e:
        flash(f"No se pudo agregar la marca: {e}")
    return redirect(url_for("admin_brands"))


@app.route("/admin/marcas/<int:brand_id>/editar", methods=["POST"])
@login_required
def admin_edit_brand(brand_id):
    new_image = save_uploaded_image(request.files.get("image"))
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM brands WHERE id = %s", (brand_id,))
        current = cursor.fetchone()

        fields = {
            "name": (request.form.get("name") or "").strip(),
            "link": request.form.get("link", "").strip() or None,
            "active": 1 if request.form.get("active") == "on" else 0,
        }
        if new_image:
            fields["image_url"] = new_image

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(f"UPDATE brands SET {set_clause} WHERE id = %s", (*fields.values(), brand_id))
        conn.commit()
        cursor.close()
        conn.close()
        if new_image and current:
            delete_image_file(current["image_url"])
        flash("Marca actualizada")
    except MySQLError as e:
        flash(f"No se pudo actualizar la marca: {e}")
    return redirect(url_for("admin_brands"))


@app.route("/admin/marcas/<int:brand_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_brand(brand_id):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM brands WHERE id = %s", (brand_id,))
        row = cursor.fetchone()
        cursor.execute("DELETE FROM brands WHERE id = %s", (brand_id,))
        conn.commit()
        cursor.close()
        conn.close()
        if row:
            delete_image_file(row["image_url"])
        flash("Marca eliminada")
    except MySQLError as e:
        flash(f"No se pudo eliminar la marca: {e}")
    return redirect(url_for("admin_brands"))


@app.route("/admin/marcas/<int:brand_id>/mover", methods=["POST"])
@login_required
def admin_move_brand(brand_id):
    direction = request.form.get("direction")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM brands ORDER BY sort_order, id")
        brands = cursor.fetchall()
        idx = next((i for i, b in enumerate(brands) if b["id"] == brand_id), None)
        if idx is not None:
            swap_idx = idx - 1 if direction == "up" else idx + 1
            if 0 <= swap_idx < len(brands):
                a, b = brands[idx], brands[swap_idx]
                cursor.execute("UPDATE brands SET sort_order = %s WHERE id = %s", (b["sort_order"], a["id"]))
                cursor.execute("UPDATE brands SET sort_order = %s WHERE id = %s", (a["sort_order"], b["id"]))
                conn.commit()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo reordenar: {e}")
    return redirect(url_for("admin_brands"))


# =============================================================
# INSTAGRAM — capturas reales de posteos/reels para la tira
# "Seguinos en Instagram" de la home (mismo patrón que brands/banners)
# =============================================================
@app.route("/admin/instagram")
@login_required
def admin_instagram_posts():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM instagram_posts ORDER BY sort_order, id")
        posts = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if not _table_missing(e):
            flash(f"Error al leer los posteos: {e}")
        else:
            flash("Todavía falta crear la tabla 'instagram_posts' — correr migracion_instagram.sql en tu base.")
        posts = []
    return render_template("admin_instagram.html", posts=posts, instagram_url="https://instagram.com/brain__suplementos")


@app.route("/admin/instagram/nueva", methods=["POST"])
@login_required
def admin_add_instagram_post():
    image_url = save_uploaded_image(request.files.get("image"))
    if not image_url:
        flash("Subí una captura del posteo o reel")
        return redirect(url_for("admin_instagram_posts"))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) FROM instagram_posts")
        next_order = cursor.fetchone()[0] + 1
        cursor.execute(
            "INSERT INTO instagram_posts (image_url, link, sort_order, active) VALUES (%s, %s, %s, %s)",
            (image_url, request.form.get("link", "").strip() or None, next_order, 1 if request.form.get("active") == "on" else 0),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Posteo agregado")
    except MySQLError as e:
        flash(f"No se pudo agregar el posteo: {e}")
    return redirect(url_for("admin_instagram_posts"))


@app.route("/admin/instagram/<int:post_id>/editar", methods=["POST"])
@login_required
def admin_edit_instagram_post(post_id):
    new_image = save_uploaded_image(request.files.get("image"))
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM instagram_posts WHERE id = %s", (post_id,))
        current = cursor.fetchone()

        fields = {
            "link": request.form.get("link", "").strip() or None,
            "active": 1 if request.form.get("active") == "on" else 0,
        }
        if new_image:
            fields["image_url"] = new_image

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(f"UPDATE instagram_posts SET {set_clause} WHERE id = %s", (*fields.values(), post_id))
        conn.commit()
        cursor.close()
        conn.close()
        if new_image and current:
            delete_image_file(current["image_url"])
        flash("Posteo actualizado")
    except MySQLError as e:
        flash(f"No se pudo actualizar el posteo: {e}")
    return redirect(url_for("admin_instagram_posts"))


@app.route("/admin/instagram/<int:post_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_instagram_post(post_id):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT image_url FROM instagram_posts WHERE id = %s", (post_id,))
        row = cursor.fetchone()
        cursor.execute("DELETE FROM instagram_posts WHERE id = %s", (post_id,))
        conn.commit()
        cursor.close()
        conn.close()
        if row:
            delete_image_file(row["image_url"])
        flash("Posteo eliminado")
    except MySQLError as e:
        flash(f"No se pudo eliminar el posteo: {e}")
    return redirect(url_for("admin_instagram_posts"))


@app.route("/admin/instagram/<int:post_id>/mover", methods=["POST"])
@login_required
def admin_move_instagram_post(post_id):
    direction = request.form.get("direction")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM instagram_posts ORDER BY sort_order, id")
        posts = cursor.fetchall()
        idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), None)
        if idx is not None:
            swap_idx = idx - 1 if direction == "up" else idx + 1
            if 0 <= swap_idx < len(posts):
                a, b = posts[idx], posts[swap_idx]
                cursor.execute("UPDATE instagram_posts SET sort_order = %s WHERE id = %s", (b["sort_order"], a["id"]))
                cursor.execute("UPDATE instagram_posts SET sort_order = %s WHERE id = %s", (a["sort_order"], b["id"]))
                conn.commit()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo reordenar: {e}")
    return redirect(url_for("admin_instagram_posts"))


# =============================================================
# DESTACADOS — elegir a mano qué productos van fijos en "Novedades"
# o en "Más vendidos" (el resto se sigue completando solo, ver
# /api/newest-products y /api/most-purchased).
# =============================================================
@app.route("/admin/destacados")
@login_required
def admin_featured_products():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT fp.id, fp.section, fp.sort_order, p.id AS product_id,
                      p.name, p.image_url, p.active
               FROM featured_products fp
               JOIN products p ON p.id = fp.product_id
               ORDER BY fp.section, fp.sort_order, fp.id"""
        )
        all_rows = cursor.fetchall()
        novedades = [r for r in all_rows if r["section"] == "novedades"]
        vendidos = [r for r in all_rows if r["section"] == "vendidos"]

        cursor.execute(
            "SELECT id, name FROM products WHERE active = 1 ORDER BY name"
        )
        products = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as e:
        if not _table_missing(e):
            flash(f"Error al leer los destacados: {e}")
        else:
            flash("Todavía falta crear la tabla 'featured_products' — correr migracion_destacados.sql en tu base.")
        novedades, vendidos, products = [], [], []
    return render_template(
        "admin_featured.html", novedades=novedades, vendidos=vendidos, products=products
    )


@app.route("/admin/destacados/agregar", methods=["POST"])
@login_required
def admin_add_featured_product():
    section = request.form.get("section")
    if section not in ("novedades", "vendidos"):
        flash("Sección inválida")
        return redirect(url_for("admin_featured_products"))
    try:
        product_id = int(request.form.get("product_id"))
    except (TypeError, ValueError):
        flash("Elegí un producto")
        return redirect(url_for("admin_featured_products"))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM featured_products WHERE section = %s",
            (section,),
        )
        next_order = cursor.fetchone()[0] + 1
        cursor.execute(
            "INSERT INTO featured_products (product_id, section, sort_order) VALUES (%s, %s, %s)",
            (product_id, section, next_order),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Producto fijado")
    except MySQLError as e:
        if getattr(e, "errno", None) == 1062:
            flash("Ese producto ya está fijado en esa sección")
        else:
            flash(f"No se pudo fijar el producto: {e}")
    return redirect(url_for("admin_featured_products"))


@app.route("/admin/destacados/<int:featured_id>/mover", methods=["POST"])
@login_required
def admin_move_featured_product(featured_id):
    direction = request.form.get("direction")
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM featured_products WHERE id = %s", (featured_id,))
        current = cursor.fetchone()
        if current:
            cursor.execute(
                "SELECT * FROM featured_products WHERE section = %s ORDER BY sort_order, id",
                (current["section"],),
            )
            items = cursor.fetchall()
            idx = next((i for i, it in enumerate(items) if it["id"] == featured_id), None)
            if idx is not None:
                swap_idx = idx - 1 if direction == "up" else idx + 1
                if 0 <= swap_idx < len(items):
                    a, b = items[idx], items[swap_idx]
                    cursor.execute("UPDATE featured_products SET sort_order = %s WHERE id = %s", (b["sort_order"], a["id"]))
                    cursor.execute("UPDATE featured_products SET sort_order = %s WHERE id = %s", (a["sort_order"], b["id"]))
                    conn.commit()
        cursor.close()
        conn.close()
    except MySQLError as e:
        flash(f"No se pudo reordenar: {e}")
    return redirect(url_for("admin_featured_products"))


@app.route("/admin/destacados/<int:featured_id>/eliminar", methods=["POST"])
@login_required
def admin_delete_featured_product(featured_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM featured_products WHERE id = %s", (featured_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Producto quitado de destacados")
    except MySQLError as e:
        flash(f"No se pudo quitar: {e}")
    return redirect(url_for("admin_featured_products"))


# =============================================================
# MEDIOS DE PAGO — panel admin
# =============================================================
@app.route("/admin/pagos", methods=["GET", "POST"])
@login_required
def admin_payment_settings():
    if request.method == "POST":
        try:
            recargo_cuotas_pct = float((request.form.get("recargo_cuotas_pct") or "0").replace(",", "."))
        except ValueError:
            recargo_cuotas_pct = 0
        recargo_cuotas_pct = max(0, recargo_cuotas_pct)
        fields = {
            "efectivo": 1 if request.form.get("efectivo") == "on" else 0,
            "transferencia": 1 if request.form.get("transferencia") == "on" else 0,
            "tarjeta_credito": 1 if request.form.get("tarjeta_credito") == "on" else 0,
            "tarjeta_debito": 1 if request.form.get("tarjeta_debito") == "on" else 0,
            "mercado_pago": 1 if request.form.get("mercado_pago") == "on" else 0,
            "tarjetas_aceptadas": request.form.get("tarjetas_aceptadas", "").strip() or None,
            "recargo_cuotas_pct": recargo_cuotas_pct,
        }
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO payment_settings
                   (id, efectivo, transferencia, tarjeta_credito, tarjeta_debito, mercado_pago, tarjetas_aceptadas, recargo_cuotas_pct)
                   VALUES (1, %s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     efectivo=VALUES(efectivo), transferencia=VALUES(transferencia),
                     tarjeta_credito=VALUES(tarjeta_credito), tarjeta_debito=VALUES(tarjeta_debito),
                     mercado_pago=VALUES(mercado_pago), tarjetas_aceptadas=VALUES(tarjetas_aceptadas),
                     recargo_cuotas_pct=VALUES(recargo_cuotas_pct)""",
                (
                    fields["efectivo"], fields["transferencia"], fields["tarjeta_credito"],
                    fields["tarjeta_debito"], fields["mercado_pago"], fields["tarjetas_aceptadas"],
                    fields["recargo_cuotas_pct"],
                ),
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash("Medios de pago actualizados")
        except MySQLError as e:
            flash(f"No se pudo guardar (¿corriste la migración de payment_settings? Ver README / migracion_recargo_cuotas.sql): {e}")
        return redirect(url_for("admin_payment_settings"))

    settings = get_payment_settings()
    return render_template(
        "admin_payment_settings.html",
        settings=settings,
        mp_configured=mp_configured(),
        mp_card_form_configured=mp_card_form_configured(),
    )


# =============================================================
# CONFIGURACIÓN — datos de la cuenta de admin, contraseña y
# pregunta de seguridad (para "olvidé mi contraseña")
# =============================================================
def get_current_admin():
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
    admin = cursor.fetchone()
    cursor.close()
    conn.close()
    return admin


@app.route("/admin/configuracion")
@login_required
def admin_settings():
    admin = get_current_admin()
    if not admin:
        return redirect(url_for("admin_login"))
    return render_template("admin_settings.html", admin=admin)


@app.route("/admin/configuracion/perfil", methods=["POST"])
@login_required
def admin_update_profile():
    admin = get_current_admin()
    if not admin:
        return redirect(url_for("admin_login"))

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    username = (request.form.get("username") or "").strip()

    if not all([name, email, username]):
        flash("Completá nombre, mail y usuario")
        return redirect(url_for("admin_settings"))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE admins SET name = %s, email = %s, username = %s WHERE id = %s",
            (name, email, username, admin["id"]),
        )
        conn.commit()
        cursor.close()
        conn.close()
        session["admin_name"] = name
        flash("Datos de la cuenta actualizados")
    except MySQLError as e:
        flash(f"No se pudo guardar (¿mail o usuario ya usado por otra cuenta?): {e}")
    return redirect(url_for("admin_settings"))


@app.route("/admin/configuracion/password", methods=["POST"])
@login_required
def admin_update_password():
    admin = get_current_admin()
    if not admin:
        return redirect(url_for("admin_login"))

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    new_password2 = request.form.get("new_password2", "")

    if not check_password_hash(admin["password_hash"], current_password):
        flash("La contraseña actual no es correcta")
    elif new_password != new_password2:
        flash("Las contraseñas nuevas no coinciden")
    elif len(new_password) < 6:
        flash("La contraseña nueva tiene que tener al menos 6 caracteres")
    else:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE admins SET password_hash = %s WHERE id = %s",
                (generate_password_hash(new_password), admin["id"]),
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash("Contraseña actualizada")
        except MySQLError as e:
            flash(f"No se pudo actualizar la contraseña: {e}")
    return redirect(url_for("admin_settings"))


@app.route("/admin/configuracion/seguridad", methods=["POST"])
@login_required
def admin_update_security():
    admin = get_current_admin()
    if not admin:
        return redirect(url_for("admin_login"))

    current_password = request.form.get("current_password", "")
    question = (request.form.get("security_question") or "").strip()
    answer = (request.form.get("security_answer") or "").strip()

    if not check_password_hash(admin["password_hash"], current_password):
        flash("La contraseña actual no es correcta")
    elif not question or not answer:
        flash("Completá la pregunta y la respuesta de seguridad")
    else:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE admins SET security_question = %s, security_answer_hash = %s WHERE id = %s",
                (question, generate_password_hash(answer.lower()), admin["id"]),
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash("Pregunta de seguridad actualizada")
        except MySQLError as e:
            flash(f"No se pudo actualizar: {e}")
    return redirect(url_for("admin_settings"))


if __name__ == "__main__":
    # host="0.0.0.0" hace que el servidor escuche en toda la red local, no
    # solo en esta compu: así podés entrar desde el celular usando la IP
    # de la PC (ver README, sección "Ver la tienda desde el celular").
    app.run(debug=True, host="0.0.0.0", port=5000)