import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, session, jsonify, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "cambia-esta-clave-por-una-segura-en-produccion"
DB_PATH = "minimarket.db"
UPLOAD_DIR = os.path.join(app.root_path, "static", "uploads", "productos")
EXTENSIONES_PERMITIDAS = {"png", "jpg", "jpeg", "webp", "gif"}
NOMBRE_TIENDA = "Tienda d'Lianis"


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _col_existe(conn, tabla, columna):
    cols = [c["name"] for c in conn.execute(f"PRAGMA table_info({tabla})").fetchall()]
    return columna in cols


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nombre_completo TEXT,
            rol TEXT NOT NULL DEFAULT 'vendedor',   -- 'admin' o 'vendedor'
            activo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE,
            nombre TEXT NOT NULL,
            categoria_id INTEGER,
            imagen TEXT,
            stock INTEGER NOT NULL DEFAULT 0,        -- siempre en unidad minima (base)
            stock_minimo INTEGER NOT NULL DEFAULT 5,
            activo INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (categoria_id) REFERENCES categorias(id)
        );

        -- Presentaciones / unidades de medida de cada producto.
        -- Cada producto tiene una presentacion "base" (es_base=1, factor=1)
        -- que es la unidad minima en la que se lleva el inventario.
        -- Puede tener otras (ej. "Pack x12", factor=12) que se venden
        -- como multiplos de la unidad base.
        CREATE TABLE IF NOT EXISTS presentaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,             -- "Unidad", "Pack x12", "Caja x24"...
            factor INTEGER NOT NULL DEFAULT 1,  -- equivalencia en unidades base
            precio_costo REAL NOT NULL DEFAULT 0,
            precio_venta REAL NOT NULL DEFAULT 0,
            es_base INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (producto_id) REFERENCES productos(id)
        );

        CREATE TABLE IF NOT EXISTS cajas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            fecha_apertura TEXT NOT NULL,
            monto_apertura REAL NOT NULL,
            fecha_cierre TEXT,
            monto_cierre_esperado REAL,
            monto_cierre_real REAL,
            diferencia REAL,
            estado TEXT NOT NULL DEFAULT 'abierta',   -- 'abierta' / 'cerrada'
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );

        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            caja_id INTEGER,
            fecha TEXT NOT NULL,
            total REAL NOT NULL,
            metodo_pago TEXT NOT NULL DEFAULT 'Efectivo',
            monto_pagado REAL,
            vuelto REAL,
            cliente_nombre TEXT,
            anulada INTEGER NOT NULL DEFAULT 0,
            anulada_motivo TEXT,
            anulada_fecha TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
            FOREIGN KEY (caja_id) REFERENCES cajas(id)
        );

        CREATE TABLE IF NOT EXISTS detalle_venta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            presentacion_nombre TEXT NOT NULL DEFAULT 'Unidad',
            factor INTEGER NOT NULL DEFAULT 1,
            cantidad REAL NOT NULL,          -- cantidad vendida en la presentacion elegida
            cantidad_base INTEGER NOT NULL,  -- cantidad * factor, lo que se descuenta del stock
            precio_costo_base REAL NOT NULL DEFAULT 0,
            precio_unitario REAL NOT NULL,   -- precio de la presentacion (pudo ser editado)
            subtotal REAL NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas(id),
            FOREIGN KEY (producto_id) REFERENCES productos(id)
        );

        -- Cola de sincronizacion: cada venta queda pendiente hasta subirse
        -- a un backend remoto (futuro). Mientras no haya internet, el
        -- sistema sigue funcionando normalmente usando solo esta base local.
        CREATE TABLE IF NOT EXISTS sync_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            sincronizado INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (venta_id) REFERENCES ventas(id)
        );

        CREATE TABLE IF NOT EXISTS pedidos_web (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            cliente_nombre TEXT NOT NULL,
            cliente_telefono TEXT NOT NULL,
            metodo_pago TEXT NOT NULL,
            total REAL NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente/atendido/cancelado
            notas TEXT
        );

        CREATE TABLE IF NOT EXISTS pedido_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            producto_id INTEGER,
            nombre_producto TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (pedido_id) REFERENCES pedidos_web(id)
        );

        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT
        );
        """
    )
    conn.commit()

    # --- Migraciones para bases de datos creadas con versiones anteriores ---
    if not _col_existe(conn, "ventas", "metodo_pago"):
        conn.execute("ALTER TABLE ventas ADD COLUMN metodo_pago TEXT NOT NULL DEFAULT 'Efectivo'")
    if not _col_existe(conn, "ventas", "monto_pagado"):
        conn.execute("ALTER TABLE ventas ADD COLUMN monto_pagado REAL")
    if not _col_existe(conn, "ventas", "vuelto"):
        conn.execute("ALTER TABLE ventas ADD COLUMN vuelto REAL")
    if not _col_existe(conn, "ventas", "caja_id"):
        conn.execute("ALTER TABLE ventas ADD COLUMN caja_id INTEGER")
    if not _col_existe(conn, "ventas", "cliente_nombre"):
        conn.execute("ALTER TABLE ventas ADD COLUMN cliente_nombre TEXT")
    if not _col_existe(conn, "ventas", "anulada"):
        conn.execute("ALTER TABLE ventas ADD COLUMN anulada INTEGER NOT NULL DEFAULT 0")
    if not _col_existe(conn, "ventas", "anulada_motivo"):
        conn.execute("ALTER TABLE ventas ADD COLUMN anulada_motivo TEXT")
    if not _col_existe(conn, "ventas", "anulada_fecha"):
        conn.execute("ALTER TABLE ventas ADD COLUMN anulada_fecha TEXT")

    if not _col_existe(conn, "productos", "categoria_id"):
        conn.execute("ALTER TABLE productos ADD COLUMN categoria_id INTEGER")
    if not _col_existe(conn, "productos", "imagen"):
        conn.execute("ALTER TABLE productos ADD COLUMN imagen TEXT")
    if not _col_existe(conn, "productos", "activo"):
        conn.execute("ALTER TABLE productos ADD COLUMN activo INTEGER NOT NULL DEFAULT 1")
    conn.commit()

    if not _col_existe(conn, "detalle_venta", "presentacion_nombre"):
        conn.execute("ALTER TABLE detalle_venta ADD COLUMN presentacion_nombre TEXT NOT NULL DEFAULT 'Unidad'")
    if not _col_existe(conn, "detalle_venta", "factor"):
        conn.execute("ALTER TABLE detalle_venta ADD COLUMN factor INTEGER NOT NULL DEFAULT 1")
    if not _col_existe(conn, "detalle_venta", "cantidad_base"):
        conn.execute("ALTER TABLE detalle_venta ADD COLUMN cantidad_base INTEGER NOT NULL DEFAULT 0")
    if not _col_existe(conn, "detalle_venta", "precio_costo_base"):
        conn.execute("ALTER TABLE detalle_venta ADD COLUMN precio_costo_base REAL NOT NULL DEFAULT 0")
    elif not _col_existe(conn, "detalle_venta", "precio_costo"):
        pass
    if _col_existe(conn, "detalle_venta", "precio_costo") and not _col_existe(conn, "detalle_venta", "precio_costo_base"):
        conn.execute("ALTER TABLE detalle_venta ADD COLUMN precio_costo_base REAL NOT NULL DEFAULT 0")
    conn.commit()

    # Migra productos antiguos (con precio/precio_costo directos) a presentaciones
    if _col_existe(conn, "productos", "precio"):
        viejos = conn.execute("SELECT * FROM productos").fetchall()
        for p in viejos:
            existe_base = conn.execute(
                "SELECT COUNT(*) c FROM presentaciones WHERE producto_id = ? AND es_base = 1",
                (p["id"],),
            ).fetchone()["c"]
            if existe_base == 0:
                costo = p["precio_costo"] if "precio_costo" in p.keys() else 0
                venta = p["precio"] if "precio" in p.keys() else 0
                conn.execute(
                    """INSERT INTO presentaciones
                       (producto_id, nombre, factor, precio_costo, precio_venta, es_base)
                       VALUES (?, 'Unidad', 1, ?, ?, 1)""",
                    (p["id"], costo or 0, venta or 0),
                )
        conn.commit()

    # Usuario administrador por defecto si la tabla esta vacia
    existe = conn.execute("SELECT COUNT(*) c FROM usuarios").fetchone()["c"]
    if existe == 0:
        conn.execute(
            "INSERT INTO usuarios (username, password_hash, nombre_completo, rol) VALUES (?, ?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "Administrador", "admin"),
        )
        conn.commit()

    # Config por defecto
    if conn.execute("SELECT COUNT(*) c FROM configuracion WHERE clave='whatsapp_numero'").fetchone()["c"] == 0:
        conn.execute("INSERT INTO configuracion (clave, valor) VALUES ('whatsapp_numero', '')")
        conn.commit()

    conn.close()


def get_config(clave, default=""):
    conn = get_db()
    row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    conn.close()
    return row["valor"] if row and row["valor"] is not None else default


def set_config(clave, valor):
    conn = get_db()
    conn.execute(
        "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (clave, valor),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Autenticacion y roles
# ---------------------------------------------------------------------------
def login_requerido(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_requerido(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        if session.get("rol") != "admin":
            flash("Esa sección es solo para administradores", "error")
            return redirect(url_for("ventas"))
        return f(*args, **kwargs)
    return wrapper


def caja_abierta_actual(conn):
    return conn.execute(
        "SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1"
    ).fetchone()


@app.context_processor
def inject_globals():
    conn = get_db()
    caja = caja_abierta_actual(conn)
    whatsapp = get_config("whatsapp_numero", "")
    conn.close()
    return dict(nombre_tienda=NOMBRE_TIENDA, caja_abierta=caja, whatsapp_tienda=whatsapp)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        usuario = conn.execute(
            "SELECT * FROM usuarios WHERE username = ? AND activo = 1", (username,)
        ).fetchone()
        conn.close()

        if usuario and check_password_hash(usuario["password_hash"], password):
            session["usuario_id"] = usuario["id"]
            session["username"] = usuario["username"]
            session["rol"] = usuario["rol"]
            session["nombre_completo"] = usuario[3] if len(usuario) > 3 and usuario[3] else usuario[1]            
            if usuario["rol"] == "admin":
                return redirect(url_for("dashboard"))
            return redirect(url_for("ventas"))

        flash("Usuario o contraseña incorrectos", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/cambiar-password", methods=["GET", "POST"])
@login_requerido
def cambiar_password():
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        confirmar = request.form.get("confirmar", "")

        conn = get_db()
        usuario = conn.execute(
            "SELECT * FROM usuarios WHERE id = ?", (session["usuario_id"],)
        ).fetchone()

        if not check_password_hash(usuario["password_hash"], actual):
            flash("La contraseña actual es incorrecta", "error")
        elif len(nueva) < 6:
            flash("La nueva contraseña debe tener al menos 6 caracteres", "error")
        elif nueva != confirmar:
            flash("La nueva contraseña y su confirmación no coinciden", "error")
        else:
            conn.execute(
                "UPDATE usuarios SET password_hash = ? WHERE id = ?",
                (generate_password_hash(nueva), session["usuario_id"]),
            )
            conn.commit()
            conn.close()
            flash("Contraseña actualizada correctamente", "success")
            return redirect(url_for("cambiar_password"))

        conn.close()
    return render_template("cambiar_password.html", activo="")


# ---------------------------------------------------------------------------
# Dashboard (solo admin)
# ---------------------------------------------------------------------------
@app.route("/")
@login_requerido
def index():
    if session.get("rol") == "admin":
        return redirect(url_for("dashboard"))
    return redirect(url_for("ventas"))


@app.route("/dashboard")
@admin_requerido
def dashboard():
    conn = get_db()
    hoy = datetime.now().strftime("%Y-%m-%d")

    ventas_hoy_row = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(total),0) t FROM ventas WHERE fecha LIKE ? AND anulada = 0",
        (hoy + "%",),
    ).fetchone()
    total_ventas_hoy = ventas_hoy_row["t"]
    cantidad_ventas_hoy = ventas_hoy_row["c"]

    ganancia_hoy = conn.execute(
        """SELECT COALESCE(SUM((dv.precio_unitario - dv.precio_costo_base * dv.factor) * dv.cantidad), 0) g
           FROM detalle_venta dv JOIN ventas v ON dv.venta_id = v.id
           WHERE v.fecha LIKE ? AND v.anulada = 0""",
        (hoy + "%",),
    ).fetchone()["g"]

    ganancia_total = conn.execute(
        """SELECT COALESCE(SUM((dv.precio_unitario - dv.precio_costo_base * dv.factor) * dv.cantidad), 0) g
           FROM detalle_venta dv JOIN ventas v ON dv.venta_id = v.id
           WHERE v.anulada = 0"""
    ).fetchone()["g"]

    por_metodo = conn.execute(
        """SELECT metodo_pago, COUNT(*) c, COALESCE(SUM(total),0) t
           FROM ventas WHERE fecha LIKE ? AND anulada = 0 GROUP BY metodo_pago""",
        (hoy + "%",),
    ).fetchall()

    top_productos = conn.execute(
        """SELECT p.nombre,
                  SUM(dv.cantidad_base) unidades,
                  SUM(dv.subtotal) total_vendido,
                  SUM((dv.precio_unitario - dv.precio_costo_base * dv.factor) * dv.cantidad) ganancia
           FROM detalle_venta dv
           JOIN productos p ON dv.producto_id = p.id
           JOIN ventas v ON dv.venta_id = v.id
           WHERE v.anulada = 0
           GROUP BY p.id ORDER BY unidades DESC LIMIT 5"""
    ).fetchall()

    stock_bajo = conn.execute(
        "SELECT * FROM productos WHERE stock <= stock_minimo AND activo = 1 ORDER BY stock ASC"
    ).fetchall()

    pedidos_pendientes = conn.execute(
        "SELECT COUNT(*) c FROM pedidos_web WHERE estado = 'pendiente'"
    ).fetchone()["c"]

    conn.close()
    return render_template(
        "dashboard.html",
        activo="dashboard",
        total_ventas_hoy=total_ventas_hoy,
        cantidad_ventas_hoy=cantidad_ventas_hoy,
        ganancia_hoy=ganancia_hoy,
        ganancia_total=ganancia_total,
        por_metodo=por_metodo,
        top_productos=top_productos,
        stock_bajo=stock_bajo,
        pedidos_pendientes=pedidos_pendientes,
    )


# ---------------------------------------------------------------------------
# Caja: apertura y cierre
# ---------------------------------------------------------------------------
@app.route("/caja/apertura", methods=["GET", "POST"])
@login_requerido
def caja_apertura():
    conn = get_db()
    if caja_abierta_actual(conn):
        conn.close()
        flash("Ya hay una caja abierta", "error")
        return redirect(url_for("ventas"))

    if request.method == "POST":
        monto = float(request.form.get("monto_apertura") or 0)
        conn.execute(
            "INSERT INTO cajas (usuario_id, fecha_apertura, monto_apertura, estado) VALUES (?, ?, ?, 'abierta')",
            (session["usuario_id"], datetime.now().isoformat(timespec="seconds"), monto),
        )
        conn.commit()
        conn.close()
        flash("Caja aperturada correctamente", "success")
        return redirect(url_for("ventas"))

    conn.close()
    return render_template("caja_apertura.html", activo="ventas")


@app.route("/caja/cierre", methods=["GET", "POST"])
@login_requerido
def caja_cierre():
    conn = get_db()
    caja = caja_abierta_actual(conn)
    if not caja:
        conn.close()
        flash("No hay ninguna caja abierta", "error")
        return redirect(url_for("ventas"))

    ventas_caja = conn.execute(
        "SELECT * FROM ventas WHERE caja_id = ? AND anulada = 0", (caja["id"],)
    ).fetchall()

    total_efectivo = sum(v["total"] for v in ventas_caja if v["metodo_pago"] == "Efectivo")
    total_otros = sum(v["total"] for v in ventas_caja if v["metodo_pago"] != "Efectivo")
    por_metodo = {}
    for v in ventas_caja:
        por_metodo.setdefault(v["metodo_pago"], {"c": 0, "t": 0})
        por_metodo[v["metodo_pago"]]["c"] += 1
        por_metodo[v["metodo_pago"]]["t"] += v["total"]

    monto_esperado = caja["monto_apertura"] + total_efectivo

    if request.method == "POST":
        monto_real = float(request.form.get("monto_cierre_real") or 0)
        diferencia = round(monto_real - monto_esperado, 2)
        conn.execute(
            """UPDATE cajas SET fecha_cierre=?, monto_cierre_esperado=?,
               monto_cierre_real=?, diferencia=?, estado='cerrada' WHERE id=?""",
            (datetime.now().isoformat(timespec="seconds"), monto_esperado, monto_real, diferencia, caja["id"]),
        )
        conn.commit()
        conn.close()
        flash("Caja cerrada correctamente", "success")
        return redirect(url_for("login") if session.get("rol") != "admin" else url_for("dashboard"))

    conn.close()
    return render_template(
        "caja_cierre.html",
        activo="ventas",
        caja=caja,
        total_efectivo=total_efectivo,
        total_otros=total_otros,
        por_metodo=por_metodo,
        monto_esperado=monto_esperado,
        cantidad_ventas=len(ventas_caja),
    )


# ---------------------------------------------------------------------------
# Ventas
# ---------------------------------------------------------------------------
@app.route("/ventas")
@login_requerido
def ventas():
    conn = get_db()
    caja = caja_abierta_actual(conn)
    if not caja:
        conn.close()
        return redirect(url_for("caja_apertura"))

    categoria_id = request.args.get("categoria")
    query = """SELECT p.*, c.nombre AS categoria_nombre FROM productos p
               LEFT JOIN categorias c ON p.categoria_id = c.id
               WHERE p.stock > 0 AND p.activo = 1"""
    params = []
    if categoria_id:
        query += " AND p.categoria_id = ?"
        params.append(categoria_id)
    query += " ORDER BY p.nombre"
    productos = conn.execute(query, params).fetchall()

    presentaciones_por_producto = {}
    for p in productos:
        pres = conn.execute(
            "SELECT * FROM presentaciones WHERE producto_id = ? ORDER BY es_base DESC, factor ASC",
            (p["id"],),
        ).fetchall()
        presentaciones_por_producto[p["id"]] = [dict(x) for x in pres]

    categorias = conn.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "ventas.html",
        activo="ventas",
        productos=productos,
        presentaciones=presentaciones_por_producto,
        categorias=categorias,
        categoria_actual=categoria_id,
    )


@app.route("/api/vender", methods=["POST"])
@login_requerido
def api_vender():
    """
    Registra una venta completa de forma atomica. Por cada linea del
    carrito se recibe la presentacion elegida (ej. Unidad o Pack x12);
    la cantidad ingresada se multiplica por el factor de esa presentacion
    para saber cuanto se descuenta del stock (que siempre vive en la
    unidad base). El precio de cada linea puede venir editado desde caja.
    """
    conn = get_db()
    caja = caja_abierta_actual(conn)
    if not caja:
        conn.close()
        return jsonify({"error": "No hay una caja abierta. Debes aperturar caja antes de vender."}), 400

    carrito = request.json.get("carrito", [])  # [{producto_id, presentacion_id, cantidad, precio}]
    metodo_pago = request.json.get("metodo_pago", "Efectivo")
    monto_pagado = request.json.get("monto_pagado")
    cliente_nombre = (request.json.get("cliente_nombre") or "").strip() or None

    if not carrito:
        conn.close()
        return jsonify({"error": "El carrito está vacío"}), 400

    metodos_validos = {"Efectivo", "Yape", "Plin", "Tarjeta"}
    if metodo_pago not in metodos_validos:
        conn.close()
        return jsonify({"error": "Método de pago no válido"}), 400

    try:
        conn.execute("BEGIN")

        total = 0.0
        detalles = []
        for item in carrito:
            producto = conn.execute(
                "SELECT * FROM productos WHERE id = ?", (item["producto_id"],)
            ).fetchone()
            if not producto:
                raise ValueError(f"Producto {item['producto_id']} no existe")

            presentacion = conn.execute(
                "SELECT * FROM presentaciones WHERE id = ? AND producto_id = ?",
                (item["presentacion_id"], producto["id"]),
            ).fetchone()
            if not presentacion:
                raise ValueError(f"Presentación no válida para '{producto['nombre']}'")

            cantidad = float(item["cantidad"])
            factor = presentacion["factor"]
            cantidad_base = int(round(cantidad * factor))

            if producto["stock"] < cantidad_base:
                raise ValueError(f"Stock insuficiente para '{producto['nombre']}'")

            # Precio: usa el editado desde caja si vino; si no, el de la presentacion
            precio_unitario = item.get("precio")
            precio_unitario = float(precio_unitario) if precio_unitario not in (None, "") else presentacion["precio_venta"]
            if precio_unitario < 0:
                raise ValueError("El precio no puede ser negativo")

            subtotal = precio_unitario * cantidad
            total += subtotal
            detalles.append({
                "producto_id": producto["id"],
                "nombre": producto["nombre"],
                "presentacion_nombre": presentacion["nombre"],
                "factor": factor,
                "cantidad": cantidad,
                "cantidad_base": cantidad_base,
                "precio_costo_base": presentacion["precio_costo"] / factor if factor else 0,
                "precio_unitario": precio_unitario,
                "subtotal": subtotal,
            })

        vuelto = None
        if metodo_pago == "Efectivo":
            if monto_pagado is None:
                raise ValueError("Debes indicar con cuánto paga el cliente")
            monto_pagado = float(monto_pagado)
            if monto_pagado < total:
                raise ValueError(
                    f"El monto pagado (S/ {monto_pagado:.2f}) es menor al total (S/ {total:.2f})"
                )
            vuelto = round(monto_pagado - total, 2)
        else:
            monto_pagado = total
            vuelto = 0.0

        cur = conn.execute(
            """INSERT INTO ventas
               (usuario_id, caja_id, fecha, total, metodo_pago, monto_pagado, vuelto, cliente_nombre)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["usuario_id"], caja["id"],
                datetime.now().isoformat(timespec="seconds"),
                total, metodo_pago, monto_pagado, vuelto, cliente_nombre,
            ),
        )
        venta_id = cur.lastrowid

        for d in detalles:
            conn.execute(
                """INSERT INTO detalle_venta
                   (venta_id, producto_id, presentacion_nombre, factor, cantidad,
                    cantidad_base, precio_costo_base, precio_unitario, subtotal)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    venta_id, d["producto_id"], d["presentacion_nombre"], d["factor"],
                    d["cantidad"], d["cantidad_base"], d["precio_costo_base"],
                    d["precio_unitario"], d["subtotal"],
                ),
            )
            conn.execute(
                "UPDATE productos SET stock = stock - ? WHERE id = ?",
                (d["cantidad_base"], d["producto_id"]),
            )

        conn.execute("INSERT INTO sync_pending (venta_id, sincronizado) VALUES (?, 0)", (venta_id,))
        conn.commit()

        alertas = []
        for d in detalles:
            p = conn.execute("SELECT * FROM productos WHERE id = ?", (d["producto_id"],)).fetchone()
            if p["stock"] <= p["stock_minimo"]:
                alertas.append(f"Stock bajo: {p['nombre']} ({p['stock']} unidades)")

        return jsonify({
            "ok": True, "venta_id": venta_id, "total": total, "metodo_pago": metodo_pago,
            "monto_pagado": monto_pagado, "vuelto": vuelto, "alertas": alertas,
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/venta/<int:venta_id>/comprobante")
@login_requerido
def venta_comprobante(venta_id):
    conn = get_db()
    venta = conn.execute(
        """SELECT v.*, u.username FROM ventas v JOIN usuarios u ON v.usuario_id = u.id
           WHERE v.id = ?""", (venta_id,)
    ).fetchone()
    if not venta:
        conn.close()
        flash("Venta no encontrada", "error")
        return redirect(url_for("ventas"))
    detalle = conn.execute(
        """SELECT dv.*, p.nombre AS producto_nombre FROM detalle_venta dv
           JOIN productos p ON dv.producto_id = p.id
           WHERE dv.venta_id = ?""", (venta_id,)
    ).fetchall()
    conn.close()
    return render_template("comprobante.html", activo="ventas", venta=venta, detalle=detalle)


@app.route("/venta/<int:venta_id>/enviar-correo", methods=["POST"])
@login_requerido
def venta_enviar_correo(venta_id):
    correo = request.form.get("correo", "").strip()
    # NOTA: para que el envio real funcione hay que configurar un servidor
    # SMTP (Gmail, Outlook, etc.) en este archivo. Sin esa configuracion,
    # el sistema no puede enviar correos de verdad.
    flash(
        f"Para enviar comprobantes a {correo} por correo, primero debes configurar "
        "un servidor SMTP en app.py (usuario y contraseña de tu correo de la tienda). "
        "Pídele a tu desarrollador que lo active.",
        "error",
    )
    return redirect(url_for("venta_comprobante", venta_id=venta_id))


@app.route("/venta/<int:venta_id>/anular", methods=["POST"])
@admin_requerido
def venta_anular(venta_id):
    motivo = request.form.get("motivo", "").strip() or "Sin motivo especificado"
    conn = get_db()
    try:
        conn.execute("BEGIN")
        venta = conn.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
        if not venta:
            raise ValueError("Venta no encontrada")
        if venta["anulada"]:
            raise ValueError("Esta venta ya estaba anulada")

        detalle = conn.execute("SELECT * FROM detalle_venta WHERE venta_id = ?", (venta_id,)).fetchall()
        for d in detalle:
            conn.execute(
                "UPDATE productos SET stock = stock + ? WHERE id = ?",
                (d["cantidad_base"], d["producto_id"]),
            )

        conn.execute(
            "UPDATE ventas SET anulada=1, anulada_motivo=?, anulada_fecha=? WHERE id=?",
            (motivo, datetime.now().isoformat(timespec="seconds"), venta_id),
        )
        conn.commit()
        flash(f"Venta #{venta_id} anulada. El stock fue devuelto al inventario.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"No se pudo anular: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for("reportes"))


# ---------------------------------------------------------------------------
# Inventario (solo admin)
# ---------------------------------------------------------------------------
def _guardar_imagen(archivo):
    if not archivo or archivo.filename == "":
        return None
    ext = archivo.filename.rsplit(".", 1)[-1].lower() if "." in archivo.filename else ""
    if ext not in EXTENSIONES_PERMITIDAS:
        return None
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    nombre_seguro = secure_filename(archivo.filename)
    nombre_final = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{nombre_seguro}"
    archivo.save(os.path.join(UPLOAD_DIR, nombre_final))
    return nombre_final


@app.route("/inventario")
@admin_requerido
def inventario():
    conn = get_db()
    productos = conn.execute(
        """SELECT p.*, c.nombre AS categoria_nombre FROM productos p
           LEFT JOIN categorias c ON p.categoria_id = c.id
           ORDER BY p.nombre"""
    ).fetchall()
    productos_completos = []
    for p in productos:
        pres = conn.execute(
            "SELECT * FROM presentaciones WHERE producto_id = ? ORDER BY es_base DESC, factor ASC",
            (p["id"],),
        ).fetchall()
        pd = dict(p)
        pd["presentaciones"] = [dict(x) for x in pres]
        pd["base"] = next((x for x in pd["presentaciones"] if x["es_base"]), None)
        pd["packs"] = [x for x in pd["presentaciones"] if not x["es_base"]]
        productos_completos.append(pd)

    categorias = conn.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "inventario.html", activo="inventario", productos=productos_completos, categorias=categorias
    )


@app.route("/inventario/agregar", methods=["POST"])
@admin_requerido
def inventario_agregar():
    conn = get_db()
    imagen = _guardar_imagen(request.files.get("imagen"))
    categoria_id = request.form.get("categoria_id") or None

    cur = conn.execute(
        """INSERT INTO productos (codigo, nombre, categoria_id, imagen, stock, stock_minimo, activo)
           VALUES (?, ?, ?, ?, ?, ?, 1)""",
        (
            request.form.get("codigo") or None,
            request.form["nombre"],
            categoria_id,
            imagen,
            int(request.form["stock"]),
            int(request.form.get("stock_minimo") or 5),
        ),
    )
    producto_id = cur.lastrowid

    conn.execute(
        """INSERT INTO presentaciones (producto_id, nombre, factor, precio_costo, precio_venta, es_base)
           VALUES (?, 'Unidad', 1, ?, ?, 1)""",
        (producto_id, float(request.form.get("precio_costo") or 0), float(request.form["precio"])),
    )

    # Presentacion adicional opcional (pack) creada junto con el producto
    pack_nombre = request.form.get("pack_nombre", "").strip()
    pack_factor = request.form.get("pack_factor", "").strip()
    pack_precio = request.form.get("pack_precio", "").strip()
    if pack_nombre and pack_factor and pack_precio:
        factor = int(pack_factor)
        precio_venta = float(pack_precio)
        precio_costo_base = float(request.form.get("precio_costo") or 0)
        conn.execute(
            """INSERT INTO presentaciones (producto_id, nombre, factor, precio_costo, precio_venta, es_base)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (producto_id, pack_nombre, factor, precio_costo_base * factor, precio_venta),
        )

    conn.commit()
    conn.close()
    flash("Producto agregado correctamente", "success")
    return redirect(url_for("inventario"))


