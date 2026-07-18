import time
import requests
import threading
import firebase_admin
import os
import json
from firebase_admin import credentials, db

TOKEN_TELEGRAM = '8709241753:AAGBhWXccYJBoP4BQrCbFgeO-YmuyEDGv30'

# Inicializar Firebase
cred_json = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(cred_json)
firebase_admin.initialize_app(cred, {'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'})

# Diccionarios de estado
esperando_nombre = {} # {chat_id: mac}
usuario_vinculado = {} # {chat_id: codigo}

def enviar_mensaje(chat_id, texto, reply_markup=None, parse_mode='Markdown'):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": parse_mode}
    if reply_markup: payload["reply_markup"] = reply_markup
    requests.post(url, json=payload)

def escuchar_firebase():
    def callback(event):
        if not event.data or not isinstance(event.data, dict): return
        for codigo, datos_usuario in event.data.items():
            chat_id = datos_usuario.get('chat_id')
            if not chat_id: continue
            
            dispositivos = datos_usuario.get('dispositivos_detectados', {})
            for mac, disp in dispositivos.items():
                if disp.get('es_intruso') and not disp.get('nombre_bautizado'):
                    mensaje = (f"🚨 *¡INTRUSO DETECTADO!* 🚨\n📍 IP: `{disp.get('ip')}`\n"
                               f"🏷 *MAC:* `{mac.replace('_', ':')}`\n⚙️ {disp.get('fabricante')}")
                    markup = {"inline_keyboard": [[
                        {"text": "✅ Permitir y Bautizar", "callback_data": f"permitir_{codigo}_{mac}"}
                    ]]}
                    enviar_mensaje(chat_id, mensaje, reply_markup=markup)
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