from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def whatsapp_bot():
    incoming_msg = request.values.get("Body", "").strip()
    phone_number = request.values.get("From", "").replace("whatsapp:", "").replace("+", "")
    
    print(f"📱 Mensaje recibido de {phone_number}: {incoming_msg}")
    
    resp = MessagingResponse()
    msg = resp.message()
    
    if incoming_msg.lower() in ["hola", "menu", "inicio"]:
        user_states.pop(phone_number, None) 
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
