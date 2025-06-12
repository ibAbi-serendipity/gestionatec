import os
import logging
from datetime import datetime, date
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from google_sheets import obtener_productos, get_inventory_sheet_for_number, registrar_movimiento, get_client_name, get_historial_sheet_for_number  # Importamos la función para obtener los productos

app = Flask(__name__)
user_states = {}  # Aquí definimos el diccionario para guardar el estado de los usuarios

def normalizar_fecha(fecha_str):
    try:
        return datetime.strptime(fecha_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None    
        
@app.route("/webhook", methods=["POST"])
def whatsapp_bot():
    incoming_msg = request.values.get("Body", "").strip()
    phone_number = request.values.get("From", "").replace("whatsapp:", "").replace("+", "")
    
    print(f"📱 Mensaje recibido de {phone_number}: {incoming_msg}")
    resp = MessagingResponse()
    msg = resp.message()
    
    if incoming_msg.lower() in ["hola", "menu", "inicio"]:
        nombre_cliente = get_client_name(phone_number)
        user_states.pop(phone_number, None)  # Limpiamos el estado del usuario
        menu = (
            f"👋 ¡Hola {nombre_cliente}, soy Kardex!\n"
            "Elige una opción:\n"
            "1️⃣ Listar productos\n"
            "2️⃣ Gestionar productos\n"
            "3️⃣ Registrar entrada\n"
            "4️⃣ Registrar salida\n"
            "5️⃣ Revisar stock mínimo / vencimiento\n"
            "6️⃣ Reporte"
        )
        msg.body(menu)
        return str(resp)
    elif phone_number in user_states:
        estado = user_states[phone_number]

        if estado.get("step") == "submenu_gestion":
            opcion = incoming_msg.strip().lower()
            if opcion == "a":
                user_states[phone_number] = {"step": "esperando_codigo"}
                msg.body("🔍 Escribe el código del producto que deseas buscar:")
                return str(resp)
            elif opcion == "b":
                user_states[phone_number] = {"step": "preguntar_perecible"}
                msg.body("🧾 ¿El producto es perecible? (sí / no)")
                return str(resp)
            elif opcion == "c":
                user_states[phone_number] = {"step": "esperando_codigo_actualizar"}
                msg.body("✏️ Ingresa el *código* del producto que deseas actualizar:")
                return str(resp)
            elif opcion == "d":
                user_states[phone_number] = {"step": "esperando_codigo_eliminar"}
                msg.body("🗑️ Ingresa el *código* del producto que deseas eliminar:")
                return str(resp)
            else:
                msg.body("❌ Opción inválida. Escribe A, B, C o D o escribe 'menu' para regresar.")
                return str(resp)

        # OPCIÓN B: AGREGAR PRODUCTO
        elif estado.get("step") == "preguntar_perecible":
            respuesta = incoming_msg.lower()
            if respuesta in ["sí", "si"]:
                estado["perecible"] = True
                estado["step"] = "elegir_categoria"
                msg.body(
                    "📦 Elige la categoría del producto:\n"
                    "A. Comestibles\nB. Medicamentos\nC. Higiene personal\nD. Limpieza"
                )
            elif respuesta == "no":
                estado["perecible"] = False
                estado["step"] = "elegir_categoria"
                msg.body(
                    "🛠️ Elige la categoría del producto:\n"
                    "E. Herramientas\nF. Papelería\nG. Electrónicos\nH. Ropa"
                )
            else:
                msg.body("❌ Respuesta no válida. Escribe 'sí' o 'no'.")
            return str(resp)

        elif estado.get("step") == "elegir_categoria":
            categorias = {
                "a": "1", "b": "2", "c": "3", "d": "4",  # Perecibles
                "e": "5", "f": "6", "g": "7", "h": "8"   # No perecibles
            }
            opcion = incoming_msg.lower()
            if opcion not in categorias:
                msg.body("❌ Opción inválida. Elige una letra válida (A-H).")
                return str(resp)

            estado["categoria"] = categorias[opcion]
            estado["step"] = "esperando_datos"
            msg.body(
                "📝 Ingresa los datos del producto en este formato:\n"
                "```Artículo, Marca, Precio, Cantidad, Stock Mínimo, Ubicación referencial```\n"
                "📌 Si deseas cancelar, escribe *menu*."
            )
            return str(resp)

        elif estado.get("step") == "esperando_datos":
            partes = [x.strip() for x in incoming_msg.split(",")]

            if len(partes) != 6:
                msg.body(
                    "❌ Formato incorrecto. Asegúrate de escribir:\n"
                    "```Artículo, Marca, Precio, Cantidad, Stock Mínimo, Ubicación referencial```\n"
                    "📌 Si deseas salir, escribe *menu*."
                )
                return str(resp)

            estado["nombre"] = partes[0]
            estado["marca"] = partes[1]
            estado["precio"] = partes[2]
            estado["cantidad"] = partes[3]
            estado["stock_minimo"] = partes[4]
            estado["lugar"] = partes[5]

            estado["step"] = "esperando_empaque"
            msg.body("📦 ¿Cuál es el tipo de empaque? (unidad / caja / bolsa / paquete / saco / botella / lata / tetrapack / sobre / tableta)")
            return str(resp)

        elif estado.get("step") == "esperando_empaque":
            empaque = incoming_msg.strip().lower()
            if not empaque:
                msg.body("❌ Tipo de empaque no válido. Intenta nuevamente.")
                return str(resp)

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

            # Buscar correlativo existente
            correlativos = []
            for fila in data:
                if fila and fila[0].startswith(prefijo_codigo) and len(fila[0]) >= 4:
                    sufijo = fila[0][3:]
                    if sufijo.isdigit():
                        correlativos.append(int(sufijo))

            nuevo_num = str(max(correlativos, default=0) + 1).zfill(2)
            codigo = f"{prefijo_codigo}{nuevo_num}"

            # Crear la nueva fila del producto
            nuevo_producto = [
                codigo,
                estado["nombre"],
                estado["marca"],
                estado["precio"],
                estado["cantidad"],
                estado["stock_minimo"],
                estado["lugar"]
            ]

            # Agregar a la hoja
            hoja.append_row(nuevo_producto)

            msg.body(
                f"✅ Producto '{estado['nombre']}' agregado con código *{codigo}*.\n"
                "¿Deseas registrar otro producto? (sí / no)"
            )
            estado.clear()
            estado["step"] = "confirmar_continuar"
            return str(resp)

        elif estado.get("step") == "confirmar_continuar":
            if incoming_msg.lower() in ["sí", "si"]:
                estado.clear()
                estado["step"] = "preguntar_perecible"
                msg.body("🧾 ¿El siguiente producto es perecible? (sí / no)")
            elif incoming_msg.lower() == "no":
                user_states.pop(phone_number)
                msg.body("📋 Has salido del registro de productos. Escribe 'menu' para ver las opciones.")
            else:
                msg.body("❓ Respuesta no válida. Escribe 'sí' para registrar otro producto o 'no' para salir.")
            return str(resp)

        # OPCION A: Filtrar por código
        elif estado.get("step") == "esperando_codigo":
            filtro_codigo = incoming_msg.upper().strip()
            hoja_cliente = get_inventory_sheet_for_number(phone_number)

            if not hoja_cliente:
                msg.body("❌ No se encontró tu hoja de productos.")
                user_states.pop(phone_number, None)
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
                        f"📦 Stock total: {p['cantidad']}\n"
                        f"💵 Precio de venta: S/ {p['precio']}\n"
                        f"📉 Stock mínimo: {p['stock_minimo']}\n"
                        f"🛒 Ubicación: {p['lugar']}\n\n"
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
                user_states.pop(phone_number, None)
                msg.body("✅ Consulta finalizada. Escribe 'menu' para ver más opciones.")
        
        # OPCION C: Actualizar producto
        elif estado.get("step") == "esperando_codigo_actualizar":
            codigo = incoming_msg.strip().upper()
            hoja = get_inventory_sheet_for_number(phone_number)
            hoja_lotes = get_lotes_sheet_for_number(phone_number)

            productos = hoja.get_all_values()
            lotes = hoja_lotes.get_all_values()[1:]  # Ignora encabezado

            encontrado = None
            for i, row in enumerate(productos[1:], start=2):
                if row[0] == codigo:
                    encontrado = (i, row)
                    break

            if encontrado:
                fila, producto = encontrado
                lotes_producto = [l for l in lotes if l[0] == codigo]

                estado.update({
                    "step": "esperando_campo_a_modificar",
                    "fila": fila,
                    "producto": producto,
                    "codigo": codigo,
                    "lotes": lotes_producto
                })

                detalles_lotes = ""
                if lotes_producto:
                    detalles_lotes = "\n\n📦 *Lotes disponibles:*\n"
                    for idx, lote in enumerate(lotes_producto, start=1):
                        detalles_lotes += (
                            f"{idx}. Lote {lote[2]} - Vence: {lote[4]} - Costo: S/ {lote[5]} - Disponible: {lote[7]}\n"
                        )

                msg.body(
                    f"🔍 Producto encontrado: {producto[1]} - {producto[2]}\n"
                    f"💾 Código: {codigo}\n"
                    f"¿Qué campo deseas modificar?\n"
                    f"- Fecha de vencimiento\n- Costo\n- Precio\n- Stock mínimo\n- Ubicación referencial"
                    f"{detalles_lotes}"
                )
            else:
                msg.body("❌ Producto no encontrado. ¿Deseas ingresar otro código? (sí / no)")
                estado["step"] = "confirmar_codigo_nuevamente_4"
            return str(resp)

        elif estado.get("step") == "esperando_campo_a_modificar":
            campo = incoming_msg.strip().lower()
            campos_validos = ["fecha de vencimiento", "costo", "precio", "stock mínimo", "ubicación referencial"]
            if campo not in campos_validos:
                msg.body("❌ Campo no válido. Elige uno de: Fecha de vencimiento / Costo / Precio / Stock mínimo / Ubicación referencial.")
                return str(resp)

            estado["campo"] = campo

            if campo in ["fecha de vencimiento", "costo"]:
                if not estado.get("lotes"):
                    msg.body("❌ Este producto no tiene lotes registrados. No se puede modificar ese campo.")
                    user_states.pop(phone_number, None)
                    return str(resp)
                estado["step"] = "seleccionar_lote_para_modificar"
                texto_lotes = "\n\nElige el número del lote que deseas modificar:\n"
                for idx, lote in enumerate(estado["lotes"], start=1):
                    texto_lotes += f"{idx}. Lote {lote[2]} - Vence: {lote[4]} - Costo: S/ {lote[5]} - Disponible: {lote[7]}\n"
                msg.body(texto_lotes)
            else:
                estado["step"] = "esperando_nuevo_valor"
                msg.body(f"✏️ Ingresa el nuevo valor para '{campo}':")
            return str(resp)

        elif estado.get("step") == "seleccionar_lote_para_modificar":
            try:
                index = int(incoming_msg.strip()) - 1
                lote = estado["lotes"][index]
                estado["lote_seleccionado"] = lote
                estado["index_lote"] = index + 2  # +2 por encabezado en hoja
                estado["step"] = "esperando_nuevo_valor"
                msg.body(f"✏️ Ingresa el nuevo valor para '{estado['campo']}' del lote {lote[2]}:")
            except:
                msg.body("❌ Opción inválida. Ingresa el número del lote a modificar.")
            return str(resp)

        elif estado.get("step") == "esperando_nuevo_valor":
            nuevo_valor = incoming_msg.strip()
            campo = estado["campo"]

            try:
                if campo in ["fecha de vencimiento", "costo"]:
                    hoja_lotes = get_lotes_sheet_for_number(phone_number)
                    col = 5 if campo == "fecha de vencimiento" else 6
                    hoja_lotes.update_cell(estado["index_lote"], col, nuevo_valor)
                    msg.body(f"✅ {campo.title()} del lote actualizado correctamente.")

                else:
                    hoja = get_inventory_sheet_for_number(phone_number)
                    campos_columna = {
                        "precio": 4,
                        "stock mínimo": 5,
                        "ubicación referencial": 6
                    }
                    hoja.update_cell(estado["fila"], campos_columna[campo] + 1, nuevo_valor)
                    msg.body(f"✅ Campo '{campo}' actualizado correctamente.")

                estado["step"] = "confirmar_otro_campo"
                msg.body("¿Deseas actualizar otro campo de este producto? (sí / no)")
            except Exception as e:
                logging.error(f"❌ Error al actualizar: {e}")
                msg.body("❌ Ocurrió un error al actualizar. Intenta nuevamente.")
            return str(resp)

        elif estado.get("step") == "confirmar_otro_campo":
            if incoming_msg.lower() in ["sí", "si"]:
                estado["step"] = "esperando_campo_a_modificar"
                msg.body("🔁 ¿Qué otro campo deseas modificar? (Fecha de vencimiento / Costo / Precio / Stock mínimo / Ubicación referencial)")
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Actualización finalizada. Escribe 'menu' para más opciones.")
            return str(resp)

        # OPCION D: Eliminar producto
        elif phone_number in user_states and user_states[phone_number].get("step") == "esperando_codigo_eliminar":
            hoja = get_inventory_sheet_for_number(phone_number)
            productos = hoja.get_all_values()
            codigo = incoming_msg.strip().upper()

            encontrado = None
            for i, row in enumerate(productos[1:], start=2):
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
                f"⚠️ Producto encontrado: *{producto[1]}* - {producto[2]}\n"
                "¿Estás seguro de que deseas eliminarlo completamente? Esto también eliminará los lotes relacionados. (sí / no)"
            )
            return str(resp)

        elif estado.get("step") == "confirmar_codigo_nuevamente_5":
            if incoming_msg.lower() in ["si", "sí"]:
                user_states[phone_number] = {"step": "esperando_codigo_eliminar"}
                msg.body("🗑️ Ingresa el código del producto que deseas eliminar:")
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Cancelado. Envía 'menu' para ver las opciones.")
            return str(resp)

        elif estado.get("step") == "confirmar_eliminacion":
            if incoming_msg.lower() in ["si", "sí"]:
                codigo = estado["codigo"]
                hoja_lotes = get_lotes_sheet_for_number(phone_number)
                filas_a_borrar = []

                if hoja_lotes:
                    lotes = hoja_lotes.get_all_values()
                    for i, fila in enumerate(lotes[1:], start=2):
                        if fila[0] == codigo:
                            disponible = int(fila[7]) if fila[7].isdigit() else 0
                            if disponible > 0:
                                estado["step"] = "doble_confirmacion_lotes"
                                estado["filas_lotes"] = filas_a_borrar
                                msg.body("⚠️ Este producto tiene lotes con *stock disponible*. ¿Seguro que deseas eliminarlos junto con el producto? (sí / no)")
                                return str(resp)
                            filas_a_borrar.append(i)

                estado["step"] = "eliminar_todo"
                return whatsapp_bot()  # fuerza el paso al siguiente estado
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Eliminación cancelada. Envía 'menu' para ver opciones.")
            return str(resp)

        elif estado.get("step") == "doble_confirmacion_lotes":
            if incoming_msg.lower() in ["sí", "si"]:
                estado["step"] = "eliminar_todo"
                return whatsapp_bot()  # continúa con eliminación
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Eliminación cancelada. Escribe 'menu' para volver.")
            return str(resp)

        elif estado.get("step") == "eliminar_todo":
            try:
                hoja = get_inventory_sheet_for_number(phone_number)
                hoja_lotes = get_lotes_sheet_for_number(phone_number)
                fila = estado["fila"]
                codigo = estado["codigo"]

                hoja.delete_rows(fila)

                eliminados = 0
                if hoja_lotes:
                    lotes = hoja_lotes.get_all_values()
                    filas_a_borrar = [i for i, fila in enumerate(lotes[1:], start=2) if fila[0] == codigo]
                    for i in reversed(filas_a_borrar):
                        hoja_lotes.delete_rows(i)
                        eliminados += 1

                msg.body(f"✅ Producto eliminado. Se eliminaron {eliminados} lote(s) asociados.")
            except Exception as e:
                logging.error(f"❌ Error al eliminar: {e}")
                msg.body("❌ Ocurrió un error al eliminar el producto o sus lotes.")
            user_states.pop(phone_number, None)
            return str(resp)

        # Paso 6: Registrar entrada
        elif estado.get("step") == "entrada_codigo":
            hoja = get_inventory_sheet_for_number(phone_number)
            if not hoja:
                msg.body("⚠️ No se pudo acceder a tu hoja de productos. Es posible que se haya superado el límite de uso. Intenta nuevamente más tarde.")
                return str(resp)
            productos = hoja.get_all_values()
            codigo = incoming_msg.strip().upper()

            for i, row in enumerate(productos[1:], start=2):
                if row[0] == codigo:
                    estado.update({
                        "step": "entrada_fecha_compra",
                        "fila": i,
                        "producto": row,
                        "codigo": codigo
                    })
                    msg.body(
                        f"🔍 Producto encontrado: {row[1]} - {row[2]}\n"
                        f"📦 Stock actual: {row[5]}\n"
                        "📅 Ingresa la *fecha de compra* (AAAA-MM-DD):\nEscribe *menu* para cancelar."
                    )
                    return str(resp)

            msg.body("❌ Código no encontrado. ¿Deseas ingresar otro código? (sí / no)")
            user_states[phone_number] = {"step": "entrada_codigo_reintentar"}
            return str(resp)

        elif estado.get("step") == "entrada_codigo_reintentar":
            if incoming_msg.lower() in ["si", "sí"]:
                user_states[phone_number] = {"step": "entrada_codigo"}
                msg.body("📥 Ingresa el código del producto:")
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Cancelado. Envía 'menu' para ver las opciones.")
            return str(resp)

        elif estado.get("step") == "entrada_fecha_compra":
            if incoming_msg.lower() == "menu":
                user_states.pop(phone_number, None)
                msg.body("✅ Registro cancelado. Escribe 'menu' para ver las opciones.")
                return str(resp)

            fecha_compra = incoming_msg.strip()
            fecha_compra_obj = normalizar_fecha(fecha_compra)

            if not fecha_compra_obj:
                msg.body("❌ Formato de fecha inválido. ¿Deseas intentarlo de nuevo? (sí / no)")
                estado["step"] = "confirmar_fecha_compra_invalida"
                return str(resp)

            hoy = date.today()
            if fecha_compra_obj > hoy:
                msg.body("❌ La fecha de compra no puede ser futura. Ingresa una fecha válida o escribe *menu* para salir:")
                return str(resp)

            estado["fecha_compra"] = fecha_compra

            # Detectar si es perecible a partir de la hoja (si el producto ya no tiene fecha anterior)
            perecible = True
            hoja_lotes = get_lotes_sheet_for_number(phone_number)
            lotes_existentes = hoja_lotes.get_all_values()
            for row in lotes_existentes:
                if row[0] == estado["codigo"] and not row[4].strip():
                    perecible = False
                    break

            if perecible:
                estado["perecible"] = True
                estado["step"] = "entrada_fecha_vencimiento"
                msg.body("📅 Ingresa la *fecha de vencimiento* (AAAA-MM-DD):")
            else:
                estado["fecha_vencimiento"] = ""
                estado["step"] = "entrada_costo"
                msg.body("💰 Ingresa el *costo unitario* del lote:")
            return str(resp)

        elif estado.get("step") == "confirmar_fecha_compra_invalida":
            if incoming_msg.lower() in ["sí", "si"]:
                estado["step"] = "entrada_fecha_compra"
                msg.body("📅 Ingresa la *fecha de compra* (AAAA-MM-DD):")
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Registro cancelado. Escribe 'menu' para ver opciones.")
            return str(resp)

        elif estado.get("step") == "entrada_fecha_vencimiento":
            fecha_vencimiento = incoming_msg.strip()
            fecha_vencimiento_obj = normalizar_fecha(fecha_vencimiento)

            if not fecha_vencimiento_obj:
                msg.body("❌ Fecha de vencimiento inválida. Intenta nuevamente:")
                return str(resp)

            estado["fecha_vencimiento"] = fecha_vencimiento
            estado["step"] = "entrada_costo"
            msg.body("💰 Ingresa el *costo unitario* del lote:")
            return str(resp)

        elif estado.get("step") == "entrada_costo":
            costo = incoming_msg.strip()
            try:
                float(costo)
                estado["costo"] = costo
                estado["step"] = "entrada_cantidad"
                msg.body("🔢 Ingresa la *cantidad* de productos del nuevo lote:")
            except:
                msg.body("❌ Costo no válido. Ingresa un número válido.")
            return str(resp)

        elif estado.get("step") == "entrada_cantidad":
            cantidad = incoming_msg.strip()
            if not cantidad.isdigit():
                msg.body("❌ Ingresa una cantidad válida.")
                return str(resp)

            hoja = get_inventory_sheet_for_number(phone_number)
            fila = estado["fila"]
            producto = estado["producto"]
            codigo = estado["codigo"]
            nueva_cantidad = int(producto[5]) + int(cantidad)

            # Actualizar stock total en hoja de productos
            hoja.update_cell(fila, 6, str(nueva_cantidad))

            # Registrar lote
            hoja_lotes = get_lotes_sheet_for_number(phone_number)
            lotes = hoja_lotes.get_all_values()
            lotes_existentes = [row for row in lotes if row[0] == codigo]
            nuevo_lote_id = str(len(lotes_existentes) + 1)

            nuevo_lote = [
                codigo,
                producto[1],
                nuevo_lote_id,
                estado["fecha_compra"],
                estado.get("fecha_vencimiento", ""),
                estado["costo"],
                cantidad,
                cantidad
            ]
            hoja_lotes.append_row(nuevo_lote)

            # Registrar en historial con precio de venta desde producto[3]
            registrar_movimiento(
                phone_number,
                "Entrada",
                codigo,
                producto[1],
                cantidad,
                nueva_cantidad,
                estado["fecha_compra"],
                precio=producto[3],
                costo=estado["costo"]
            )

            msg.body(
                f"✅ Entrada registrada. Nuevo stock: {nueva_cantidad}\n"
                "📦 ¿Deseas registrar otra entrada? (sí / no)"
            )
            estado.clear()
            estado["step"] = "confirmar_otra_entrada"
            return str(resp)

        elif estado.get("step") == "confirmar_otra_entrada":
            if incoming_msg.lower() in ["sí", "si"]:
                estado.clear()
                estado["step"] = "entrada_codigo"
                msg.body("📥 Ingresa el código del producto al que deseas registrar entrada:")
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Registro finalizado. Escribe *menu* para ver las opciones.")
            return str(resp)

        # Paso 7: Registrar salida
        elif estado.get("step") == "salida_codigo":
            hoja = get_inventory_sheet_for_number(phone_number)
            productos = hoja.get_all_values()
            codigo = incoming_msg.strip().upper()

            for i, row in enumerate(productos[1:], start=2):
                if row[0] == codigo:
                    estado.update({
                        "step": "salida_fecha",
                        "fila": i,
                        "producto": row,
                        "codigo": codigo
                    })
                    hoja_lotes = get_lotes_sheet_for_number(phone_number)
                    lotes = [l for l in hoja_lotes.get_all_values()[1:] if l[0] == codigo and int(l[7]) > 0]
                    lotes_ordenados = sorted(lotes, key=lambda l: normalizar_fecha(l[3]))

                    if not lotes_ordenados:
                        msg.body("⚠️ No hay lotes disponibles para este producto.")
                        user_states.pop(phone_number, None)
                        return str(resp)

                    primer_lote = lotes_ordenados[0]
                    estado["lote"] = primer_lote

                    msg.body(
                        f"🔍 Producto encontrado: {row[1]} - {row[2]}\n"
                        f"📦 Stock total: {row[5]} | 💰 Precio actual: S/ {row[3]}\n"
                        f"📦 Se usará el lote más antiguo (ID {primer_lote[2]}) con {primer_lote[7]} unidades disponibles.\n"
                        "📅 Ingresa la *fecha de salida* (AAAA-MM-DD):"
                    )
                    return str(resp)

            msg.body("❌ Código no encontrado. ¿Deseas ingresar otro código? (sí / no)")
            user_states[phone_number] = {"step": "salida_codigo_reintentar"}
            return str(resp)

        elif estado.get("step") == "salida_codigo_reintentar":
            if incoming_msg.lower() in ["sí", "si"]:
                estado["step"] = "salida_codigo"
                msg.body("📤 Ingresa el código del producto:")
            else:
                user_states.pop(phone_number, None)
                msg.body("✅ Cancelado. Envía 'menu' para ver las opciones.")
            return str(resp)

        elif estado.get("step") == "salida_fecha":
            fecha_salida = incoming_msg.strip()
            fecha_obj = normalizar_fecha(fecha_salida)
            hoy = date.today()

            if not fecha_obj:
                msg.body("❌ Formato de fecha inválido. Usa el formato AAAA-MM-DD.")
                return str(resp)
            if fecha_obj > hoy:
                msg.body("❌ La fecha de salida no puede ser futura. Ingresa una fecha válida.")
                return str(resp)

            lote = estado["lote"]
            vencimiento_lote = normalizar_fecha(lote[4])
            if vencimiento_lote and vencimiento_lote < fecha_obj:
                msg.body(f"⚠️ El lote seleccionado (ID {lote[2]}) venció el {lote[4]}. No se permite registrar salidas de productos vencidos.")
                user_states.pop(phone_number, None)
                return str(resp)

            estado["fecha_salida"] = fecha_salida
            estado["step"] = "salida_cantidad"
            msg.body("🔢 Ingresa la cantidad que deseas retirar:")
            return str(resp)

        elif estado.get("step") == "salida_cantidad":
            cantidad_salida = incoming_msg.strip()
            if not cantidad_salida.isdigit():
                msg.body("❌ Ingresa una cantidad válida.")
                return str(resp)

            cantidad_retirar = int(cantidad_salida)
            lote = estado["lote"]
            disponible_lote = int(lote[7])

            if cantidad_retirar > disponible_lote:
                msg.body(f"❌ No puedes retirar más de lo disponible en el lote. Disponible: {disponible_lote}")
                return str(resp)

            hoja_productos = get_inventory_sheet_for_number(phone_number)
            hoja_lotes = get_lotes_sheet_for_number(phone_number)

            fila_producto = estado["fila"]
            producto = estado["producto"]
            nuevo_stock = int(producto[5]) - cantidad_retirar
            hoja_productos.update_cell(fila_producto, 6, str(nuevo_stock))

            # Actualizar lote
            filas_lotes = hoja_lotes.get_all_values()
            for idx, row in enumerate(filas_lotes):
                if row[0] == estado["codigo"] and row[2] == lote[2]:
                    fila_lote = idx + 1
                    hoja_lotes.update_cell(fila_lote, 8, str(disponible_lote - cantidad_retirar))
                    break

            registrar_movimiento(
                phone_number,
                "Salida",
                estado["codigo"],
                producto[1],
                cantidad_retirar,
                nuevo_stock,
                estado["fecha_salida"],
                precio=producto[3],
                costo=lote[5]
            )

            msg.body(f"✅ Salida registrada. Nuevo stock total: {nuevo_stock}\n📋 Escribe *menu* para regresar al menú.")
            user_states.pop(phone_number, None)
            return str(resp)
        return str(resp)

    # Opción 1: Ver productos
    elif incoming_msg == "1":
        hoja_cliente = get_inventory_sheet_for_number(phone_number)
        if not hoja_cliente:
            msg.body("❌ No se encontró la hoja de productos para tu número.")
        else:
            productos = hoja_cliente.get_all_values()
            if not productos or len(productos) <= 1:
                msg.body("📭 No hay productos registrados.")
            else:
                respuesta = "📦 *Productos en inventario:*\n"
                for i, row in enumerate(productos[1:], start=1):  # Saltamos encabezado
                    codigo = row[0]
                    nombre = row[1]
                    marca = row[2]
                    precio = row[3]
                    stock = row[4]
                    respuesta += (
                        f"{i}. *{nombre}* ({marca}) - {codigo}\n"
                        f"   📦 Stock: {stock} | 💰 S/ {precio}\n"
                    )
                msg.body(respuesta)
        return str(resp)

    # Opción 2: Gestionar productos
    elif incoming_msg == "2":
        user_states[phone_number] = {"step": "submenu_gestion"}
        msg.body(
            "🛠️ *GESTIONAR PRODUCTOS:*\n"
            "A. Filtrar por código\n"
            "B. Agregar producto\n"
            "C. Actualizar producto\n"
            "D. Eliminar producto\n\n"
            "Escribe A, B, C o D para continuar. O escribe 'menu' para volver."
        )
        return str(resp)    

    # Opción 3: Registrar entrada
    elif incoming_msg == "3":
        user_states[phone_number] = {"step": "entrada_codigo"}
        msg.body("📥 Ingresa el código del producto al que deseas registrar entrada:")
        return str(resp)   
    # Opción 4: Registrar salida
    elif incoming_msg == "4":
        user_states[phone_number] = {"step": "salida_codigo"}
        msg.body("📤 Ingresa el código del producto del que deseas registrar una salida:")
        return str(resp)
    # Opción 6: Reporte
    elif incoming_msg == "6":
        try:
            hoja = get_historial_sheet_for_number(phone_number)
            if not hoja:
                msg.body("❌ No se encontró la hoja de historial de movimientos.")
                return str(resp)

            datos = hoja.get_all_values()[1:]
            if not datos:
                msg.body("⚠️ No hay registros en el historial para generar un reporte.")
                return str(resp)

            fechas = {}
            productos = {}  # nombre: [cantidad_total, código, marca]
            ganancias = 0.0

            hoja_productos = get_inventory_sheet_for_number(phone_number)
            datos_productos = hoja_productos.get_all_values()[1:]

            for row in datos:
                fecha, codigo, nombre, tipo, cantidad, stock_final, precio_venta, costo = row
                cantidad = int(cantidad)
                if tipo.lower() == "salida":
                    fechas[fecha] = fechas.get(fecha, 0) + cantidad

                    if nombre not in productos:
                        marca = ""
                        for p in datos_productos:
                            if p[0] == codigo:
                                marca = p[2]
                                break
                        productos[nombre] = [cantidad, codigo, marca]
                    else:
                        productos[nombre][0] += cantidad

                    try:
                        ganancias += (float(precio_venta) - float(costo)) * cantidad
                    except:
                        continue

            if not productos:
                msg.body("⚠️ No hay suficientes salidas para generar un reporte.")
                return str(resp)

            # Fechas con más ventas
            max_ventas = max(fechas.values())
            fechas_mas_ventas = [(f, v) for f, v in fechas.items() if v == max_ventas]

            # Top 3 más vendidos
            top_mas_vendidos = sorted(productos.items(), key=lambda x: x[1][0], reverse=True)[:3]

            # Top 3 menos vendidos
            top_menos_vendidos = sorted(productos.items(), key=lambda x: x[1][0])[:3]

            # Cálculo de pérdidas por productos vencidos
            perdidas = 0.0
            hoja_lotes = get_lotes_sheet_for_number(phone_number)
            hoy = date.today()
            lotes = hoja_lotes.get_all_values()[1:]
            for row in lotes:
                try:
                    fecha_venc = normalizar_fecha(row[4])
                    disponible = int(row[7])
                    costo_lote = float(row[5])
                    if fecha_venc and fecha_venc < hoy and disponible > 0:
                        perdidas += disponible * costo_lote
                except:
                    continue

            reporte = "📈 *REPORTE DE VENTAS*\n"
            reporte += "-------------------------------------------\n"
            reporte += "📅 *Fecha(s) con más ventas:* \n"
            for fecha, total in fechas_mas_ventas:
                reporte += f"{fecha} ({total})\n"

            reporte += "-------------------------------------------\n"
            reporte += "🥇 *Top 3 más vendidos:* \n"
            for nombre, datos in top_mas_vendidos:
                cantidad, codigo, marca = datos
                reporte += f"{nombre} ({codigo}, {marca}, {cantidad}u)\n"

            reporte += "-------------------------------------------\n"
            reporte += "🥉 *Top 3 menos vendidos:* \n"
            for nombre, datos in top_menos_vendidos:
                cantidad, codigo, marca = datos
                reporte += f"{nombre} ({codigo}, {marca}, {cantidad}u)\n"

            reporte += "-------------------------------------------\n"
            reporte += f"💰 *Ganancias acumuladas:* S/ {ganancias:.2f}\n"
            reporte += f"⚠️ *Pérdidas por productos vencidos:* S/ {perdidas:.2f}\n"
            reporte += "-------------------------------------------\n"
            reporte += "📲 Escribe *menu* para regresar al menú."

            msg.body(reporte)
            return str(resp)

        except Exception as e:
            logging.error(f"❌ Error al generar reporte: {e}")
            msg.body("❌ Ocurrió un error al generar el reporte.")
        return str(resp)

    # Opción 5: Revisar stock mínimo / vencimiento
    elif incoming_msg == "5":
        hoja_productos = get_inventory_sheet_for_number(phone_number)
        hoja_lotes = get_lotes_sheet_for_number(phone_number)

        if not hoja_productos or not hoja_lotes:
            msg.body("❌ No se encontró alguna de tus hojas de inventario.")
            return str(resp)

        productos = hoja_productos.get_all_values()[1:]
        lotes = hoja_lotes.get_all_values()[1:]

        hoy = datetime.today().date()
        stock_minimos = []
        proximos_vencer = []
        vencidos = []

        # Mapeo código → info (para encontrar stock mínimo y marca)
        productos_dict = {p[0]: {"nombre": p[1], "marca": p[2], "stock_minimo": int(p[5])} for p in productos if len(p) >= 6}

        for lote in lotes:
            try:
                codigo = lote[0]
                nombre = lote[1]
                lote_id = lote[2]
                fecha_venc = lote[4]
                disponible = int(lote[7])
                producto_info = productos_dict.get(codigo)

                if not producto_info:
                    continue

                stock_minimo = producto_info["stock_minimo"]
                marca = producto_info["marca"]

                # Stock mínimo
                if disponible <= stock_minimo:
                    stock_minimos.append(
                        f"- {nombre} ({marca}), Lote {lote_id} | Stock: {disponible} | Mínimo: {stock_minimo}"
                    )

                # Revisar vencimiento si aplica
                if fecha_venc:
                    fecha_obj = datetime.strptime(fecha_venc, "%Y-%m-%d").date()
                    dias_restantes = (fecha_obj - hoy).days

                    if fecha_obj < hoy:
                        vencidos.append(f"- {nombre} ({marca}), Lote {lote_id} | Venció: {fecha_venc}")
                    elif dias_restantes <= 21:
                        proximos_vencer.append(f"- {nombre} ({marca}), Lote {lote_id} | Vence: {fecha_venc}")

            except Exception:
                continue

        respuesta = "📋 *Productos con stock mínimo:*\n"
        respuesta += "\n".join(stock_minimos) if stock_minimos else "✅ No hay productos con stock bajo."

        respuesta += "\n\n⏰ *Productos próximos a vencer (≤21 días):*\n"
        respuesta += "\n".join(proximos_vencer) if proximos_vencer else "✅ No hay productos próximos a vencer."

        respuesta += "\n\n❌ *Productos vencidos:*\n"
        respuesta += "\n".join(vencidos) if vencidos else "✅ No hay productos vencidos."

        respuesta += "\n\n📲 Escribe *menu* para regresar al menú principal."
        msg.body(respuesta)
        return str(resp)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)