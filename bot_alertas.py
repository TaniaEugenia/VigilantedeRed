import time
import requests
import threading
import firebase_admin
import os
import json
from firebase_admin import credentials, db

# --- CONFIGURACIÓN ---
TOKEN_TELEGRAM = '8709241753:AAGBhWXccYJBoP4BQrCbFgeO-YmuyEDGv30'

# Inicializar Firebase desde variable de entorno
cred_json = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(cred_json)
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'
})

def enviar_mensaje(chat_id, texto, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload)

# --- LISTENER DE ALERTAS (VIGILANTE ACTIVO) ---
def escuchar_firebase():
    print("📡 Escuchando intrusos en Firebase...")
    ref = db.reference('usuarios')
    
    def callback(event):
        # Si hay datos nuevos en la base de datos
        if event.data and isinstance(event.data, dict):
            for codigo, datos in event.data.items():
                intrusos = datos.get('dispositivos_detectados', {})
                chat_id = datos.get('chat_id')
                
                if chat_id and isinstance(intrusos, dict):
                    for mac, disp in intrusos.items():
                        # --- FORMATEO VISUAL ADAPTADO A LA IMAGEN (image_8a89a0.png) ---
                        # Usamos emojis de Telegram como iconos y Markdown para formato
                        ip_str = disp.get('ip', 'N/A')
                        fabricante_str = disp.get('fabricante', 'Desconocido')
                        tipo_str = disp.get('tipo', 'Dispositivo desconocido')

                        mensaje = (
                            f"🚨 *¡INTRUSO DETECTADO!* 🚨\n\n"
                            f"📍 *IP:* `{ip_str}`\n"
                            f"🏷 *MAC:* `{mac}`\n"
                            f"⚙️ *Fabricante:* {fabricante_str}\n"
                            f"🔍 *Tipo estimado:* {tipo_str}\n"
                            f"🖥 *Nombre de red:* (Sin asignar)\n\n"
                            f"¿Querés darle permiso de acceso a tu red?"
                        )
                        
                        # Botones interactivos (Inline Keyboard)
                        markup = {
                            "inline_keyboard": [[
                                {
                                    "text": "✅ Permitir y Bautizar",
                                    "callback_data": f"permitir_{mac}_{ip_str}"
                                },
                                {
                                    "text": "❌ Ignorar",
                                    "callback_data": f"ignorar_{mac}"
                                }
                            ]]
                        }
                        
                        # IMPORTANTE: Asegúrate de que tu función enviar_mensaje acepte el parámetro parse_mode
                        enviar_mensaje(chat_id, mensaje, reply_markup=markup, parse_mode='Markdown')

    ref.listen(callback)

# --- PROCESAMIENTO COMANDOS BOT ---
def procesar_actualizaciones():
    offset = None
    print("📡 Bot administrativo activo.")
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/getUpdates?timeout=10&offset={offset}"
            response = requests.get(url).json()
            
            if "result" in response:
                for update in response["result"]:
                    offset = update["update_id"] + 1
                    
                    # Manejo de botones (callback)
                    if "callback_query" in update:
                        query = update["callback_query"]
                        chat_id = query["message"]["chat"]["id"]
                        data = query["data"]
                        requests.post(f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery", json={"callback_query_id": query["id"]})
                        
                        if data.startswith("permitir_"):
                            enviar_mensaje(chat_id, "✍️ Escribime el nombre para este dispositivo:")
                    
                    # Manejo de comandos/mensajes
                    elif "message" in update and "text" in update["message"]:
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        texto = msg["text"]
                        
                        if texto.startswith("/start"):
                            partes = texto.split(" ")
                            if len(partes) > 1:
                                codigo = partes[1].upper()
                                db.reference(f'usuarios/{codigo}').update({'chat_id': chat_id})
                                enviar_mensaje(chat_id, f"✅ Vinculado con éxito a la red {codigo}.")
                        
                        elif texto.startswith("/micode"):
                            enviar_mensaje(chat_id, "🔑 Función activa. Tu código está registrado en el sistema de monitoreo.")

        except Exception as e:
            print(f"Error en bot: {e}")
        time.sleep(1)

if __name__ == "__main__":
    # Inicia el vigilante y el bot simultáneamente
    threading.Thread(target=escuchar_firebase, daemon=True).start()
    procesar_actualizaciones()