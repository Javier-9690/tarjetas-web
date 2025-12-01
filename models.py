# models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Password(db.Model):
    __tablename__ = "passwords"

    id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String(64), unique=True, nullable=False)


class Card(db.Model):
    __tablename__ = "cards"

    id = db.Column(db.Integer, primary_key=True)

    category = db.Column(db.String(20), index=True, nullable=False)

    # Campos genéricos que cubren tus columnas de Tkinter
    n = db.Column(db.String(50))
    modulo_sector = db.Column(db.String(100))
    categoria = db.Column(db.String(100))
    subcategoria = db.Column(db.String(100))
    nombre_tarjeta = db.Column(db.String(200))
    tipo_tarjeta = db.Column(db.String(100))
    numero_tarjeta = db.Column(db.String(100), index=True)

    status = db.Column(db.String(20), default="Activa")  # "Activa" / "Inactiva"

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    deliveries = db.relationship(
        "Delivery", backref="card", lazy=True, cascade="all, delete-orphan"
    )


class Delivery(db.Model):
    __tablename__ = "deliveries"

    id = db.Column(db.Integer, primary_key=True)

    category = db.Column(db.String(20), index=True, nullable=False)

    card_id = db.Column(db.Integer, db.ForeignKey("cards.id"), nullable=True)
    card_number = db.Column(db.String(100), index=True)

    rut = db.Column(db.String(50))
    nombre = db.Column(db.String(200))
    cargo = db.Column(db.String(100))
    empresa = db.Column(db.String(100))

    entrega_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    devolucion_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
