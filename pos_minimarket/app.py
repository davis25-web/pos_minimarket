# =========================================================
# ARCHIVO COMPLETO: pos_minimarket/app.py
# =========================================================
import os
from io import BytesIO
from flask import Flask, render_template, send_from_directory, send_file, url_for, abort
import sqlite3

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_db_connection():
    """Conexión SQLite con autodetección de base de datos"""
    candidatos = [
        os.path.join(BASE_DIR, 'datos_tienda', 'minimarket.db'),
        os.path.join(BASE_DIR, 'datos_tienda', 'minimarket'),
        os.path.join(BASE_DIR, 'datos_tienda', 'pos_minimarket.db'),
        os.path.join(BASE_DIR, 'datos_tienda', 'tienda.db'),
        os.path.join(BASE_DIR, 'minimarket.db'),
        os.path.join(BASE_DIR, 'minimarket'),
    ]
    
    carpeta_datos = os.path.join(BASE_DIR, 'datos_tienda')
    if os.path.exists(carpeta_datos):
        for f in os.listdir(carpeta_datos):
            if not f.endswith(('-shm', '-wal', '.log', '.txt')):
                candidatos.append(os.path.join(carpeta_datos, f))

    for ruta in candidatos:
        if os.path.exists(ruta) and os.path.isfile(ruta):
            try:
                conn = sqlite3.connect(ruta)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('productos', 'producto')")
                if cursor.fetchone():
                    return conn
                conn.close()
            except Exception:
                continue

    conn = sqlite3.connect(os.path.join(BASE_DIR, 'datos_tienda', 'minimarket.db'))
    conn.row_factory = sqlite3.Row
    return conn

# =========================================================
# RUTA DE IMÁGENES CON FALLBACK
# =========================================================
@app.route('/imagen_producto/<path:filename>')
def servir_imagen_producto(filename):
    if not filename or filename in ['None', 'null', '']:
        filename = 'default.svg'

    filename = filename.replace('\\', '/').split('/')[-1]

    posibles_carpetas = [
        os.path.join(BASE_DIR, 'datos_tienda', 'imagenes_productos'),
        os.path.join(BASE_DIR, 'datos_tienda'),
        os.path.join(BASE_DIR, 'static', 'uploads'),
        os.path.join(BASE_DIR, 'static'),
        BASE_DIR
    ]

    for carpeta in posibles_carpetas:
        ruta = os.path.join(carpeta, filename)
        if os.path.exists(ruta) and os.path.isfile(ruta):
            return send_from_directory(carpeta, filename)

    for carpeta in posibles_carpetas:
        if os.path.exists(carpeta):
            try:
                for f in os.listdir(carpeta):
                    if f.lower() == filename.lower():
                        return send_from_directory(carpeta, f)
            except Exception:
                continue

    svg_fallback = '''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="background:#f3e8ff;"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>'''
    return send_file(BytesIO(svg_fallback.encode('utf-8')), mimetype='image/svg+xml')

# =========================================================
# RUTA DEL CATÁLOGO ONLINE COMPLETO
# =========================================================
@app.route('/')
@app.route('/catalogo')
def catalogo():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM productos")
        except sqlite3.OperationalError:
            cursor.execute("SELECT * FROM producto")

        productos_raw = cursor.fetchall()
        conn.close()

        productos = []
        categorias = set()

        for p in productos_raw:
            prod = dict(p)
            
            # Autodetección de Nombre
            prod['nombre'] = prod.get('nombre') or prod.get('producto') or prod.get('descripcion') or 'Producto'
            
            # Autodetección de Precio (precio_venta, p_venta, precio_unitario, etc.)
            raw_precio = (
                prod.get('precio_venta') if prod.get('precio_venta') is not None else
                prod.get('precio') if prod.get('precio') is not None else
                prod.get('p_venta') if prod.get('p_venta') is not None else
                prod.get('precio_unitario') if prod.get('precio_unitario') is not None else
                prod.get('precio_publico') if prod.get('precio_publico') is not None else 0.0
            )
            try:
                prod['precio'] = float(raw_precio)
            except (ValueError, TypeError):
                prod['precio'] = 0.0

            # Autodetección de Categoría
            cat = prod.get('categoria') or prod.get('categoria_nombre') or prod.get('rubro') or 'General'
            prod['categoria'] = str(cat).strip().title()
            categorias.add(prod['categoria'])

            # URL de la Imagen
            nombre_img = prod.get('imagen') or prod.get('foto') or prod.get('img') or 'default.svg'
            prod['imagen_url'] = url_for('servir_imagen_producto', filename=str(nombre_img))
            
            productos.append(prod)

        return render_template('catalogo.html', productos=productos, categorias=sorted(list(categorias)))

    except Exception as e:
        app.logger.error(f"Error en catálogo: {e}")
        return render_template('catalogo.html', productos=[], categorias=[], error=str(e))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
