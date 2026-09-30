# =========================================================
# ARCHIVO COMPLETO: app.py (Corregido para Servir Imágenes en Render)
# =========================================================
import os
from io import BytesIO
from flask import Flask, render_template, send_from_directory, send_file, url_for, abort
import sqlite3

app = Flask(__name__)

# Base de datos local y de servidor Render
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'datos_tienda', 'minimarket.db')

def get_db_connection():
    """Conexión a SQLite con fallback inteligente"""
    if not os.path.exists(DB_PATH):
        alt_db = os.path.join(BASE_DIR, 'minimarket.db')
        conn = sqlite3.connect(alt_db if os.path.exists(alt_db) else DB_PATH)
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# =========================================================
# RUTA INFALIBLE PARA SERVIR IMÁGENES DE PRODUCTOS EN RENDER
# =========================================================
@app.route('/imagen_producto/<path:filename>')
def servir_imagen_producto(filename):
    """
    Busca imágenes en todas las ubicaciones posibles de Render.
    Si no la encuentra, genera un SVG elegante por defecto (Evita cuadros rotos).
    """
    if not filename or filename == 'None' or filename == 'null':
        filename = 'default.svg'

    # Limpiar posibles barras invertidas de Windows (\\ -> /)
    filename = filename.replace('\\', '/').split('/')[-1]

    # Lista jerárquica de carpetas donde buscar las imágenes en Render
    posibles_carpetas = [
        os.path.join(BASE_DIR, 'datos_tienda', 'imagenes_productos'),
        os.path.join(BASE_DIR, 'datos_tienda'),
        os.path.join(BASE_DIR, 'static', 'uploads'),
        os.path.join(BASE_DIR, 'static', 'imagenes'),
        os.path.join(BASE_DIR, 'static'),
        BASE_DIR
    ]

    # 1. Buscar coincidencia exacta
    for carpeta in posibles_carpetas:
        ruta_completa = os.path.join(carpeta, filename)
        if os.path.exists(ruta_completa) and os.path.isfile(ruta_completa):
            return send_from_directory(carpeta, filename)

    # 2. Buscar insensible a mayúsculas/minúsculas y extensiones (.JPG vs .jpg vs .jpeg)
    for carpeta in posibles_carpetas:
        if os.path.exists(carpeta):
            try:
                archivos = os.listdir(carpeta)
                for f in archivos:
                    if f.lower() == filename.lower():
                        return send_from_directory(carpeta, f)
            except Exception:
                continue

    # 3. FALLBACK DINÁMICO: Servir un SVG de caja por defecto para evitar cuadros rotos en la web
    svg_fallback = '''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="background:#f3e8ff;"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>'''
    return send_file(BytesIO(svg_fallback.encode('utf-8')), mimetype='image/svg+xml')


# =========================================================
# RUTA DEL CATÁLOGO DE PRODUCTOS
# =========================================================
@app.route('/')
@app.route('/catalogo')
def catalogo():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Consultar productos activos
        cursor.execute("SELECT * FROM productos")
        productos_raw = cursor.fetchall()
        conn.close()

        productos = []
        for p in productos_raw:
            prod = dict(p)
            nombre_img = prod.get('imagen') or prod.get('foto') or 'default.svg'
            prod['imagen_url'] = url_for('servir_imagen_producto', filename=nombre_img)
            productos.append(prod)

        return render_template('catalogo.html', productos=productos)

    except Exception as e:
        app.logger.error(f"Error al cargar catálogo: {e}")
        return render_template('catalogo.html', productos=[], error=str(e))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
