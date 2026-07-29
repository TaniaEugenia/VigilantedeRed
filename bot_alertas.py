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
        if not event.data or not isinstance(event.data, dict): 
            return
        
        ahora_timestamp = datetime.datetime.now().timestamp()

        # Recorremos los datos que llegan de Firebase
        for codigo, usuario_data in event.data.items():
            if not isinstance(usuario_data, dict):
                continue
            
            dispositivos = usuario_data.get('dispositivos_detectados', {})
            if not isinstance(dispositivos, dict):
                continue

            for mac, disp in dispositivos.items():
                # Validación previa para evitar que crashee si disp no es un diccionario
                if isinstance(disp, dict):
                    chat_id = disp.get('chat_id')
                else:
                    print(f"Advertencia: El dispositivo no arrojó un diccionario válido. Valor actual: {disp}")
                    chat_id = None  # Si el usuario eligió no recibir más avisos

                if not chat_id:
                    continue

                if disp.get('silenciado'):
                    continue

                alerta_enviada = disp.get('alerta_enviada', False)
                segundo_aviso_enviado = disp.get('segundo_aviso_enviado', False)
                intervalo_hs = disp.get('intervalo_recordatorio_hs')
                ultima_alerta_ts = disp.get('ultima_alerta_ts', 0)

                # -------------------------------------------------------------
                # CASO 1: PRIMER ESCANEO (Alerta inicial estándar)
                # -------------------------------------------------------------
                if not alerta_enviada:
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
                    
                    markup = {"inline_keyboard": [
                        [
                            {"text": "✅ Permitir y Bautizar", "callback_data": f"permitir|{codigo}|{mac}"},
                            {"text": "❌ Ignorar", "callback_data": f"ignorar|{mac}"}
                        ],
                        [
                            {"text": "🗑️ Eliminar Dispositivo", "callback_data": f"pre_eliminar|{codigo}|{mac}"}
                        ]
                    ]}
                    
                    enviar_mensaje(chat_id, mensaje, reply_markup=markup)
                    
                    db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
                        'alerta_enviada': True,
                        'ultima_alerta_ts': ahora_timestamp
                    })

                # -------------------------------------------------------------
                # CASO 2: SEGUNDO ESCANEO (Sigue sin nombre -> Preguntar horario/silenciar)
                # -------------------------------------------------------------
                elif alerta_enviada and not segundo_aviso_enviado and intervalo_hs is None:
                    mensaje = (
                        f"⏳ *EL DISPOSITIVO SIGUE SIN NOMBRE* ⏳\n\n"
                        f"📍 *IP:* `{disp.get('ip', 'Desconocida')}`\n"
                        f"🏷 *MAC:* `{mac.replace('_', ':')}`\n\n"
                        f"Detectamos que el dispositivo continúa conectado sin bautizar.\n"
                        f"¿Cada cuánto querés que te recordemos nombrarlo?"
                    )
                    
                    markup = {"inline_keyboard": [
                        [{"text": "✅ Bautizar Ahora", "callback_data": f"permitir|{codigo}|{mac}"}],
                        [
                            {"text": "⏱ 1 Hora", "callback_data": f"freq|1|{codigo}|{mac}"},
                            {"text": "⏱ 4 Horas", "callback_data": f"freq|4|{codigo}|{mac}"},
                            {"text": "⏱ 24 Horas", "callback_data": f"freq|24|{codigo}|{mac}"}
                        ],
                        [{"text": "🔕 No volver a notificar", "callback_data": f"silenciar|{codigo}|{mac}"}],
                        [{"text": "🗑️ Eliminar Dispositivo", "callback_data": f"pre_eliminar|{codigo}|{mac}"}]
                    ]}
                    
                    enviar_mensaje(chat_id, mensaje, reply_markup=markup)
                    
                    db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
                        'segundo_aviso_enviado': True,
                        'ultima_alerta_ts': ahora_timestamp
                    })

                # -------------------------------------------------------------
                # CASO 3: RECORDATORIOS POSTERIORES (Si eligió un intervalo de horas)
                # -------------------------------------------------------------
                elif intervalo_hs and (ahora_timestamp - ultima_alerta_ts) >= (intervalo_hs * 3600):
                    mensaje = (
                        f"🔔 *RECORDATORIO DE DISPOSITIVO* 🔔\n\n"
                        f"📍 *IP:* `{disp.get('ip', 'Desconocida')}`\n"
                        f"🏷 *MAC:* `{mac.replace('_', ':')}`\n\n"
                        f"Este equipo sigue sin ser bautizado en tu red."
                    )
                    
                    markup = {"inline_keyboard": [
                        [{"text": "✅ Permitir y Bautizar", "callback_data": f"permitir|{codigo}|{mac}"}],
                        [{"text": "🔕 No volver a notificar", "callback_data": f"silenciar|{codigo}|{mac}"}],
                        [{"text": "🗑️ Eliminar Dispositivo", "callback_data": f"pre_eliminar|{codigo}|{mac}"}]
                    ]}
                    
                    enviar_mensaje(chat_id, mensaje, reply_markup=markup)
                    
                    db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
                        'ultima_alerta_ts': ahora_timestamp
                    })

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

                    # ---------------------------------------------------------
                    # FLUJO DE ELIMINACIÓN DE DISPOSITIVOS
                    # ---------------------------------------------------------
                    elif data.startswith("pre_eliminar|"):
                        try:
                            _, codigo, mac = data.split("|")
                            mac_clean = mac.replace('_', ':')
                            
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            mensaje_confirmar = (
                                f"⚠️ *¿ESTÁS SEGURO?*\n\n"
                                f"Vas a borrar el dispositivo con MAC `{mac_clean}` de la base de datos."
                            )
                            markup_confirmar = {"inline_keyboard": [
                                [
                                    {"text": "🚨 Confirmar eliminación", "callback_data": f"confirm_eliminar|{codigo}|{mac}"},
                                    {"text": "↩️ Cancelar", "callback_data": f"cancel_eliminar|{codigo}|{mac}"}
                                ]
                            ]}
                            
                            requests.post(url_edit, data={
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "text": mensaje_confirmar,
                                "parse_mode": "Markdown",
                                "reply_markup": json.dumps(markup_confirmar)
                            })
                        except Exception as e:
                            print(f"Error en pre_eliminar: {e}")

                    elif data.startswith("confirm_eliminar|"):
                        try:
                            _, codigo, mac = data.split("|")
                            db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').delete()
                            
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            requests.post(url_edit, data={
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "text": "🗑️ *Dispositivo eliminado correctamente de la base de datos.*",
                                "parse_mode": "Markdown"
                            })
                        except Exception as e:
                            print(f"Error confirmando eliminación: {e}")

                    elif data.startswith("cancel_eliminar|"):
                        try:
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            requests.post(url_edit, data={
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "text": "❌ *Operación cancelada.* El dispositivo no fue eliminado.",
                                "parse_mode": "Markdown"
                            })
                        except Exception as e:
                            print(f"Error al cancelar eliminación: {e}")

                    # B) Configuración de Frecuencia de Recordatorio
                    elif data.startswith("freq|"):
                        try:
                            _, horas, codigo, mac = data.split("|")
                            horas = int(horas)
                            
                            db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
                                'intervalo_recordatorio_hs': horas,
                                'ultima_alerta_ts': datetime.datetime.now().timestamp()
                            })
                            
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            requests.post(url_edit, data={
                                "chat_id": chat_id, 
                                "message_id": message_id, 
                                "text": f"⏱ ¡Entendido! Te recordaré sobre este dispositivo cada *{horas} hora(s)* si sigue sin bautizar.", 
                                "parse_mode": "Markdown"
                            })
                        except Exception as e:
                            print(f"Error guardando frecuencia: {e}")

                    # C) Opción de Silenciar Permanentemente
                    elif data.startswith("silenciar|"):
                        try:
                            _, codigo, mac = data.split("|")
                            
                            db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
                                'silenciado': True
                            })
                            
                            url_edit = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageText"
                            requests.post(url_edit, data={
                                "chat_id": chat_id, 
                                "message_id": message_id, 
                                "text": "🔕 *Notificaciones desactivadas* para este dispositivo.", 
                                "parse_mode": "Markdown"
                            })
                        except Exception as e:
                            print(f"Error al silenciar dispositivo: {e}")

                    # D) El cliente avisa que ya realizó el pago
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

                    # E) Administrador aprueba el pago e impacta Firebase
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

                    # F) Administrador rechaza la alerta de pago
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
                                usuario_ref = db.reference(f'usuarios/{codigo}')
                                if usuario_ref.get() is not None:
                                    usuario_ref.update({'chat_id': chat_id})
                                    usuario_vinculado[chat_id] = codigo
                                    enviar_mensaje(chat_id, f"✅ Vinculado exitosamente al código: {codigo}.")
                                else:
                                    enviar_mensaje(chat_id, f"❌ El código `{codigo}` no existe en la base de datos. Verificá si lo escribiste bien.")
                            except Exception as e:
                                enviar_mensaje(chat_id, "❌ Error al conectar con la base de datos.")
                                print(f"Error en /start Firebase: {e}")
                        else:
                            enviar_mensaje(chat_id, "⚠️ Por favor ingresá el código. Ejemplo: `/start TU_CODIGO`")
                    
                    # Comando /milista
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
                                
                                # LISTADO Y OPCIÓN DE GESTIÓN EN CADA DISPOSITIVO
                                dispositivos = datos_usuario.get('dispositivos_detectados', {})
                                
                                if not dispositivos:
                                    enviar_mensaje(chat_id, f"📋 *REPORTE DE RED (`{codigo}`)*\n\n_No hay dispositivos registrados._")
                                else:
                                    enviar_mensaje(chat_id, f"📋 *REPORTE Y GESTIÓN DE RED (`{codigo}`)*\n\nPresioná *Eliminar* si querés borrar un equipo:")
                                    for mac, d in dispositivos.items():
                                        mac_clean = mac.replace('_', ':')
                                        nombre = d.get('nombre_bautizado')
                                        ip = d.get('ip', 'IP desconocida')
                                        
                                        if nombre:
                                            texto_disp = f"✅ *{nombre}*\n📍 IP: `{ip}` | MAC: `{mac_clean}`"
                                        else:
                                            fab = d.get('fabricante', 'Desconocido')
                                            texto_disp = f"⚠️ *Sin Nombre* ({fab})\n📍 IP: `{ip}` | MAC: `{mac_clean}`"
                                        
                                        markup_disp = {"inline_keyboard": [[
                                            {"text": "🗑️ Eliminar este dispositivo", "callback_data": f"pre_eliminar|{codigo}|{mac}"}
                                        ]]}
                                        enviar_mensaje(chat_id, texto_disp, reply_markup=markup_disp)
                                        
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
                            enviar_mensaje(chat_id, "❌ Hubo un problema al guardar el nombre.")
                            
        time.sleep(1)

if __name__ == "__main__":
    threading.Thread(target=escuchar_firebase, daemon=True).start()
    print("Vigilante de red comercial encendido y escuchando...")
    procesar_updates_telegram()