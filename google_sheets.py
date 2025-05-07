import os
import json
import gspread
import logging
from oauth2client.service_account import ServiceAccountCredentials

# Configurar logging
logging.basicConfig(level=logging.INFO)

# Configura el alcance de la API de Google Sheets
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# Lee las credenciales desde una variable de entorno (asegúrate de tener la variable GOOGLE_CREDS configurada)
creds_json = os.environ.get("GOOGLE_CREDS")

if not creds_json:
    logging.error("❌ No se encontró la variable de entorno GOOGLE_CREDS")
    exit()

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)

# Autenticar con Google Sheets
gc = gspread.authorize(creds)

def get_client_sheet_url(phone_number):
    """
    Busca el número de cliente en la hoja de clientes y devuelve el enlace de su hoja de productos.
    """
    try:
        # Abre la hoja de clientes (asegúrate de que esta hoja exista)
        clientes_sheet = gc.open("Clientes").sheet1
    except Exception as e:
        logging.error(f"❌ Error al abrir hoja 'Clientes': {e}")
        return None

    try:
        # Obtén todas las filas de la hoja 'Clientes'
        rows = clientes_sheet.get_all_records()
        logging.info(f"📄 {len(rows)} filas leídas de hoja 'Clientes'")
    except Exception as e:
        logging.error(f"❌ Error al leer filas: {e}")
        return None

    # Busca el cliente por número
    for row in rows:
        numero_hoja = str(row.get("Número", "")).strip()
        if numero_hoja == phone_number.strip():
            logging.info(f"✅ Cliente encontrado: {row.get('Nombre')}")
            try:
                # Obtener URL de la hoja de productos
                url = row.get("URL de hoja")
                return url
            except Exception as e:
                logging.error(f"❌ Error al obtener URL de la hoja del cliente: {e}")
                return None

    logging.warning("⚠️ Número no encontrado en la hoja de clientes.")
    return None

def get_inventory_sheet_for_number(phone_number):
    """
    Obtiene la hoja de inventario asociada al número de teléfono del cliente.
    """
    url = get_client_sheet_url(phone_number)
    if url:
        try:
            # Abre la hoja del cliente a partir de la URL
            cliente_sheet = gc.open_by_url(url)
            return cliente_sheet.sheet1  # Devuelve la primera hoja de la URL
        except Exception as e:
            logging.error(f"❌ Error al abrir la hoja del cliente: {e}")
            return None
    else:
        return None

def obtener_productos(hoja):
    data = hoja.get_all_values()[1:]  # Ignora la fila de encabezado
    productos = []
    for row in data:
        if len(row) >= 9:
            producto = {
                "codigo": row[0],
                "nombre": row[1],
                "marca": row[2],
                "fecha": row[3],
                "costo": row[4],
                "cantidad": row[5],
                "precio": row[6],
                "stock_minimo": row[7],
                "ultima_compra": row[8]
            }
            productos.append(producto)
    return productos
    except Exception as e:
        logging.error(f"❌ Error al leer los datos de la hoja del cliente: {e}")
        return None
    
