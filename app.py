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
    elif phone_number in user_states:
        estado = user_states[phone_number]

        # Paso 1: Esperar datos
        if estado.get("step") == "esperando_datos":
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
        elif estado.get("step") == "esperando_categoria":
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
        elif estado.get("step")== "esperando_empaque":
            empaque = incoming_msg.strip().lower()
            if not empaque:
                msg.body("❌ Tipo de empaque no válido.")
            else:
                estado["empaque"] = empaque
                hoja = get_inventory_sheet_for_number(phone_number)
                if not hoja:
                    msg.body("❌ No se pudo acceder a tu hoja de inventario.")
                    return str(resp)

                # Generar prefijo del código
                categoria_num = estado["categoria"]
                marca_inicial = estado["marca"][0].upper()
                empaque_inicial = empaque[0].upper()
                prefijo_codigo = f"{categoria_num}{marca_inicial}{empaque_inicial}"

                # Obtener productos existentes
                productos = hoja.get_all_values()
                data = productos[1:] if len(productos) > 1 else []

                # Filtrar y contar correlativos con el mismo prefijo
                correlativos = []
                for fila in data:
                    if len(fila) > 0:
                        codigo = fila[0]
                        if codigo.startswith(prefijo_codigo) and len(codigo) >= 4 and codigo[-2:].isdigit():
                            correlativos.append(int(codigo[-2:]))

                nuevo_num = str(max(correlativos, default=0) + 1).zfill(2)
                codigo = f"{prefijo_codigo}{nuevo_num}"

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
        elif estado.get("step") == "confirmar_continuar":
            if incoming_msg.lower() in ["sí", "si"]:
                estado["step"] = "esperando_datos"
                msg.body("Por favor envía los datos del nuevo producto en este formato:\n"
                         "'Nombre, Marca, Fecha (AAAA-MM-DD), Costo, Cantidad, Precio, Stock Mínimo'")
            elif incoming_msg.lower() == "no":
                user_states.pop(phone_number)
                msg.body("📋 Has salido del registro de productos. Escribe 'menu' para ver las opciones.")
            else:
                msg.body("❓ Respuesta no válida. Escribe 'sí' para registrar otro producto o 'no' para salir.")

        elif estado.get("step") == "esperando_codigo":
            filtro_codigo = incoming_msg.upper().strip()
            hoja_cliente = get_inventory_sheet_for_number(phone_number)
        
            if not hoja_cliente:
                msg.body("❌ No se encontró tu hoja de productos.")
                user_states.pop(phone_number)
            else:
                productos = obtener_productos(hoja_cliente)
                coincidencias = [p for p in productos if p["codigo"].upper().startswith(filtro_codigo)]

                if not coincidencias:
                    msg.body("❌ No se encontraron productos con ese código. ¿Deseas intentar con otro código? (sí / no)")
                elif len(coincidencias) == 1:
                    p = coincidencias[0]
                    respuesta = (
                        f"🔎 Detalles del producto con código {p['codigo']}:\n"
                        f"📌 Nombre: {p['nombre']}\n"
                        f"🏷️ Marca: {p['marca']}\n"
                        f"📅 Fecha de caducidad: {p['fecha']}\n"
                        f"💰 Costo: S/ {p['costo']}\n"
                        f"📦 Cantidad: {p['cantidad']}\n"
                        f"💵 Precio: S/ {p['precio']}\n"
                        f"📉 Stock mínimo: {p['stock_minimo']}\n"
                        f"🛒 Última compra: {p['ultima_compra']}\n\n"
                        "¿Deseas consultar otro código? (sí / no)"
                    )
                    msg.body(respuesta)
                else:
                    respuesta = f"🔍 Se encontraron {len(coincidencias)} productos:\n"
                    for i, p in enumerate(coincidencias, start=1):
                        respuesta += f"{i}. {p['nombre']} - {p['marca']}, Stock: {p['cantidad']} (Código: {p['codigo']})\n"
                    respuesta += "\n¿Deseas consultar otro código? (sí / no)"
                    msg.body(respuesta)
                
                user_states[phone_number] = {"step": "preguntar_otro_codigo"}

            elif estado.get("step") == "preguntar_otro_codigo":
                if incoming_msg.lower() in ["sí", "si", "s"]:
                    user_states[phone_number] = {"step": "esperando_codigo"}
                    msg.body("🔍 Escribe el siguiente código que deseas consultar:")
                else:
                    user_states.pop(phone_number)
                    msg.body("✅ Consulta finalizada. Escribe 'menu' para ver más opciones.")
        # Paso 4: Actualizar producto
        elif estado.get("step") == "esperando_codigo_actualizar":
            codigo = incoming_msg.strip().upper()
            hoja = get_inventory_sheet_for_number(phone_number)
            productos = hoja.get_all_values()

            encontrado = None
            for i, row in enumerate(productos[1:], start=2):  # saltamos encabezado
                if row[0] == codigo:
                    encontrado = (i, row)
                    break

            if encontrado:
                fila, producto = encontrado
                user_states[phone_number] = {
                    "step": "esperando_campo_a_modificar",
                    "fila": fila,
                    "producto": producto,
                    "codigo": codigo
                }
                msg.body(
                    f"🔍 Producto encontrado: {producto[1]} - {producto[2]}\n"
                    "¿Qué campo deseas modificar? (fecha / costo / precio / stock mínimo)"
                )
            
            if not encontrado:
                msg.body("❌ Producto no encontrado. ¿Deseas ingresar otro código? (sí / no)")
                user_states[phone_number] = {"step": "confirmar_codigo_nuevamente_4"}
                return str(resp)
        
        elif phone_number in user_states and user_states[phone_number].get("step") == "confirmar_codigo_nuevamente_4":
            if incoming_msg.lower() == "si":
                user_states[phone_number] = {"step": "esperando_codigo_actualizar"}
                msg.body("🔄 Ingresa el código del producto que deseas actualizar:")
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Volviendo al menú principal. Envía 'menu' para ver opciones.")
            return str(resp)

        elif phone_number in user_states and user_states[phone_number].get("step") == "esperando_campo_a_modificar":
            campo = incoming_msg.strip().lower()
            campos_validos = {
                "fecha": 3,
                "costo": 4,
                "precio": 6,
                "stock mínimo": 7
            }

            user_states[phone_number]["campo"] = campo
            user_states[phone_number]["columna"] = campos_validos[campo]
            user_states[phone_number]["step"] = "esperando_nuevo_valor"
            msg.body(f"✏️ Ingresa el nuevo valor para '{campo}':")
            return str(resp)
            if campo not in campos_validos:
                msg.body("❌ Campo no válido. Elige entre: fecha / costo / precio / stock mínimo")
                return str(resp)
    
        elif phone_number in user_states and user_states[phone_number].get("step") == "esperando_nuevo_valor":
            nuevo_valor = incoming_msg.strip()
            hoja = get_inventory_sheet_for_number(phone_number)
            fila = user_states[phone_number]["fila"]
            columna = user_states[phone_number]["columna"]
            campo = user_states[phone_number]["campo"]

            try:
                hoja.update_cell(fila, columna + 1, nuevo_valor)
                msg.body(f"✅ El campo '{campo}' fue actualizado correctamente.\n"
                        "¿Deseas actualizar otro campo de este producto? (sí / no)")
                user_states[phone_number]["step"] = "confirmar_otro_campo"
            except Exception as e:
                msg.body("❌ Error al actualizar el valor. Intenta nuevamente.")
                logging.error(f"Error al actualizar celda: {e}")
            return str(resp)

        elif phone_number in user_states and user_states[phone_number].get("step") == "confirmar_otro_campo":
            if incoming_msg.lower() == "si":
                user_states[phone_number]["step"] = "esperando_campo_a_modificar"
                msg.body("🔁 ¿Qué otro campo deseas modificar? (fecha / costo / precio / stock mínimo)")
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Actualización finalizada. Envía 'menu' para ver opciones.")
            return str(resp)
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
            return str(resp)
    # Opción 2: Filtrar por código
    elif incoming_msg == "2":
        user_states[phone_number] = {"step": "esperando_codigo"}
        msg.body("🔍 Escribe el código del producto que deseas consultar:")
        return str(resp)

    # Opción 3: Agregar producto
    elif incoming_msg == "3":
        user_states[phone_number] = {"step": "esperando_datos"}
        msg.body("Por favor envía los datos del producto en este formato:\n"
                 "Nombre, Marca, Fecha de vencimiento (AAAA-MM-DD), Costo, Cantidad, Precio, Stock Mínimo, Fecha de compra (AAAA-MM-DD)\n")
        return str(resp)
    # Opción 4: Actualizar producto
    elif incoming_msg == "4":
        user_states[phone_number] = {"step": "esperando_codigo_actualizar"}
        msg.body("🔄 Ingresa el código del producto que deseas actualizar:")
        return str(resp)
    
    return str(resp)
    
    # Opción 5: Eliminar producto
    """elif incoming_msg == "5":
        user_states[phone_number] = {"step": "esperando_codigo_eliminar"}
        msg.body("🗑️ Ingresa el código del producto que deseas eliminar:")
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "esperando_codigo_eliminar":
        hoja = get_inventory_sheet_for_number(phone_number)
        productos = hoja.get_all_values()
        codigo = incoming_msg.strip().upper()

        encontrado = None
        for i, row in enumerate(productos[1:], start=2):  # Saltamos encabezado
            if row[0] == codigo:
                encontrado = (i, row)
                break

        if not encontrado:
            msg.body("❌ Producto no encontrado. ¿Deseas ingresar otro código? (sí / no)")
            user_states[phone_number] = {"step": "confirmar_codigo_nuevamente_5"}
            return str(resp)

        fila, producto = encontrado
        user_states[phone_number] = {
            "step": "confirmar_eliminacion",
            "fila": fila,
            "producto": producto,
            "codigo": codigo
        }
        msg.body(
            f"⚠️ Producto encontrado: {producto[1]} - {producto[2]}\n"
            f"¿Estás seguro de que deseas eliminarlo? (sí / no)"
        )
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "confirmar_codigo_nuevamente_5":
        if incoming_msg.lower() == "sí":
            user_states[phone_number] = {"step": "esperando_codigo_eliminar"}
            msg.body("🗑️ Ingresa el código del producto que deseas eliminar:")
        else:
            user_states.pop(phone_number, None)
            msg.body("✅ Cancelado. Envía 'menu' para ver las opciones.")
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "confirmar_eliminacion":
        if incoming_msg.lower() == "sí":
            hoja = get_inventory_sheet_for_number(phone_number)
            fila = user_states[phone_number]["fila"]
            try:
                hoja.delete_rows(fila)
                msg.body("✅ Producto eliminado correctamente.")
            except Exception as e:
                msg.body("❌ Ocurrió un error al eliminar el producto.")
                logging.error(f"Error al eliminar fila: {e}")
            user_states.pop(phone_number, None)
        else:
            msg.body("✅ Eliminación cancelada. Envía 'menu' para ver opciones.")
            user_states.pop(phone_number, None)
        return str(resp)
   
    # Opción 6: Registrar entrada
    elif incoming_msg == "6":
        user_states[phone_number] = {"step": "entrada_codigo"}
        msg.body("📥 Ingresa el código del producto al que deseas registrar entrada:")
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "entrada_codigo":
        hoja = get_inventory_sheet_for_number(phone_number)
        productos = hoja.get_all_values()
        codigo = incoming_msg.strip().upper()

        for i, row in enumerate(productos[1:], start=2):  # Saltamos encabezado
            if row[0] == codigo:
                user_states[phone_number] = {
                    "step": "entrada_fecha",
                    "fila": i,
                    "producto": row,
                    "codigo": codigo
                }
                msg.body("📅 Ingresa la nueva fecha de última compra (AAAA-MM-DD):")
                return str(resp)

        msg.body("❌ Código no encontrado. ¿Deseas ingresar otro código? (sí / no)")
        user_states[phone_number] = {"step": "entrada_codigo_reintentar"}
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "entrada_codigo_reintentar":
        if incoming_msg.lower() == "sí":
            user_states[phone_number] = {"step": "entrada_codigo"}
            msg.body("📥 Ingresa el código del producto:")
        else:
            user_states.pop(phone_number, None)
            msg.body("✅ Cancelado. Envía 'menu' para ver las opciones.")
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "entrada_fecha":
        user_states[phone_number]["nueva_fecha"] = incoming_msg.strip()
        user_states[phone_number]["step"] = "entrada_cantidad"
        msg.body("🔢 Ingresa la cantidad que deseas registrar:")
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "entrada_cantidad":
        cantidad_extra = incoming_msg.strip()
        if not cantidad_extra.isdigit():
            msg.body("❌ Por favor ingresa un número válido.")
            return str(resp)

        estado = user_states[phone_number]
        hoja = get_inventory_sheet_for_number(phone_number)
        fila = estado["fila"]
        producto = estado["producto"]
        fecha = estado["nueva_fecha"]
        cantidad_actual = int(producto[5])
        nueva_cantidad = cantidad_actual + int(cantidad_extra)

        hoja.update_cell(fila, 6, str(nueva_cantidad))  # Columna de cantidad (6)
        hoja.update_cell(fila, 9, fecha)  # Columna de última compra (9)

        msg.body(f"✅ Se registró la entrada. Nuevo stock: {nueva_cantidad}")
        user_states.pop(phone_number, None)
        return str(resp)

    # Opción 7: Registrar salida
    elif incoming_msg == "7":
        user_states[phone_number] = {"step": "salida_codigo"}
        msg.body("📤 Ingresa el código del producto del que deseas registrar una salida:")
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "salida_codigo":
        hoja = get_inventory_sheet_for_number(phone_number)
        productos = hoja.get_all_values()
        codigo = incoming_msg.strip().upper()

        for i, row in enumerate(productos[1:], start=2):  # Saltamos encabezado
            if row[0] == codigo:
                user_states[phone_number] = {
                    "step": "salida_cantidad",
                    "fila": i,
                    "producto": row,
                    "codigo": codigo
                }
                msg.body("🔢 Ingresa la cantidad que deseas retirar:")
                return str(resp)

        msg.body("❌ Código no encontrado. ¿Deseas ingresar otro código? (sí / no)")
        user_states[phone_number] = {"step": "salida_codigo_reintentar"}
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "salida_codigo_reintentar":
        if incoming_msg.lower() == "sí":
            user_states[phone_number] = {"step": "salida_codigo"}
            msg.body("📤 Ingresa el código del producto:")
        else:
            user_states.pop(phone_number, None)
            msg.body("✅ Cancelado. Envía 'menu' para ver las opciones.")
        return str(resp)

    elif phone_number in user_states and user_states[phone_number].get("step") == "salida_cantidad":
        cantidad_salida = incoming_msg.strip()
        if not cantidad_salida.isdigit():
            msg.body("❌ Por favor ingresa un número válido.")
            return str(resp)

        estado = user_states[phone_number]
        hoja = get_inventory_sheet_for_number(phone_number)
        fila = estado["fila"]
        producto = estado["producto"]
        cantidad_actual = int(producto[5])
        cantidad_retirar = int(cantidad_salida)

        if cantidad_retirar > cantidad_actual:
            msg.body(f"❌ No puedes retirar más de lo disponible. Stock actual: {cantidad_actual}")
            return str(resp)

        nuevo_stock = cantidad_actual - cantidad_retirar
        hoja.update_cell(fila, 6, str(nuevo_stock))  # Columna cantidad (6)

        msg.body(f"✅ Salida registrada. Nuevo stock de '{producto[1]}': {nuevo_stock}")
        user_states.pop(phone_number, None)
        return str(resp)
    """

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)