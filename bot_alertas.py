import time
import requests
import threading
import firebase_admin
import os
import json
from firebase_admin import credentials, db

# --- AQUÍ VA TU FUNCIÓN CORREGIDA ---
def enviar_mensaje(chat_id, texto, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(reply_markup) if reply_markup else None
    }
    requests.post(url, data=payload)

# --- EL RESTO DE TU CÓDIGO (TOKEN, INICIALIZACIÓN, FUNCIONES) ---
TOKEN_TELEGRAM = '8709241753:AAGBhWXccYJBoP4BQrCbFgeO-YmuyEDGv30'
# ... (y el resto de tu código que me pasaste antes)

# Inicializar Firebase
cred_json = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(cred_json)
firebase_admin.initialize_app(cred, {'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'})

# Diccionarios de estado
esperando_nombre = {} # {chat_id: mac}
usuario_vinculado = {} # {chat_id: codigo}

def escuchar_firebase():
    def callback(event):
        if not event.data or not isinstance(event.data, dict): return
        for codigo, datos_usuario in event.data.items():
            chat_id = datos_usuario.get('chat_id')
            if not chat_id: continue
            
            dispositivos = datos_usuario.get('dispositivos_detectados', {})
            for mac, disp in dispositivos.items():
                if disp.get('es_intruso') and not disp.get('nombre_bautizado'):
                    # Formato mejorado igual a tu segunda foto
                    mensaje = (
                        f"🚨 *¡INTRUSO DETECTADO!* 🚨\n\n"
                        f"📍 *IP:* `{disp.get('ip')}`\n"
                        f"🏷 *MAC:* `{mac.replace('_', ':')}`\n"
                        f"⚙️ *Fabricante:* {disp.get('fabricante', 'Desconocido')}\n"
                        f"🔍 *Tipo estimado:* {disp.get('tipo', 'Desconocido')}\n\n"
                        f"¿Querés darle permiso de acceso a tu red?"
                    )
                    
                    # Dos botones: Permitir y Ignorar
                    markup = {"inline_keyboard": [[
                        {"text": "✅ Permitir y Bautizar", "callback_data": f"permitir_{codigo}_{mac}"},
                        {"text": "❌ Ignorar", "callback_data": f"ignorar_{mac}"}
                    ]]}
                    
                    enviar_mensaje(chat_id, mensaje, reply_markup=markup)
    
    # Escucha en la ruta 'usuarios' para detectar cambios en cualquier red
    db.reference('usuarios').listen(callback)
def procesar_actualizaciones():
    offset = None
    while True:
        url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/getUpdates?timeout=10&offset={offset}"
        response = requests.get(url).json()
        if "result" in response:
            for update in response["result"]:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    query = update["callback_query"]
                    chat_id = query["message"]["chat"]["id"]
                    data = query["data"]
                    if data.startswith("permitir_"):
                        _, codigo, mac = data.split("_", 2)
                        esperando_nombre[chat_id] = (codigo, mac)
                        enviar_mensaje(chat_id, "✍️ Escribime el nombre para este dispositivo:")
                elif "message" in update and "text" in update["message"]:
                    msg = update["message"]
                    chat_id, texto = msg["chat"]["id"], msg["text"]
                    if texto.startswith("/start"):
                        codigo = texto.split(" ")[1].upper() if len(texto.split()) > 1 else None
                        if codigo:
                            db.reference(f'usuarios/{codigo}').update({'chat_id': chat_id})
                            usuario_vinculado[chat_id] = codigo
                            enviar_mensaje(chat_id, f"✅ Vinculado a {codigo}.")
                    elif texto.startswith("/milista"):
                        codigo = usuario_vinculado.get(chat_id)
                        if codigo:
                            dispositivos = db.reference(f'usuarios/{codigo}/dispositivos_detectados').get() or {}
                            lista = "\n".join([f"✅ {d.get('nombre_bautizado')}" for d in dispositivos.values() if not d.get('es_intruso')])
                            enviar_mensaje(chat_id, f"📋 *Dispositivos habilitados:*\n{lista or 'Ninguno'}")
                    elif chat_id in esperando_nombre:
                        codigo, mac = esperando_nombre.pop(chat_id)
                        db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
                            'nombre_bautizado': texto, 'es_intruso': False
                        })
                        enviar_mensaje(chat_id, "✅ Dispositivo bautizado y autorizado.")
        time.sleep(1)

if __name__ == "__main__":
    threading.Thread(target=escuchar_firebase, daemon=True).start()
    procesar_actualizaciones()