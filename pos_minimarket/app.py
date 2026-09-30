# =========================================================
# ARCHIVO COMPLETO: app.py (Auto-Detector de Base de Datos e Imágenes)
# =========================================================
import os
from io import BytesIO
from flask import Flask, render_template, send_from_directory, send_file, url_for, abort
import sqlite3

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_db_connection():
    """
    Busca automáticamente el archivo de la base de datos SQLite 
    en todas las carpetas posibles de Render (minimarket.db, minimarket, pos_minimarket.db, etc.)
    """
    candidatos = [
        os.path.join(BASE_DIR, 'datos_tienda', 'minimarket.db'),
        os.path.join(BASE_DIR, 'datos_tienda', 'minimarket'),
        os.path.join(BASE_DIR, 'datos_tienda', 'pos_minimarket.db'),
        os.path.join(BASE_DIR, 'datos_tienda', 'tienda.db'),
        os.path.join(BASE_DIR, 'minimarket.db'),
        os.path.join(BASE_DIR, 'minimarket'),
        os.path.join(BASE_DIR, 'pos_minimarket.db'),
    ]
    
    # Escanear la carpeta datos_tienda por cualquier archivo de base de datos
    carpeta_datos = os.path.join(BASE_DIR, 'datos_tienda')
    if os.path.exists(carpeta_datos):
        for f in os.listdir(carpeta_datos):
            if not f.endswith('-shm') and not f.endswith('-wal') and not f.endswith('.log') and not f.endswith('.txt'):
                candidatos.append(os.path.join(carpeta_datos, f))

    for ruta in candidatos:
        if os.path.exists(ruta) and os.path.isfile(ruta):
            try:
                conn = sqlite3.connect(ruta)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                # Verificar si contiene tablas de productos
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('productos', 'producto')")
                if cursor.fetchone():
                    return conn
                conn.close()
            except Exception:
                continue

    # Fallback si aún no existe
    ruta_default = os.path.join(BASE_DIR, 'datos_tienda', 'minimarket.db')
    conn = sqlite3.connect(ruta_default)
    conn.row_factory = sqlite3.Row
    return conn

# =========================================================
# RUTA PARA SERVIR IMÁGENES
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

    # 1. Coincidencia exacta
    for carpeta in posibles_carpetas:
        ruta_completa = os.path.join(carpeta, filename)
        if os.path.exists(ruta_completa) and os.path.isfile(ruta_completa):
            return send_from_directory(carpeta, filename)

    # 2. Insensible a mayúsculas/minúsculas
    for carpeta in posibles_carpetas:
        if os.path.exists(carpeta):
            try:
                for f in os.listdir(carpeta):
                    if f.lower() == filename.lower():
                        return send_from_directory(carpeta, f)
            except Exception:
                continue

    # 3. Fallback SVG si no se encuentra
    svg_fallback = '''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="background:#f3e8ff;"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>'''
    return send_file(BytesIO(svg_fallback.encode('utf-8')), mimetype='image/svg+xml')

# =========================================================
# RUTA DEL CATÁLOGO ONLINE
# =========================================================
@app.route('/')
@app.route('/catalogo')
def catalogo():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Buscar en tabla 'productos' o 'producto'
        try:
            cursor.execute("SELECT * FROM productos")
        except sqlite3.OperationalError:
            cursor.execute("SELECT * FROM producto")

        productos_raw = cursor.fetchall()
        conn.close()

        productos = []
        for p in productos_raw:
            prod = dict(p)
            # Mapear campos flexibles (compatibilidad con diferentes esquemas SQL)
            prod['nombre'] = prod.get('nombre') or prod.get('producto') or 'Producto'
            prod['precio'] = prod.get('precio') or prod.get('p_venta') or prod.get('costo') or 0.0
            nombre_img = prod.get('imagen') or prod.get('foto') or prod.get('img') or 'default.svg'
            prod['imagen_url'] = url_for('servir_imagen_producto', filename=nombre_img)
            productos.append(prod)

        return render_template('catalogo.html', productos=productos)

    except Exception as e:
        app.logger.error(f"Error en catálogo: {e}")
        return render_template('catalogo.html', productos=[], error=str(e))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
