import time
import requests
import threading
import firebase_admin
import os
import json
from firebase_admin import credentials, db

# --- FUNCIÓN DE ENVÍO ---
def enviar_mensaje(chat_id, texto, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(reply_markup) if reply_markup else None
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Error al enviar mensaje: {e}")

# --- CONFIGURACIÓN DE TOKENS ---
TOKEN_TELEGRAM = '8709241753:AAGBhWXccYJBoP4BQrCbFgeO-YmuyEDGv30'

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
            print(f"Error de conexión con Telegram: {e}")
            time.sleep(2)
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
                        try:
                            _, codigo, mac = data.split("|")
                            esperando_nombre[chat_id] = (codigo, mac)
                            enviar_mensaje(chat_id, "✍️ Escribime el nombre para este dispositivo:")
                        except Exception as e:
                            print(f"Error procesando callback: {e}")
                
                # 2. MANEJO DE MENSAJES DE TEXTO
                elif "message" in update and "text" in update["message"]:
                    msg = update["message"]
                    chat_id, texto = msg["chat"]["id"], msg["text"]
                    
                    # El comando /start SIEMPRE tiene prioridad absoluta y rompe estados anteriores
                    if texto.startswith("/start"):
                        # Si estaba esperando un nombre, cancelamos esa espera
                        if chat_id in esperando_nombre:
                            esperando_nombre.pop(chat_id)
                            
                        partes = texto.split()
                        codigo = partes[1].upper() if len(partes) > 1 else None
                        if codigo:
                            try:
                                db.reference(f'usuarios/{codigo}').update({'chat_id': chat_id})
                                usuario_vinculado[chat_id] = codigo
                                enviar_mensaje(chat_id, f"✅ Vinculado exitosamente al código: {codigo}.")
                            except Exception as e:
                                enviar_mensaje(chat_id, "❌ Error al conectar con la base de datos.")
                                print(f"Error en /start Firebase: {e}")
                        else:
                            enviar_mensaje(chat_id, "⚠️ Por favor ingresá el código. Ejemplo: `/start TU_CODIGO`")
                    
                    elif texto.startswith("/milista"):
                        codigo = usuario_vinculado.get(chat_id)
                        
                        if not codigo: # Intento de recuperación dinámica
                            try:
                                usuarios_db = db.reference('usuarios').get() or {}
                                for cod, datos in usuarios_db.items():
                                    if datos.get('chat_id') == chat_id:
                                        codigo = cod
                                        usuario_vinculado[chat_id] = codigo
                                        break
                            except Exception as e:
                                print(f"Error recuperando usuario: {e}")
                        
                        if codigo:
                            try:
                                dispositivos = db.reference(f'usuarios/{codigo}/dispositivos_detectados').get() or {}
                                lista = "\n".join([f"✅ {d.get('nombre_bautizado')} ({k.replace('_', ':')})" 
                                                   for k, d in dispositivos.items() if d.get('nombre_bautizado')])
                                enviar_mensaje(chat_id, f"📋 *Dispositivos habilitados:*\n{lista or 'Ninguno todavía.'}")
                            except Exception as e:
                                print(f"Error al traer lista: {e}")
                        else:
                            enviar_mensaje(chat_id, "❌ No encontré ninguna red vinculada. Usá `/start TU_CODIGO` primero.")
                    
                    # Si no es un comando, evaluamos si el usuario estaba bautizando un dispositivo
                    elif chat_id in esperando_nombre:
                        try:
                            codigo, mac = esperando_nombre.pop(chat_id)
                            db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
                                'nombre_bautizado': texto, 
                                'es_intruso': False
                            })
                            enviar_mensaje(chat_id, f"✅ Dispositivo \"{texto}\" bautizado y autorizado correctamente.")
                        except Exception as e:
                            print(f"Error guardando bautismo: {e}")
                            enviar_mensaje(chat_id, "❌ Hubo un problema al guardar el nombre en Firebase.")
                            
        time.sleep(1)

if __name__ == "__main__":
    # Arrancamos el hilo de Firebase
    threading.Thread(target=escuchar_firebase, daemon=True).start()
    # Iniciamos el bucle principal de Telegram
    print("Vigilante de red encendido y escuchando...")
    procesar_actualizaciones()