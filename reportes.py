import os
import io
import json
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials
import gspread
from gspread.exceptions import WorksheetNotFound
import logging

# --- Configuración Google API ---
SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/spreadsheets.readonly']
creds_json = os.environ.get("GOOGLE_CREDS")
creds_dict = json.loads(creds_json)
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

drive_service = build('drive', 'v3', credentials=creds)
gsheets_client = gspread.authorize(creds)

# --- Funciones ---
def get_historial_sheet(phone_number):
    try:
        logging.info(f"🔍 Buscando hoja de historial para número: {phone_number}")
        clientes_sheet = gsheets_client.open("Clientes").sheet1
        rows = clientes_sheet.get_all_records()
        logging.info(f"📄 Total de filas leídas en hoja 'Clientes': {len(rows)}")

        for row in rows:
            numero = str(row.get("Número", "")).strip()
            url = row.get("URL de hoja", "").strip()
            logging.info(f"🔎 Revisando fila: número={numero}, url={url}")

            if numero == phone_number:
                logging.info(f"✅ Número {phone_number} encontrado en hoja de clientes.")
                if url:
                    try:
                        logging.info(f"🌐 Intentando abrir hoja con URL: {url}")
                        libro = gsheets_client.open_by_url(url)
                        hoja = libro.worksheet("Historial de movimientos")
                        logging.info(f"📘 Hoja 'Historial de movimientos' accedida correctamente.")
                        return hoja
                    except WorksheetNotFound:
                        logging.error("❌ La hoja 'Historial de movimientos' no existe en el archivo.")
                        return None
                else:
                    logging.info("⚠️ No se encontró URL para este número.")
                    return None

        logging.info("⚠️ Número no encontrado en la hoja de clientes.")
        return None
    except Exception as e:
        logging.info(f"❌ Error general en get_historial_sheet: {e}")
        return None


def analizar_datos(historial):
    data = historial.get_all_values()[1:]  # Ignorar encabezado
    conteo_fechas = {}
    conteo_productos = {}

    for row in data:
        fecha = row[0].strip().lstrip("'")
        codigo = row[1].strip()
        nombre = row[2].strip()
        tipo = row[3].strip().lower()
        cantidad = int(row[4].strip().lstrip("'"))

        # Acumular por fecha
        if tipo.lower() == "salida":
            conteo_fechas[fecha] = conteo_fechas.get(fecha, 0) + cantidad
            conteo_productos[nombre] = conteo_productos.get(nombre, 0) + cantidad

    fecha_mas_ventas = max(conteo_fechas.items(), key=lambda x: x[1], default=("N/A", 0))
    mas_vendido = max(conteo_productos.items(), key=lambda x: x[1], default=("N/A", 0))
    menos_vendido = min(conteo_productos.items(), key=lambda x: x[1], default=("N/A", 0))

    return fecha_mas_ventas, mas_vendido, menos_vendido

def generar_pdf(fecha_max, mas_vendido, menos_vendido, filename):
    c = canvas.Canvas(filename, pagesize=A4)
    c.setFont("Helvetica", 14)
    c.drawString(50, 800, "📊 Reporte de ventas")

    c.setFont("Helvetica", 12)
    c.drawString(50, 770, f"• Fecha con más ventas: {fecha_max[0]} ({fecha_max[1]} unidades)")
    c.drawString(50, 750, f"• Producto más vendido: {mas_vendido[0]} ({mas_vendido[1]} unidades)")
    c.drawString(50, 730, f"• Producto menos vendido: {menos_vendido[0]} ({menos_vendido[1]} unidades)")

    c.drawString(50, 690, f"Generado el: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.save()

def subir_pdf_drive(filepath, filename):
    # Coloca aquí el ID de tu carpeta de Drive
    CARPETA_ID = "170H9rV7p5EsO6EF7oyyZSXPZXoVLryEt"
    file_metadata = {
        'name': filename,
        'parents': [CARPETA_ID],
        'mimeType': 'application/pdf'
    }
    media = MediaFileUpload(filepath, mimetype='application/pdf')
    file = drive_service.files().create(
        body=file_metadata, 
        media_body=media, 
        fields='id'
    ).execute()
    file_id = file.get('id')

    drive_service.permissions().create(
        fileId=file_id,
        body={'type': 'anyone', 'role': 'reader'},
    ).execute()

    return f"https://drive.google.com/uc?id={file_id}&export=download"

def generar_reporte_pdf(phone_number):
    print(f"📊 Generando reporte para el número: {phone_number}")
    hoja = get_historial_sheet(phone_number)
    if not hoja:
        print("⚠️ No se encontró la hoja de historial.")
        return None

    fecha_max, mas_vendido, menos_vendido = analizar_datos(hoja)
    print(f"📈 Datos: {fecha_max}, {mas_vendido}, {menos_vendido}")
    filename = f"reporte_{phone_number}.pdf"
    filepath = os.path.join("/tmp", filename)
    generar_pdf(fecha_max, mas_vendido, menos_vendido, filepath)

    url_pdf = subir_pdf_drive(filepath, filename)
    print(f"✅ PDF subido a: {url_pdf}")
    return url_pdf
