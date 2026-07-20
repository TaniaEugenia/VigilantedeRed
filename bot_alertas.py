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
esperando_nombre = {} # {chat_id: (codigo, mac)}
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
                    mensaje = (
                        f"🚨 *¡INTRUSO DETECTADO!* 🚨\n\n"
                        f"📍 *IP:* `{disp.get('ip')}`\n"
                        f"🏷 *MAC:* `{mac.replace('_', ':')}`\n"
                        f"⚙️ *Fabricante:* {disp.get('fabricante', 'Desconocido')}\n"
                        f"🔍 *Tipo estimado:* {disp.get('tipo', 'Desconocido')}\n\n"
                        f"¿Querés darle permiso de acceso a tu red?"
                    )
                    
                    # Cambiamos el separador "_" por "|" para evitar errores de parseo con las MACs
                    markup = {"inline_keyboard": [[
                        {"text": "✅ Permitir y Bautizar", "callback_data": f"permitir|{codigo}|{mac}"},
                        {"text": "❌ Ignorar", "callback_data": f"ignorar|{mac}"}
                    ]]}
                    
                    enviar_mensaje(chat_id, mensaje, reply_markup=markup)
    
    db.reference('usuarios').listen(callback)

def procesar_actualizaciones():
    offset = None
    while True:
        url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/getUpdates?timeout=10&offset={offset}"
        try:
            response = requests.get(url).json()
        except Exception as e:
            print(f"Error de conexión: {e}")
            time.sleep(1)
            continue

        if "result" in response:
            for update in response["result"]:
                offset = update["update_id"] + 1
                
                # 1. MANEJO DE BOTONES (CALLBACK QUERIES)
                if "callback_query" in update:
                    query = update["callback_query"]
                    chat_id = query["message"]["chat"]["id"]
                    data = query["data"]
                    
                    if data.startswith("permitir|"):
                        # Separamos usando el nuevo carácter "|"
                        _, codigo, mac = data.split("|")
                        esperando_nombre[chat_id] = (codigo, mac)
                        enviar_mensaje(chat_id, "✍️ Escribime el nombre para este dispositivo:")
                
                # 2. MANEJO DE MENSAJES DE TEXTO
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
                        
                        # Si no está en memoria, intentamos recuperarlo buscando en Firebase
                        if not codigo:
                            usuarios_db = db.reference('usuarios').get() or {}
                            for cod, datos in usuarios_db.items():
                                if datos.get('chat_id') == chat_id:
                                    codigo = cod
                                    usuario_vinculado[chat_id] = codigo
                                    break
                        
                        if codigo:
                            dispositivos = db.reference(f'usuarios/{codigo}/dispositivos_detectados').get() or {}
                            lista = "\n".join([f"✅ {d.get('nombre_bautizado')} ({k.replace('_', ':')})" 
                                               for k, d in dispositivos.items() if d.get('nombre_bautizado')])
                            enviar_mensaje(chat_id, f"📋 *Dispositivos habilitados:*\n{lista or 'Ninguno todavía.'}")
                        else:
                            enviar_mensaje(chat_id, "❌ No encontré ninguna red vinculada. Por favor, usa /start [tu_codigo]")
                    
                    # 3. CAPTURA DEL NOMBRE (BAUTISMO)
                    elif chat_id in esperando_nombre:
                        codigo, mac = esperando_nombre.pop(chat_id)
                        
                        # Guardamos en Firebase: cambiamos es_intruso a False y seteamos el nombre
                        db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
                            'nombre_bautizado': texto, 
                            'es_intruso': False
                        })
                        enviar_mensaje(chat_id, f"✅ Dispositivo \"{texto}\" bautizado y autorizado correctamente.")
                        
        time.sleep(1)