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

# --- ESCUCHA EN TIEMPO REAL (ALERTAS DE DISPOSITIVOS) ---
def escuchar_firebase():
    def callback(event):
        if not event.data or not isinstance(event.data, dict): return
        for codigo, datos_usuario in event.data.items():
            chat_id = datos_usuario.get('chat_id')
            if not chat_id: continue
            
            dispositivos = datos_usuario.get('dispositivos_detectados', {})
            for mac, disp in dispositivos.items():
                # Notifica si es intruso o si es un equipo detectado que aún no fue bautizado
                if (disp.get('es_intruso') or not disp.get('nombre_bautizado')) and not disp.get('alerta_enviada'):
                    es_intruso = disp.get('es_intruso', True)
                    titulo = "🚨 *¡INTRUSO DETECTADO!* 🚨" if es_intruso else "⚠️ *NUEVO DISPOSITIVO SIN BAUTIZAR* ⚠️"
                    
                    mensaje = (
                        f"{titulo}\n\n"
                        f"📍 *IP:* `{disp.get('ip', 'Desconocida')}`\n"
                        f"🏷 *MAC:* `{mac.replace('_', ':')}`\n"
                        f"⚙️ *Fabricante:* {disp.get('fabricante', 'Desconocido')}\n"
                        f"🔍 *Tipo estimado:* {disp.get('tipo', 'Desconocido')}\n\n"
                        f"¿Querés darle un nombre y autorizarlo en tu red?"
                    )
                    
                    markup = {"inline_keyboard": [[
                        {"text": "✅ Permitir y Bautizar", "callback_data": f"permitir|{codigo}|{mac}"},
                        {"text": "❌ Ignorar", "callback_data": f"ignorar|{mac}"}
                    ]]}
                    
                    enviar_mensaje(chat_id, mensaje, reply_markup=markup)
                    # Marcamos para evitar spam repetido en tiempo real
                    db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({'alerta_enviada': True})
    
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
                            
                    elif data.startswith("ignorar|"):
                        try:
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            requests.post(url_edit, data={"chat_id": chat_id, "message_id": message_id, "text": "👁️ Dispositivo ignorado por el momento.", "parse_mode": "Markdown"})
                        except Exception as e:
                            print(f"Error al ignorar: {e}")

                    # B) El cliente avisa que ya realizó el pago
                    elif data.startswith("avisar_"):
                        try:
                            partes = data.split("_")
                            horas = partes[1]
                            codigo_usuario = partes[2]
                            
                            enviar_mensaje(chat_id, "✅ *Aviso recibido.* Estamos verificando tu pago en el sistema. Recordá que la activación puede demorar hasta 24 hs. ¡Muchas gracias!")
                            
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
                            
                            ref.update({
                                'estado': 'activo',
                                'fecha_vencimiento': nueva_fecha_venc.strftime("%Y-%m-%d %H:%M:%S")
                            })
                            
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            payload_edit = {
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "text": f"🟢 *Activado con éxito.* Red `{codigo_usuario}` habilitada por {horas}hs.",
                                "parse_mode": "Markdown"
                            }
                            requests.post(url_edit, data=payload_edit)
                            
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
                    
                    # Comando /start
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
                    
                    # Comando /milista (MUESTRA BAUTIZADOS Y PENDIENTES POR SEPARADO)
                    elif texto.startswith("/milista"):
                        codigo = usuario_vinculado.get(chat_id)
                        
                        if not codigo: 
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
                                
                                # Verificación Expiración
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
                                                        f"2️⃣ *Una vez realizado el pago, presiona abajo:*")
                                        
                                        markup_pago = {"inline_keyboard": [
                                            [{"text": "🔔 Ya pagué 24 Horas (Notificar)", "callback_data": f"avisar_24_{codigo}"}],
                                            [{"text": "📅 Ya pagué 30 Días (Notificar)", "callback_data": f"avisar_720_{codigo}"}]
                                        ]}
                                        enviar_mensaje(chat_id, mensaje_pago, reply_markup=markup_pago)
                                        continue
                                
                                # SEPARACIÓN DE DISPOSITIVOS EN LISTA
                                dispositivos = datos_usuario.get('dispositivos_detectados', {})
                                
                                bautizados = []
                                pendientes = []
                                
                                for k, d in dispositivos.items():
                                    mac_clean = k.replace('_', ':')
                                    nombre = d.get('nombre_bautizado')
                                    if nombre:
                                        bautizados.append(f"✅ *{nombre}* (`{mac_clean}`)")
                                    else:
                                        ip = d.get('ip', 'IP no desc.')
                                        fab = d.get('fabricante', 'Desconocido')
                                        pendientes.append(f"⚠️ `{mac_clean}` - IP: {ip} ({fab})")
                                
                                msg_final = f"📋 *REPORTE DE RED (`{codigo}`)*\n\n"
                                
                                msg_final += "🟢 *Dispositivos Autorizados (Bautizados):*\n"
                                msg_final += "\n".join(bautizados) if bautizados else "_Ninguno bautizado aún._"
                                
                                msg_final += "\n\n🟡 *Dispositivos Detectados Sin Nombre:*\n"
                                msg_final += "\n".join(pendientes) if pendientes else "_No hay dispositivos pendientes._"
                                
                                enviar_mensaje(chat_id, msg_final)
                            except Exception as e:
                                print(f"Error al traer lista de dispositivos: {e}")
                        else:
                            enviar_mensaje(chat_id, "❌ No encontré ninguna red vinculada. Usá `/start TU_CODIGO` primero.")
                    
                    # Captura de textos para Bautismos
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
    threading.Thread(target=escuchar_firebase, daemon=True).start()
    print("Vigilante de red comercial encendido y escuchando...")
    procesar_updates_telegram()