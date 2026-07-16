import time
import requests
import threading
import firebase_admin
import os
import json
from firebase_admin import credentials, db

# --- CONFIGURACIÓN ---
TOKEN_TELEGRAM = '8709241753:AAGBhWXccYJBoP4BQrCbFgeO-YmuyEDGv30'

# --- INICIALIZAR FIREBASE DESDE VARIABLE DE ENTORNO ---
# Asegúrate de tener la variable FIREBASE_CREDENTIALS en la pestaña Variables de Railway
cred_json = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(cred_json)
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'
})

def enviar_mensaje(chat_id, texto):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": texto})

# --- LISTENER DE ALERTAS ---
def escuchar_firebase():
    print("📡 Escuchando intrusos en Firebase...")
    ref = db.reference('usuarios')
    
    def callback(event):
        if event.data and isinstance(event.data, dict) and event.data.get('es_intruso'):
            codigo = event.path.split('/')[1]
            usuario_ref = db.reference(f'usuarios/{codigo}').get()
            
            chat_id = usuario_ref.get('chat_id') if usuario_ref else None
            if chat_id:
                ip = event.data.get('ip', 'Desconocida')
                mac = event.path.split('/')[-1]
                enviar_mensaje(chat_id, f"🚨 ALERTA: Intruso detectado en red {codigo}\nIP: {ip}\nMAC: {mac}")

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
                    if "message" in update and "text" in update["message"]:
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
    threading.Thread(target=escuchar_firebase, daemon=True).start()
    procesar_actualizaciones()