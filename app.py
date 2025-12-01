# app.py
import io
import hashlib
from datetime import datetime
from functools import wraps
from typing import Optional

import pandas as pd
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_file,
    abort,
)

from config import Config
from models import db, Password, Card, Delivery


# =========================
# Utilidades de claves
# =========================
def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


DEFAULT_PASSWORDS = [
    "Javier_Aramark_2025",
    "Lorena_Aramark_2025",
    "Carolina_Aramark_2025",
]


def verify_password(plain: str) -> bool:
    h = _sha256(plain)
    return db.session.query(Password.id).filter_by(hash=h).first() is not None


def ensure_default_passwords():
    # Crea en la tabla Password los hashes de DEFAULT_PASSWORDS si aún no existen.
    existing = {p.hash for p in Password.query.all()}
    created = 0
    for pwd in DEFAULT_PASSWORDS:
        h = _sha256(pwd)
        if h not in existing:
            db.session.add(Password(hash=h))
            created += 1
    if created:
        db.session.commit()


# =========================
# Definición de categorías
# =========================
CATEGORY_ORDER = ["MODULO", "MAESTRA", "MANTENCION", "PROVISORIA"]

CATEGORY_DEFINITIONS = {
    "MODULO": [
        ("n", "N°"),
        ("modulo_sector", "Módulo / Sector"),
        ("nombre_tarjeta", "Nombre de la Tarjeta"),
        ("tipo_tarjeta", "Tipo de Tarjeta"),
        ("numero_tarjeta", "Numero de tarjeta"),
    ],
    "MAESTRA": [
        ("n", "N°"),
        ("categoria", "Categoría"),
        ("nombre_tarjeta", "Nombre de la Tarjeta"),
        ("tipo_tarjeta", "Tipo de Tarjeta"),
        ("numero_tarjeta", "Numero Tarjeta"),
    ],
    "MANTENCION": [
        ("n", "N°"),
        ("categoria", "Categoría"),
        ("subcategoria", "Subcategoría"),
        ("nombre_tarjeta", "Nombre de la Tarjeta"),
        ("tipo_tarjeta", "Tipo de Tarjeta"),
        ("numero_tarjeta", "Numero Tarjeta"),
    ],
    "PROVISORIA": [
        ("n", "N°"),
        ("categoria", "Categoría"),
        ("nombre_tarjeta", "Nombre de la Tarjeta"),
        ("tipo_tarjeta", "Tipo de Tarjeta"),
        ("numero_tarjeta", "Numero Tarjeta"),
    ],
}


# =========================
# Helpers de autenticación
# =========================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)

    return wrapper


# =========================
# Helpers de fecha / estado
# =========================
def format_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def compute_card_status(card: Card):
    # Devuelve (texto_estado, tipo_estado)  tipo_estado ∈ {"Disponible","Entregadas","Devueltas"}
    deliveries = (
        Delivery.query.filter_by(category=card.category, card_id=card.id)
        .order_by(Delivery.entrega_at.asc())
        .all()
    )
    if not deliveries:
        return "Disponible", "Disponible"

    last = deliveries[-1]
    if last.devolucion_at:
        return f"Disponible (devuelto {format_dt(last.devolucion_at)})", "Devueltas"

    base = "Entregada"
    if last.nombre:
        base = f"Entregada a {last.nombre}"
    if last.entrega_at:
        base += f" ({format_dt(last.entrega_at)})"
    return base, "Entregadas"


def get_last_open_delivery(card: Card) -> Optional[Delivery]:
    # Última entrega sin registro de devolución, o None.
    deliveries = (
        Delivery.query.filter_by(category=card.category, card_id=card.id)
        .filter(Delivery.devolucion_at.is_(None))
        .order_by(Delivery.entrega_at.asc())
        .all()
    )
    return deliveries[-1] if deliveries else None


