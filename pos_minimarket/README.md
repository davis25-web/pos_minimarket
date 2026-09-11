# Tienda d'Lianis — Sistema de Ventas

Sistema de punto de venta (POS) local y profesional, con catálogo web,
control de caja, roles de usuario, múltiples unidades de medida por
producto y más. Corre en tu propia computadora, sin depender de internet
para vender.

## Instalación

1. Necesitas Python 3.8 o superior.
2. Abre una terminal en esta carpeta:

```
pip install -r requirements.txt
python app.py
```

3. Sistema de ventas (caja): **http://localhost:5000**
4. Catálogo web para tus clientes: **http://localhost:5000/catalogo**
   (compártelo si tu compu y el celular del cliente están en la misma red Wi-Fi,
   usando la IP de tu compu en vez de "localhost", ej. http://192.168.1.5:5000/catalogo)

## Usuario inicial

- **Usuario:** admin — **Contraseña:** admin123 (cámbiala apenas puedas)

## Roles

- **Administrador**: acceso completo — Dashboard, Ventas, Inventario, Reportes,
  Usuarios, Configuración, anular ventas, ver catálogo web.
- **Vendedor**: solo puede vender, y aperturar/cerrar caja.

Crea usuarios vendedores desde **Usuarios** (solo visible para administradores).

## Funciones principales

- **Ventas**: carrito, métodos de pago (Efectivo/Yape/Plin/Tarjeta), cálculo
  automático de vuelto, precio editable en caja, cliente opcional.
- **Comprobante**: se genera tras cada venta — imprimible, con botón de
  WhatsApp para enviarlo al cliente. El envío por correo requiere configurar
  un servidor SMTP en `app.py` (te ayudo si quieres activarlo).
- **Apertura y cierre de caja**: obligatorio abrir caja antes de vender;
  al cerrar, el sistema compara el efectivo esperado contra el contado.
- **Anular venta**: solo administradores; devuelve el stock automáticamente.
- **Inventario con imágenes y categorías.**
- **Múltiples unidades de medida (packs)**: cada producto tiene una unidad
  base (la unidad suelta, en la que se lleva el stock) y puede tener además
  presentaciones tipo "Pack x12" con su propio precio. Al vender un pack,
  el sistema descuenta automáticamente `cantidad × factor` del stock base.
- **Dashboard**: ventas y ganancia del día, ganancia histórica, top productos,
  alertas de stock bajo, ventas por método de pago.
- **Catálogo web público** (`/catalogo`): tus clientes ven tus productos con
  fotos, arman un pedido, indican cómo van a pagar, y te llega a Reportes →
  Pedidos recibidos. Pueden escribirte por WhatsApp para coordinar el envío.

## Notas importantes

- El archivo `minimarket.db` guarda todo. Haz respaldo de vez en cuando
  (cópialo a un USB o a la nube).
- Si vienes de una versión anterior del sistema, tus productos, stock,
  precios, ventas y usuarios se conservan automáticamente al iniciar
  (migración automática de la base de datos).
- La "factura electrónica" generada es un comprobante interno imprimible,
  no un documento autorizado por SUNAT. Para eso se necesita integrar un
  proveedor certificado (ej. Nubefact, Efact) — puedo ayudarte con eso si
  lo necesitas más adelante.