@app.route("/inventario/editar/<int:producto_id>", methods=["POST"])
@admin_requerido
def inventario_editar(producto_id):
    conn = get_db()
    imagen_nueva = _guardar_imagen(request.files.get("imagen"))
    categoria_id = request.form.get("categoria_id") or None

    if imagen_nueva:
        conn.execute(
            "UPDATE productos SET nombre=?, categoria_id=?, stock=?, stock_minimo=?, imagen=? WHERE id=?",
            (request.form["nombre"], categoria_id, int(request.form["stock"]),
             int(request.form.get("stock_minimo") or 5), imagen_nueva, producto_id),
        )
    else:
        conn.execute(
            "UPDATE productos SET nombre=?, categoria_id=?, stock=?, stock_minimo=? WHERE id=?",
            (request.form["nombre"], categoria_id, int(request.form["stock"]),
             int(request.form.get("stock_minimo") or 5), producto_id),
        )

    conn.execute(
        "UPDATE presentaciones SET precio_costo=?, precio_venta=? WHERE producto_id=? AND es_base=1",
        (float(request.form.get("precio_costo") or 0), float(request.form["precio"]), producto_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("inventario"))


@app.route("/inventario/eliminar/<int:producto_id>", methods=["POST"])
@admin_requerido
def inventario_eliminar(producto_id):
    conn = get_db()
    conn.execute("DELETE FROM presentaciones WHERE producto_id=?", (producto_id,))
    conn.execute("DELETE FROM productos WHERE id=?", (producto_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("inventario"))


@app.route("/inventario/presentacion/agregar/<int:producto_id>", methods=["POST"])
@admin_requerido
def presentacion_agregar(producto_id):
    conn = get_db()
    base = conn.execute(
        "SELECT * FROM presentaciones WHERE producto_id=? AND es_base=1", (producto_id,)
    ).fetchone()
    factor = int(request.form["factor"])
    precio_costo_base = base["precio_costo"] if base else 0
    conn.execute(
        """INSERT INTO presentaciones (producto_id, nombre, factor, precio_costo, precio_venta, es_base)
           VALUES (?, ?, ?, ?, ?, 0)""",
        (producto_id, request.form["nombre"], factor, precio_costo_base * factor, float(request.form["precio_venta"])),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("inventario"))


@app.route("/inventario/presentacion/eliminar/<int:presentacion_id>", methods=["POST"])
@admin_requerido
def presentacion_eliminar(presentacion_id):
    conn = get_db()
    conn.execute("DELETE FROM presentaciones WHERE id=? AND es_base=0", (presentacion_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("inventario"))


# ---------------------------------------------------------------------------
# Categorias (solo admin)
# ---------------------------------------------------------------------------
@app.route("/categorias", methods=["GET", "POST"])
@admin_requerido
def categorias():
    conn = get_db()
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if nombre:
            try:
                conn.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre,))
                conn.commit()
            except sqlite3.IntegrityError:
                flash("Esa categoría ya existe", "error")
    lista = conn.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
    conn.close()
    return render_template("categorias.html", activo="inventario", categorias=lista)


@app.route("/categorias/eliminar/<int:categoria_id>", methods=["POST"])
@admin_requerido
def categorias_eliminar(categoria_id):
    conn = get_db()
    conn.execute("UPDATE productos SET categoria_id=NULL WHERE categoria_id=?", (categoria_id,))
    conn.execute("DELETE FROM categorias WHERE id=?", (categoria_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("categorias"))


# ---------------------------------------------------------------------------
# Usuarios (solo admin)
# ---------------------------------------------------------------------------
@app.route("/usuarios", methods=["GET", "POST"])
@admin_requerido
def usuarios():
    conn = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        nombre_completo = request.form.get("nombre_completo", "").strip()
        password = request.form.get("password", "")
        rol = request.form.get("rol", "vendedor")
        if rol not in ("admin", "vendedor"):
            rol = "vendedor"
        if len(password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres", "error")
        else:
            try:
                conn.execute(
                    "INSERT INTO usuarios (username, password_hash, nombre_completo, rol) VALUES (?, ?, ?, ?)",
                    (username, generate_password_hash(password), nombre_completo, rol),
                )
                conn.commit()
                flash(f"Usuario '{username}' creado como {rol}", "success")
            except sqlite3.IntegrityError:
                flash("Ese nombre de usuario ya existe", "error")

    lista = conn.execute("SELECT * FROM usuarios ORDER BY rol, username").fetchall()
    conn.close()
    return render_template("usuarios.html", activo="usuarios", usuarios=lista)


@app.route("/usuarios/desactivar/<int:usuario_id>", methods=["POST"])
@admin_requerido
def usuarios_desactivar(usuario_id):
    if usuario_id == session["usuario_id"]:
        flash("No puedes desactivar tu propio usuario", "error")
        return redirect(url_for("usuarios"))
    conn = get_db()
    row = conn.execute("SELECT activo FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    nuevo_estado = 0 if row["activo"] else 1
    conn.execute("UPDATE usuarios SET activo=? WHERE id=?", (nuevo_estado, usuario_id))
    conn.commit()
    conn.close()
    return redirect(url_for("usuarios"))


# ---------------------------------------------------------------------------
# Configuracion (solo admin)
# ---------------------------------------------------------------------------
@app.route("/configuracion", methods=["GET", "POST"])
@admin_requerido
def configuracion():
    if request.method == "POST":
        set_config("whatsapp_numero", request.form.get("whatsapp_numero", "").strip())
        flash("Configuración guardada", "success")
        return redirect(url_for("configuracion"))
    return render_template(
        "configuracion.html", activo="configuracion",
        whatsapp_numero=get_config("whatsapp_numero", ""),
        url_catalogo=url_for("catalogo", _external=True),
    )


# ---------------------------------------------------------------------------
# Reportes (solo admin)
# ---------------------------------------------------------------------------
@app.route("/reportes")
@admin_requerido
def reportes():
    conn = get_db()
    ventas_recientes = conn.execute(
        """SELECT v.id, v.fecha, v.total, v.metodo_pago, v.anulada, v.anulada_motivo, u.username
           FROM ventas v JOIN usuarios u ON v.usuario_id = u.id
           ORDER BY v.id DESC LIMIT 100"""
    ).fetchall()
    total_hoy = conn.execute(
        "SELECT COALESCE(SUM(total),0) t FROM ventas WHERE fecha LIKE ? AND anulada = 0",
        (datetime.now().strftime("%Y-%m-%d") + "%",),
    ).fetchone()["t"]
    pendientes_sync = conn.execute(
        "SELECT COUNT(*) c FROM sync_pending WHERE sincronizado = 0"
    ).fetchone()["c"]
    pedidos_web = conn.execute(
        "SELECT * FROM pedidos_web ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return render_template(
        "reportes.html", activo="reportes", ventas=ventas_recientes, total_hoy=total_hoy,
        pendientes_sync=pendientes_sync, pedidos_web=pedidos_web,
    )


@app.route("/pedido-web/<int:pedido_id>/estado", methods=["POST"])
@admin_requerido
def pedido_web_estado(pedido_id):
    nuevo_estado = request.form.get("estado", "pendiente")
    conn = get_db()
    conn.execute("UPDATE pedidos_web SET estado=? WHERE id=?", (nuevo_estado, pedido_id))
    conn.commit()
    conn.close()
    return redirect(url_for("reportes"))


# ---------------------------------------------------------------------------
# Catalogo publico (sin login) + pedidos de clientes
# ---------------------------------------------------------------------------
@app.route("/catalogo")
def catalogo():
    conn = get_db()
    categoria_id = request.args.get("categoria")
    query = """SELECT p.*, c.nombre AS categoria_nombre FROM productos p
               LEFT JOIN categorias c ON p.categoria_id = c.id
               WHERE p.activo = 1 AND p.stock > 0"""
    params = []
    if categoria_id:
        query += " AND p.categoria_id = ?"
        params.append(categoria_id)
    query += " ORDER BY p.nombre"
    productos = conn.execute(query, params).fetchall()

    productos_con_precio = []
    for p in productos:
        base = conn.execute(
            "SELECT * FROM presentaciones WHERE producto_id=? AND es_base=1", (p["id"],)
        ).fetchone()
        pd = dict(p)
        pd["precio"] = base["precio_venta"] if base else 0
        productos_con_precio.append(pd)

    categorias = conn.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
    whatsapp = get_config("whatsapp_numero", "")
    conn.close()
    return render_template(
        "catalogo.html", productos=productos_con_precio, categorias=categorias,
        categoria_actual=categoria_id, whatsapp_tienda=whatsapp, nombre_tienda=NOMBRE_TIENDA,
    )


@app.route("/api/pedido-web", methods=["POST"])
def api_pedido_web():
    data = request.json
    carrito = data.get("carrito", [])
    cliente_nombre = (data.get("cliente_nombre") or "").strip()
    cliente_telefono = (data.get("cliente_telefono") or "").strip()
    metodo_pago = data.get("metodo_pago", "Coordinar")

    if not carrito:
        return jsonify({"error": "Tu pedido está vacío"}), 400
    if not cliente_nombre or not cliente_telefono:
        return jsonify({"error": "Indica tu nombre y tu número de celular"}), 400

    conn = get_db()
    try:
        conn.execute("BEGIN")
        total = 0.0
        detalles = []
        for item in carrito:
            producto = conn.execute("SELECT * FROM productos WHERE id=?", (item["producto_id"],)).fetchone()
            if not producto:
                continue
            base = conn.execute(
                "SELECT * FROM presentaciones WHERE producto_id=? AND es_base=1", (producto["id"],)
            ).fetchone()
            precio = base["precio_venta"] if base else 0
            cantidad = int(item["cantidad"])
            subtotal = precio * cantidad
            total += subtotal
            detalles.append((producto["id"], producto["nombre"], cantidad, precio, subtotal))

        cur = conn.execute(
            """INSERT INTO pedidos_web (fecha, cliente_nombre, cliente_telefono, metodo_pago, total, estado)
               VALUES (?, ?, ?, ?, ?, 'pendiente')""",
            (datetime.now().isoformat(timespec="seconds"), cliente_nombre, cliente_telefono, metodo_pago, total),
        )
        pedido_id = cur.lastrowid
        for producto_id, nombre, cantidad, precio, subtotal in detalles:
            conn.execute(
                """INSERT INTO pedido_detalle (pedido_id, producto_id, nombre_producto, cantidad, precio_unitario, subtotal)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (pedido_id, producto_id, nombre, cantidad, precio, subtotal),
            )
        conn.commit()
        return jsonify({"ok": True, "pedido_id": pedido_id, "total": total})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