# =========================
# Factory de la app Flask
# =========================
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_default_passwords()

    # ===== context processor para usar {{ now.year }} en el footer =====
    @app.context_processor
    def inject_now():
        return {"now": datetime.utcnow()}

    # =========================
    # Rutas
    # =========================

    @app.route("/")
    def index():
        if session.get("logged_in"):
            return redirect(url_for("panel"))
        return redirect(url_for("login"))

    # ---------- LOGIN / LOGOUT ----------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            password = request.form.get("password", "")
            if verify_password(password):
                session["logged_in"] = True
                flash("Acceso correcto.", "success")
                next_url = request.args.get("next") or url_for("panel")
                return redirect(next_url)
            flash("Clave incorrecta.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("Sesión cerrada.", "info")
        return redirect(url_for("login"))

    # ---------- ADMINISTRACIÓN DE CLAVES ----------

    @app.route("/passwords", methods=["GET", "POST"])
    @login_required
    def manage_passwords():
        if request.method == "POST":
            action = request.form.get("action")

            if action == "add":
                pwd = request.form.get("new_password", "").strip()
                if not pwd:
                    flash("La clave no puede estar vacía.", "warning")
                else:
                    h = _sha256(pwd)
                    if Password.query.filter_by(hash=h).first():
                        flash("Esa clave ya existe.", "info")
                    else:
                        db.session.add(Password(hash=h))
                        db.session.commit()
                        flash("Clave agregada.", "success")

            elif action == "delete":
                pid = request.form.get("password_id")
                p = Password.query.get(pid)
                if p:
                    db.session.delete(p)
                    db.session.commit()
                    flash("Clave eliminada.", "success")

        passwords = Password.query.order_by(Password.id.asc()).all()
        return render_template("passwords.html", passwords=passwords)

    # ---------- PANEL / RESUMEN POR CATEGORÍA ----------

    @app.route("/panel")
    @login_required
    def panel():
        summary_rows = []

        for code in CATEGORY_ORDER:
            cards = Card.query.filter_by(category=code).all()
            total = len(cards)
            activas = sum(1 for c in cards if (c.status or "Activa") == "Activa")
            inactivas = total - activas
            pendientes = 0

            for c in cards:
                _, tipo = compute_card_status(c)
                if tipo == "Entregadas":
                    pendientes += 1

            summary_rows.append(
                {
                    "category": code,
                    "total": total,
                    "activas": activas,
                    "inactivas": inactivas,
                    "pendientes": pendientes,
                }
            )

        return render_template(
            "summary.html",
            summary_rows=summary_rows,
            categories=CATEGORY_ORDER,
        )

    @app.route("/summary")
    @login_required
    def summary():
        # Alias para compatibilidad
        return redirect(url_for("panel"))

    @app.route("/export/summary.xlsx")
    @login_required
    def export_summary_excel():
        data = []
        for code in CATEGORY_ORDER:
            cards = Card.query.filter_by(category=code).all()
            total = len(cards)
            activas = sum(1 for c in cards if (c.status or "Activa") == "Activa")
            inactivas = total - activas
            pendientes = 0
            for c in cards:
                _, tipo = compute_card_status(c)
                if tipo == "Entregadas":
                    pendientes += 1

            data.append(
                {
                    "Categoría": code,
                    "Total": total,
                    "Activas": activas,
                    "Inactivas": inactivas,
                    "Pendientes de entrega": pendientes,
                }
            )

        df = pd.DataFrame(data)
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name="resumen_tarjetas.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # ---------- DASHBOARD (placeholder) ----------

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    # ---------- VISTA DE CATEGORÍA (listar + alta) ----------

    @app.route("/category/<category_code>", methods=["GET", "POST"])
    @login_required
    def category_view(category_code):
        if category_code not in CATEGORY_DEFINITIONS:
            abort(404)

        fields = CATEGORY_DEFINITIONS[category_code]

        if request.method == "POST":
            action = request.form.get("action")
            if action == "add":
                card = Card(category=category_code)
                for field_name, _ in fields:
                    setattr(
                        card,
                        field_name,
                        request.form.get(field_name, "").strip(),
                    )
                card.status = request.form.get("status", "Activa")
                db.session.add(card)
                db.session.commit()
                flash("Tarjeta agregada.", "success")
                return redirect(
                    url_for("category_view", category_code=category_code)
                )

        status_filter = request.args.get("status", "Todas")
        cards = (
            Card.query.filter_by(category=category_code)
            .order_by(Card.id.asc())
            .all()
        )

        rows = []
        for card in cards:
            values = [getattr(card, f) or "" for f, _ in fields]
            texto_estado, tipo = compute_card_status(card)

            if status_filter == "Entregadas" and tipo != "Entregadas":
                continue
            if status_filter == "Devueltas" and tipo != "Devueltas":
                continue

            rows.append(
                {
                    "card": card,
                    "values": values,
                    "estado_texto": texto_estado,
                }
            )

        return render_template(
            "category.html",
            category_code=category_code,
            fields=fields,
            rows=rows,
            status_filter=status_filter,
            categories=CATEGORY_ORDER,
        )

    # ---------- IMPORTAR TARJETAS DESDE EXCEL ----------

    @app.route("/category/<category_code>/import", methods=["POST"])
    @login_required
    def import_cards(category_code):
        if category_code not in CATEGORY_DEFINITIONS:
            abort(404)

        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Seleccione un archivo Excel para importar.", "warning")
            return redirect(url_for("category_view", category_code=category_code))

        try:
            df = pd.read_excel(file, dtype=str).fillna("")
        except Exception as e:
            flash(f"No se pudo leer el archivo Excel: {e}", "danger")
            return redirect(url_for("category_view", category_code=category_code))

        fields = CATEGORY_DEFINITIONS[category_code]

        imported = 0

        for _, row in df.iterrows():
            card = Card(category=category_code)
            empty = True

            for field_name, label in fields:
                value = ""
                if field_name in df.columns:
                    value = str(row.get(field_name, "")).strip()
                elif label in df.columns:
                    value = str(row.get(label, "")).strip()

                if value:
                    setattr(card, field_name, value)
                    empty = False

            # Estado (Activa / Inactiva)
            status_val = ""
            if "status" in df.columns:
                status_val = str(row.get("status", "")).strip()
            elif "Activa / Inactiva" in df.columns:
                status_val = str(row.get("Activa / Inactiva", "")).strip()

            if status_val not in ("Activa", "Inactiva"):
                status_val = "Activa"
            card.status = status_val

            if not empty:
                db.session.add(card)
                imported += 1

        if imported:
            db.session.commit()
            flash(f"Se importaron {imported} tarjetas desde el Excel.", "success")
        else:
            flash("No se encontraron registros válidos en el archivo.", "info")

        return redirect(url_for("category_view", category_code=category_code))

    # ---------- DESCARGAR PLANTILLA EXCEL ----------

    @app.route("/category/<category_code>/template.xlsx")
    @login_required
    def download_cards_template(category_code):
        if category_code not in CATEGORY_DEFINITIONS:
            abort(404)

        fields = CATEGORY_DEFINITIONS[category_code]
        columns = [label for _, label in fields] + ["Activa / Inactiva"]
        df = pd.DataFrame(columns=columns)
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)

        filename = f"plantilla_tarjetas_{category_code.lower()}.xlsx"
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # ---------- ELIMINAR TARJETA ----------

    @app.route("/category/<category_code>/<int:card_id>/delete", methods=["POST"])
    @login_required
    def delete_card(category_code, card_id):
        card = Card.query.filter_by(id=card_id, category=category_code).first_or_404()
        db.session.delete(card)
        db.session.commit()
        flash("Tarjeta eliminada.", "success")
        return redirect(url_for("category_view", category_code=category_code))

    # ---------- ENTREGA / DEVOLUCIÓN ----------

    @app.route(
        "/category/<category_code>/<int:card_id>/deliver",
        methods=["GET", "POST"],
    )
    @login_required
    def deliver_card(category_code, card_id):
        if category_code not in CATEGORY_DEFINITIONS:
            abort(404)
        card = Card.query.filter_by(id=card_id, category=category_code).first_or_404()

        last_open = get_last_open_delivery(card)
        last_any = (
            Delivery.query.filter_by(category=category_code, card_id=card.id)
            .order_by(Delivery.entrega_at.asc())
            .all()
        )
        last_any = last_any[-1] if last_any else None

        if request.method == "POST":
            now = datetime.utcnow()

            rut = request.form.get("rut", "").strip()
            nombre = request.form.get("nombre", "").strip()
            cargo = request.form.get("cargo", "").strip()
            empresa = request.form.get("empresa", "").strip()
            entrega_str = request.form.get("entrega_at", "").strip()
            devolucion_str = request.form.get("devolucion_at", "").strip()

            if not rut or not nombre:
                flash("RUT y Nombre son obligatorios.", "warning")
                return redirect(
                    url_for(
                        "deliver_card",
                        category_code=category_code,
                        card_id=card_id,
                    )
                )

            def parse_dt_str(s: str) -> Optional[datetime]:
                if not s:
                    return None
                try:
                    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    return None

            entrega_at = parse_dt_str(entrega_str) or now
            devolucion_at = parse_dt_str(devolucion_str)

            if last_open:
                # Actualizar registro abierto
                last_open.rut = rut
                last_open.nombre = nombre
                last_open.cargo = cargo
                last_open.empresa = empresa
                last_open.entrega_at = entrega_at
                last_open.devolucion_at = devolucion_at
            else:
                # Crear nuevo registro
                d = Delivery(
                    category=category_code,
                    card_id=card.id,
                    card_number=card.numero_tarjeta or "",
                    rut=rut,
                    nombre=nombre,
                    cargo=cargo,
                    empresa=empresa,
                    entrega_at=entrega_at,
                    devolucion_at=devolucion_at,
                )
                db.session.add(d)

            db.session.commit()
            flash("Registro de entrega / devolución guardado.", "success")
            return redirect(url_for("category_view", category_code=category_code))

        # GET: pre-llenar formulario
        now_str = format_dt(datetime.utcnow())
        form_data = {
            "rut": "",
            "nombre": "",
            "cargo": "",
            "empresa": "",
            "entrega_at": now_str,
            "devolucion_at": "",
        }

        if last_open:
            form_data["rut"] = last_open.rut or ""
            form_data["nombre"] = last_open.nombre or ""
            form_data["cargo"] = last_open.cargo or ""
            form_data["empresa"] = last_open.empresa or ""
            form_data["entrega_at"] = format_dt(last_open.entrega_at)
            form_data["devolucion_at"] = now_str
        elif last_any:
            form_data["rut"] = last_any.rut or ""
            form_data["nombre"] = last_any.nombre or ""
            form_data["cargo"] = last_any.cargo or ""
            form_data["empresa"] = last_any.empresa or ""
            form_data["entrega_at"] = format_dt(last_any.entrega_at)
            form_data["devolucion_at"] = format_dt(last_any.devolucion_at)

        return render_template(
            "history.html",
            card=card,
            form_data=form_data,
            last_open=last_open,
            last_any=last_any,
            category_code=category_code,
        )

    # ---------- HISTORIAL POR TARJETA ----------

    @app.route("/category/<category_code>/<int:card_id>/history", methods=["GET"])
    @login_required
    def card_history(category_code, card_id):
        card = Card.query.filter_by(id=card_id, category=category_code).first_or_404()
        deliveries = (
            Delivery.query.filter_by(category=category_code, card_id=card.id)
            .order_by(Delivery.entrega_at.asc())
            .all()
        )
        return render_template(
            "full_history.html",
            card=card,
            deliveries=deliveries,
            category_code=category_code,
        )

    # ---------- HISTORIAL COMPLETO DE CATEGORÍA ----------

    @app.route("/category/<category_code>/full-history")
    @login_required
    def category_full_history(category_code):
        if category_code not in CATEGORY_DEFINITIONS:
            abort(404)

        status_filter = request.args.get("status", "Todas")
        deliveries = (
            Delivery.query.filter_by(category=category_code)
            .order_by(Delivery.entrega_at.asc())
            .all()
        )

        filtered = []
        for d in deliveries:
            if status_filter == "Entregadas" and d.devolucion_at is not None:
                continue
            if status_filter == "Devueltas" and d.devolucion_at is None:
                continue
            filtered.append(d)

        return render_template(
            "full_history.html",
            card=None,
            deliveries=filtered,
            category_code=category_code,
        )

    return app


# Instancia global para gunicorn: app:app
app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
