from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from google_sheets import obtener_productos  # Importamos la función para obtener los productos

app = Flask(__name__)

user_states = {}  # Aquí definimos el diccionario para guardar el estado de los usuarios

@app.route("/webhook", methods=["POST"])
def whatsapp_bot():
    incoming_msg = request.values.get("Body", "").strip()
    phone_number = request.values.get("From", "").replace("whatsapp:", "").replace("+", "")
    
    print(f"📱 Mensaje recibido de {phone_number}: {incoming_msg}")
    
    resp = MessagingResponse()
    msg = resp.message()
    
    if incoming_msg.lower() in ["hola", "menu", "inicio"]:
        user_states.pop(phone_number, None)  # Limpiamos el estado del usuario
        menu = (
            "👋 ¡Bienvenido al bot de inventario!\n"
            "Elige una opción:\n"
            "1️⃣ Ver productos\n"
            "2️⃣ Filtrar por código\n"
            "3️⃣ Agregar producto\n"
            "4️⃣ Actualizar producto\n"
            "5️⃣ Eliminar producto\n"
            "6️⃣ Registrar entrada\n"
            "7️⃣ Registrar salida\n"
            "8️⃣ Reporte\n"
            "9️⃣ Sugerencias de compra\n"
            "0️⃣ Revisar stock mínimo / vencimiento"
        )
        msg.body(menu)
        return str(resp)

    # Opción 1: Ver productos
    elif incoming_msg == "1":
        hoja_cliente = get_inventory_sheet_for_number(phone_number)  # Obtén la hoja de productos del cliente
        if not hoja_cliente:
            msg.body("❌ No se encontró la hoja de productos para tu número.")
        else:
            productos = obtener_productos(hoja_cliente)  # Obtener productos desde Google Sheets
            if not productos:
                msg.body("📭 No hay productos registrados.")
            else:
                respuesta = "📦 Productos en inventario:\n"
                for i, p in enumerate(productos, start=1):
                    respuesta += (
                        f"{i}. {p['nombre']} - {p['marca']}, Vence: {p['fecha']}, "
                        f"Stock: {p['cantidad']} - Precio: S/ {p['precio']}\n"
                    )
                msg.body(respuesta)

    else:
        msg.body("Envía 'menu' para ver las opciones disponibles.")

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
