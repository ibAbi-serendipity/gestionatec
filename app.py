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
    
    msg.body("👋 Hola, bienvenido al bot de inventario.")
    print(f"📤 Respuesta enviada: {str(resp)}")
    
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
