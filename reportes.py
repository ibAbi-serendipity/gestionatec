import os
import io
import datetime
import gspread
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from oauth2client.service_account import ServiceAccountCredentials

# Configurar acceso a Google Sheets
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds_dict = json.loads(os.environ.get("GOOGLE_CREDS"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
gc = gspread.authorize(creds)

def generar_reporte_pdf(phone_number):
    try:
        # Obtener hoja "Historial de movimientos"
        url = get_client_sheet_url(phone_number)
        if not url:
            return None
        doc = gc.open_by_url(url)
        try:
            historial = doc.worksheet("Historial de movimientos")
        except:
            return None

        registros = historial.get_all_records()
        if not registros:
            return None

        # Procesar los datos
        conteo_por_fecha = {}
        ventas_por_producto = {}

        for row in registros:
            if row.get("Tipo") == "Salida":
                fecha = row.get("Fecha")
                producto = row.get("Nombre")
                cantidad = int(row.get("Cantidad", 0))

                # Contar ventas por fecha
                if fecha:
                    conteo_por_fecha[fecha] = conteo_por_fecha.get(fecha, 0) + cantidad

                # Contar ventas por producto
                if producto:
                    ventas_por_producto[producto] = ventas_por_producto.get(producto, 0) + cantidad

        fechas_mas_ventas = sorted(conteo_por_fecha.items(), key=lambda x: x[1], reverse=True)[:5]
        productos_mas = sorted(ventas_por_producto.items(), key=lambda x: x[1], reverse=True)[:5]
        productos_menos = sorted(ventas_por_producto.items(), key=lambda x: x[1])[:5]

        # Crear PDF
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, height - 50, "📊 Reporte de Ventas")

        y = height - 100
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Fechas con más ventas:")
        c.setFont("Helvetica", 11)
        for fecha, total in fechas_mas_ventas:
            y -= 18
            c.drawString(60, y, f"{fecha}: {total} unidades")

        y -= 30
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Productos más vendidos:")
        c.setFont("Helvetica", 11)
        for prod, total in productos_mas:
            y -= 18
            c.drawString(60, y, f"{prod}: {total} unidades")

        y -= 30
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Productos menos vendidos:")
        c.setFont("Helvetica", 11)
        for prod, total in productos_menos:
            y -= 18
            c.drawString(60, y, f"{prod}: {total} unidades")

        c.showPage()
        c.save()
        buffer.seek(0)

        # Guardar en archivo temporal (puedes subirlo a un bucket o retornar el path local)
        filename = f"reporte_{phone_number}.pdf"
        filepath = os.path.join("./reportes", filename)
        os.makedirs("./reportes", exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(buffer.read())

        return filepath  # Retorna la ruta local del PDF

    except Exception as e:
        print(f"Error generando reporte: {e}")
        return None

# Esta función debe estar disponible desde google_sheets.py o duplicarse aquí:
def get_client_sheet_url(phone_number):
    clientes_sheet = gc.open("Clientes").sheet1
    rows = clientes_sheet.get_all_records()
    for row in rows:
        if str(row.get("Número", "")).strip() == phone_number:
            return row.get("URL de hoja")
    return None
