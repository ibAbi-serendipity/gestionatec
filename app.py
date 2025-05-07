from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from google_sheets import obtener_productos, get_inventory_sheet_for_number  # Importamos la función para obtener los productos

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
        hoja_cliente = get_inventory_sheet_for_number(phone_number)
        if not hoja_cliente:
            msg.body("❌ No se encontró la hoja de productos para tu número.")
        else:
            productos = obtener_productos(hoja_cliente)
            if productos is None:
                msg.body("⚠️ Hubo un error al leer los productos. Intenta nuevamente.")
            elif not productos:
                msg.body("📭 No hay productos registrados.")
            else:
                respuesta = "📦 *Productos en inventario:*\n"
                for i, p in enumerate(productos, start=1):
                    respuesta += (
                        f"{i}. *{p['nombre']}* ({p['marca']}) - {p['codigo']}\n"
                        f"   🗓️ Vence: {p['fecha']} | 📦 Stock: {p['cantidad']} | 💰 S/ {p['precio']}\n"
                    )
                msg.body(respuesta)

    # Opción 2: Filtrar por código
    elif incoming_msg == "2":
        pass

    # Opción 3: Agregar producto
    elif incoming_msg == "3":
        user_states[phone_number] = {"step": "esperando_datos"}
        msg.body("Por favor envía los datos del producto en este formato:\n"
                 "Nombre, Marca, Fecha de vencimiento (AAAA-MM-DD), Costo, Cantidad, Precio, Stock Mínimo, Fecha de compra (AAAA-MM-DD)\n")

    elif phone_number in user_states:
        estado = user_states[phone_number]

        # Paso 1: Esperar datos
        if estado["step"] == "esperando_datos":
            partes = [x.strip() for x in incoming_msg.split(",")]
            if len(partes) != 8:
                msg.body("❌ Formato incorrecto. Asegúrate de enviar: Nombre, Marca, Fecha, Costo, Cantidad, Precio, Stock Mínimo")
            else:
                estado.update({
                    "nombre": partes[0],
                    "marca": partes[1],
                    "fecha": partes[2],
                    "costo": partes[3],
                    "cantidad": partes[4],
                    "precio": partes[5],
                    "stock_minimo": partes[6],
                    "ultima_compra": partes[7],
                    "step": "esperando_categoria"
                })
                msg.body("📦 ¿Cuál es la categoría del producto? (perecible / no perecible / limpieza / herramienta o material)")

        # Paso 2: Esperar categoría
        elif estado["step"] == "esperando_categoria":
            categorias = {
                "perecible": "1",
                "no perecible": "2",
                "limpieza": "3",
                "herramienta o material": "4"
            }
            cat = incoming_msg.lower()
            if cat not in categorias:
                msg.body("❌ Categoría no válida. Elige: perecible / no perecible / limpieza / herramienta o material")
            else:
                estado["categoria"] = categorias[cat]
                estado["step"] = "esperando_empaque"
                msg.body("📦 ¿Cuál es el tipo de empaque? (unidad / caja / bolsa / paquete / saco / botella / lata / tetrapack / sobre)")

        # Paso 3: Esperar empaque y guardar
        elif estado["step"] == "esperando_empaque":
            empaque = incoming_msg.strip().lower()
            if not empaque:
                msg.body("❌ Tipo de empaque no válido.")
            else:
                estado["empaque"] = empaque
                hoja = get_inventory_sheet_for_number(phone_number)
                if not hoja:
                    msg.body("❌ No se pudo acceder a tu hoja de inventario.")
                    return str(resp)

                # Leer productos para determinar correlativo
                productos = hoja.get_all_values()
                encabezados = productos[0] if productos else []
                data = productos[1:] if len(productos) > 1 else []
                correlativos = [
                    int(p[0][-2:]) for p in data
                    if p[0].startswith(estado["categoria"] + estado["marca"][0].upper() + empaque[0].upper())
                    and len(p[0]) >= 4 and p[0][-2:].isdigit()
                ]
                nuevo_num = str(max(correlativos, default=0) + 1).zfill(2)
                codigo = estado["categoria"] + estado["marca"][0].upper() + empaque[0].upper() + nuevo_num

                nuevo_producto = [
                    codigo,
                    estado["nombre"],
                    estado["marca"],
                    estado["fecha"],
                    estado["costo"],
                    estado["cantidad"],
                    estado["precio"],
                    estado["stock_minimo"],
                    estado["ultima_compra"],
                    ""  # última compra (puede llenarse luego)
                ]
                hoja.append_row(nuevo_producto)
                msg.body(f"✅ Producto '{estado['nombre']}' agregado con código {codigo}.\n"
                        "¿Deseas registrar otro producto? (sí / no)")
                estado.clear()
                estado["step"] = "confirmar_continuar"
                return str(resp)
        
        # Paso final: Confirmar si desea registrar otro
        elif estado["step"] == "confirmar_continuar":
            if incoming_msg.lower() in ["sí", "si"]:
                estado["step"] = "esperando_datos"
                msg.body("Por favor envía los datos del nuevo producto en este formato:\n"
                         "Nombre, Marca, Fecha (AAAA-MM-DD), Costo, Cantidad, Precio, Stock Mínimo")
            elif incoming_msg.lower() == "no":
                user_states.pop(phone_number)
                msg.body("📋 Has salido del registro de productos. Escribe 'menu' para ver las opciones.")
            else:
                msg.body("❓ Respuesta no válida. Escribe 'sí' para registrar otro producto o 'no' para salir.")

    else:
        msg.body("Envía 'menu' para ver las opciones disponibles.")

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)