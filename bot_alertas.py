import time
import requests
import threading
import firebase_admin
import os
import json
import datetime
from firebase_admin import credentials, db

# --- CONFIGURACIÓN DE TOKENS Y CRITICAL DATA ---
TOKEN_TELEGRAM = '8709241753:AAGBhWXccYJBoP4BQrCbFgeO-YmuyEDGv30'
MI_CHAT_ID_PERSONAL = 8640928982

# Inicializar Firebase
cred_json = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(cred_json)
firebase_admin.initialize_app(cred, {'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'})

# Diccionarios de estado internos
esperando_nombre = {} # {chat_id: (codigo, mac)}
usuario_vinculado = {} # {chat_id: codigo}

# --- FUNCIÓN NATIVA DE ENVÍO ---
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

# --- ESCUCHA EN TIEMPO REAL (ALERTAS DE INTRUSO INTACTAS) ---
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

# --- BUCLE DE ACTUALIZACIONES (POLLING CON REQUESTS) ---
def procesar_updates_telegram():
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
                
                # =========================================================
                # 1. MANEJO DE INTERACCIONES DE BOTONES (CALLBACK QUERIES)
                # =========================================================
                if "callback_query" in update:
                    query = update["callback_query"]
                    chat_id = query["message"]["chat"]["id"]
                    message_id = query["message"]["message_id"]
                    data = query["data"]
                    
                    # A) Botón nativo para iniciar bautismo de dispositivo
                    if data.startswith("permitir|"):
                        try:
                            _, codigo, mac = data.split("|")
                            esperando_nombre[chat_id] = (codigo, mac)
                            enviar_mensaje(chat_id, "✍️ Escribime el nombre para este dispositivo:")
                        except Exception as e:
                            print(f"Error procesando callback permitir: {e}")
                            
                    # B) El cliente avisa que ya realizó el pago (Opción B)
                    elif data.startswith("avisar_"):
                        try:
                            partes = data.split("_")
                            horas = partes[1]
                            codigo_usuario = partes[2]
                            
                            # Confirmamos la recepción al cliente
                            enviar_mensaje(chat_id, "✅ *Aviso recibido.* Estamos verificando tu pago en el sistema. Recordá que la activación puede demorar hasta 24 hs. ¡Muchas gracias!")
                            
                            # Te enviamos la alerta a tu chat privado para control manual
                            mensaje_admin = (f"💰 *¡ALERTA DE PAGO A VERIFICAR!*\n\n"
                                             f"👤 *Usuario (Chat ID):* `{chat_id}`\n"
                                             f"🔑 *Código Red:* `{codigo_usuario}`\n"
                                             f"⏳ *Plan solicitado:* {horas} horas.\n\n"
                                             f"Revisá tu Mercado Pago. Si el dinero ingresó, aprobalo acá abajo:")
                            
                            markup_admin = {"inline_keyboard": [
                                [{"text": "✅ Aprobar y Activar Servicio", "callback_data": f"aprobar_{horas}_{codigo_usuario}_{chat_id}"}],
                                [{"text": "❌ Rechazar / No pagó", "callback_data": f"rechazar_{chat_id}"}]
                            ]}
                            
                            enviar_mensaje(MI_CHAT_ID_PERSONAL, mensaje_admin, reply_markup=markup_admin)
                        except Exception as e:
                            print(f"Error al procesar el aviso del cliente: {e}")

                    # C) Administrador aprueba el pago e impacta Firebase
                    elif data.startswith("aprobar_"):
                        try:
                            partes = data.split("_")
                            horas = int(partes[1])
                            codigo_usuario = partes[2]
                            chat_cliente = int(partes[3])
                            
                            ref = db.reference(f'usuarios/{codigo_usuario}')
                            datos = ref.get() or {}
                            
                            fecha_base = datetime.datetime.now()
                            fecha_venc_actual_str = datos.get('fecha_vencimiento')
                            
                            if fecha_venc_actual_str:
                                try:
                                    fecha_venc_actual = datetime.datetime.strptime(fecha_venc_actual_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                                    if fecha_venc_actual > datetime.datetime.now():
                                        fecha_base = fecha_venc_actual
                                except:
                                    pass
                                    
                            nueva_fecha_venc = fecha_base + datetime.timedelta(hours=horas)
                            
                            # Actualizamos a activo y seteamos el nuevo vencimiento
                            ref.update({
                                'estado': 'activo',
                                'fecha_vencimiento': nueva_fecha_venc.strftime("%Y-%m-%d %H:%M:%S")
                            })
                            
                            # Modificamos tu mensaje de control para dejar registro
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            payload_edit = {
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "text": f"🟢 *Activado con éxito.* Red `{codigo_usuario}` habilitada por {horas}hs.",
                                "parse_mode": "Markdown"
                            }
                            requests.post(url_edit, data=payload_edit)
                            
                            # Notificamos al cliente la activación inmediata
                            texto_cliente = (f"🚀 *¡Tu pago fue verificado e ingresado al sistema!* \n\n"
                                             f"Tu red `{codigo_usuario}` ya se encuentra *ACTIVA*.\n"
                                             f"Protección válida hasta el: `{nueva_fecha_venc.strftime('%d/%m/%Y %H:%M:%S')}`.")
                            enviar_mensaje(chat_cliente, texto_cliente)
                        except Exception as e:
                            print(f"Error en aprobación del administrador: {e}")

                    # D) Administrador rechaza la alerta de pago
                    elif data.startswith("rechazar_"):
                        try:
                            chat_cliente = int(data.split("_")[1])
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            requests.post(url_edit, data={"chat_id": chat_id, "message_id": message_id, "text": "❌ Alerta rechazada / archivada.", "parse_mode": "Markdown"})
                            
                            enviar_mensaje(chat_cliente, "⚠️ No pudimos verificar tu pago. Si creés que es un error, por favor contactate con el soporte adjuntando el comprobante de la transacción.")
                        except Exception as e:
                            print(f"Error al rechazar pago: {e}")

                # =========================================================
                # 2. MANEJO DE MENSAJES DE TEXTO RECIBIDOS
                # =========================================================
                elif "message" in update and "text" in update["message"]:
                    msg = update["message"]
                    chat_id, texto = msg["chat"]["id"], msg["text"]
                    
                    # Comando /start (Vinculación de Nodos)
                    if texto.startswith("/start"):
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
                    
                    # Comando /milista (Muestra lista si está activo o bloquea pidiendo pago si venció)
                    elif texto.startswith("/milista"):
                        codigo = usuario_vinculado.get(chat_id)
                        
                        if not codigo: # Búsqueda de rescate dinámica en Firebase
                            try:
                                usuarios_db = db.reference('usuarios').get() or {}
                                for cod, datos in usuarios_db.items():
                                    if datos.get('chat_id') == chat_id:
                                        codigo = cod
                                        usuario_vinculado[chat_id] = codigo
                                        break
                            except Exception as e:
                                print(f"Error recuperando usuario dinámico: {e}")
                        
                        if codigo:
                            try:
                                datos_usuario = db.reference(f'usuarios/{codigo}').get() or {}
                                estado_actual = datos_usuario.get('estado', 'activo')
                                fecha_venc_str = datos_usuario.get('fecha_vencimiento')
                                
                                # Si no existe la variable de vencimiento, creamos las 24hs gratis iniciales
                                if not fecha_venc_str and datos_usuario.get('fecha_creacion'):
                                    try:
                                        fecha_c_str = datos_usuario.get('fecha_creacion').split(".")[0]
                                        fecha_c = datetime.datetime.strptime(fecha_c_str, "%Y-%m-%d %H:%M:%S")
                                        fecha_venc = fecha_c + datetime.timedelta(hours=24)
                                        fecha_venc_str = fecha_venc.strftime("%Y-%m-%d %H:%M:%S")
                                        db.reference(f'usuarios/{codigo}').update({'fecha_vencimiento': fecha_venc_str})
                                    except Exception as err_parse:
                                        print(f"Error parseando fecha_creacion: {err_parse}")
                                        fecha_venc_str = (datetime.datetime.now() + datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                                
                                # Verificación Comercial de Expiración
                                if fecha_venc_str:
                                    fecha_limite = datetime.datetime.strptime(fecha_venc_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                                    if datetime.datetime.now() > fecha_limite or estado_actual == 'suspendido':
                                        if estado_actual != 'suspendido':
                                            db.reference(f'usuarios/{codigo}').update({'estado': 'suspendido'})
                                        
                                        mensaje_pago = (f"⚠️ *¡Tu tiempo de protección ha vencido!* (Red `{codigo}`)\n\n"
                                                        f"El escaneo automático se encuentra pausado.\n\n"
                                                        f"1️⃣ *Aboná el plan que prefieras aquí:*\n"
                                                        f"🔗 [Pagar 24 Horas Extra - $10.000](https://mpago.la/1NqWsQf)\n"
                                                        f"🔗 [Pagar 30 Días / 720hs - $20.000](https://mpago.la/2N8NvtF)\n\n"
                                                        f"2️⃣ *Una vez realizado el pago, presiona abajo:*\n"
                                                        f"📌 _Nota: La verificación es manual y puede demorar hasta 24hs en habilitarse._")
                                        
                                        markup_pago = {"inline_keyboard": [
                                            [{"text": "🔔 Ya pagué 24 Horas (Notificar)", "callback_data": f"avisar_24_{codigo}"}],
                                            [{"text": "📅 Ya pagué 30 Días (Notificar)", "callback_data": f"avisar_720_{codigo}"}]
                                        ]}
                                        enviar_mensaje(chat_id, mensaje_pago, reply_markup=markup_pago)
                                        continue # Corta el flujo comercial
                                
                                # Flujo normal si está AL DÍA: Muestra su lista original limpia
                                dispositivos = datos_usuario.get('dispositivos_detectados', {})
                                lista = "\n".join([f"✅ {d.get('nombre_bautizado')} (`{k.replace('_', ':')}`)" 
                                                   for k, d in dispositivos.items() if d.get('nombre_bautizado')])
                                
                                enviar_mensaje(chat_id, f"📋 *Dispositivos autorizados en tu red:*\n\n{lista or 'Ninguno todavía.'}")
                            except Exception as e:
                                print(f"Error al traer lista de dispositivos: {e}")
                        else:
                            enviar_mensaje(chat_id, "❌ No encontré ninguna red vinculada. Usá `/start TU_CODIGO` primero.")
                    
                    # Captura de textos para Bautismos (Mantiene tu lógica nativa)
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
    # Arrancamos el daemon de Firebase para alertas en tiempo real
    threading.Thread(target=escuchar_firebase, daemon=True).start()
    
    # Arrancamos el procesador principal del bot
    print("Vigilante de red comercial encendido y escuchando...")
    procesar_updates_telegram()