import os
import requests
import time
import threading
import telebot
import re
import datetime
import random
import string
import sys
import firebase_admin
from firebase_admin import credentials, db

# --- NUEVA IMPORTACIÓN PARA NPCAP ---
from scapy.all import ARP, Ether, srp, get_if_addr, conf

# --- CONFIGURACIÓN ---
TOKEN_TELEGRAM = '8709241753:AAGBhWXccYJBoP4BQrCbFgeO-YmuyEDGv30'

# --- FUNCIÓN PARA ENCONTRAR ARCHIVOS DENTRO DEL EXE ---
def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- CONEXIÓN A FIREBASE ---
ruta_json = ruta_recurso("config_vinculacion.json")
cred = credentials.Certificate(ruta_json)
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'
})

bot = telebot.TeleBot(TOKEN_TELEGRAM)
fabricantes_cache = {} 

# --- VARIABLES TEMPORALES DEL BOT ---
esperando_nombre = {}

def generar_codigo():
    return "VIG-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

def registrar_codigo_en_nube(codigo):
    try:
        db.reference(f'usuarios/{codigo}').update({
            'estado': 'activo',
            'fecha_creacion': str(datetime.datetime.now())
        })
        print(f"✅ Código {codigo} registrado/actualizado en la nube.")
    except Exception as e:
        print(f"❌ Error al registrar: {e}")

def verificar_acceso(codigo):
    ref = db.reference(f'usuarios/{codigo}')
    data = ref.get()
    return data is not None and data.get('estado') == 'activo'

def obtener_fabricante(mac):
    if mac in fabricantes_cache: return fabricantes_cache[mac]
    try:
        r = requests.get(f"https://api.macvendors.com/{mac}", timeout=2)
        nombre = r.text if r.status_code == 200 else "Desconocido"
        fabricantes_cache[mac] = nombre
        return nombre
    except: return "Desconocido"

# --- PROCESADOR DEL COMANDO /START PARA VINCULACIÓN AUTOMÁTICA ---
@bot.message_handler(commands=['start'])
def atender_start(message):
    try:
        texto = message.text.strip()
        partes = texto.split(" ")
        
        if len(partes) < 2:
            bot.reply_to(message, "❌ Por favor, iniciá el bot enviando tu código. Ejemplo: `/start VIG-1234`", parse_mode="Markdown")
            return
            
        codigo_usuario = partes[1].upper().strip()
        ref_usuario = db.reference(f'usuarios/{codigo_usuario}')
        
        if ref_usuario.get() is not None:
            ref_usuario.update({'chat_id': message.chat.id})
            bot.reply_to(message, f"🚀 ¡Dispositivo vinculado con éxito!\n\nA partir de ahora vas a recibir acá las alertas de la red `{codigo_usuario}`.", parse_mode="Markdown")
            print(f"📱 Bot enlazado automáticamente: {codigo_usuario} -> ChatID: {message.chat.id}")
        else:
            bot.reply_to(message, "❌ El código ingresado no existe o no es válido. Revisalo en la pantalla de tu PC.")
            
    except Exception as e:
        print(f"Error en comando start: {e}")

# --- ESCUCHADOR DE BOTONES TELEGRAM (CALLBACKS) ---
@bot.callback_query_handler(func=lambda call: True)
def responder_botones(call):
    try:
        partes = call.data.split("_", 1)
        if len(partes) < 2: return
        accion, mac = partes[0], partes[1]
        
        chat_id = call.message.chat.id
        
        usuarios_ref = db.reference('usuarios').get()
        codigo_usuario = None
        if usuarios_ref:
            for cod, datos in usuarios_ref.items():
                if datos.get('chat_id') == chat_id:
                    codigo_usuario = cod
                    break

        if not codigo_usuario:
            bot.answer_callback_query(call.id, "❌ Error: Dispositivo no vinculado.")
            return

        if accion == "permitir":
            bot.answer_callback_query(call.id, "Preparando para bautizar...")
            esperando_nombre[chat_id] = {"mac": mac, "codigo": codigo_usuario}
            bot.send_message(chat_id, "✍️ Escribime el nombre para este dispositivo:")
            
        elif accion == "ignorar":
            bot.answer_callback_query(call.id, "Alerta ignorada.")
            bot.edit_message_text(f"⚠️ Alerta ignorada para `{mac.replace('_', ':')}`.", chat_id, call.message.message_id, parse_mode="Markdown")
    except Exception as e:
        print(f"Error al procesar callback: {e}")

# --- CAPTURA DEL TEXTO (EL BAUTISMO) ---
@bot.message_handler(func=lambda message: message.chat.id in esperando_nombre)
def bautizar_dispositivo(message):
    try:
        chat_id = message.chat.id
        nombre_dispositivo = message.text.strip()
        
        datos_espera = esperando_nombre[chat_id]
        mac = datos_espera["mac"]
        codigo = datos_espera["codigo"]
        
        ref_dispositivo = db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}')
        ref_dispositivo.update({
            'nombre': nombre_dispositivo,
            'es_intruso': False,
            'tipo': 'Autorizado'
        })
        
        bot.send_message(chat_id, f"✅ Dispositivo \"{nombre_dispositivo}\" bautizado y autorizado correctamente.")
        del esperando_nombre[chat_id]
        
    except Exception as e:
        print(f"Error al bautizar en Firebase: {e}")

# --- COMANDO /MILISTA CORREGIDO ---
@bot.message_handler(commands=['milista'])
def ver_lista(message):
    try:
        chat_id = message.chat.id
        
        usuarios_ref = db.reference('usuarios').get()
        codigo_usuario = None
        if usuarios_ref:
            for cod, datos in usuarios_ref.items():
                if datos.get('chat_id') == chat_id:
                    codigo_usuario = cod
                    break
        
        if not codigo_usuario:
            bot.reply_to(message, "❌ No tenés ninguna red vinculada. Usá `/start TU_CÓDIGO` primero.")
            return
            
        dispositivos = db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados').get()
        
        if not dispositivos:
            bot.reply_to(message, "📋 No hay dispositivos registrados en tu red todavía.")
            return
            
        respuesta = "📋 *Dispositivos habilitados:*\n"
        hay_autorizados = False
        
        for mac, info in dispositivos.items():
            if info.get('es_intruso') is False:
                nombre = info.get('nombre', 'Sin nombre')
                mac_formateada = mac.replace('_', ':')
                respuesta += f"✅ {nombre} (`{mac_formateada}`)\n"
                hay_autorizados = True
                
        if not hay_autorizados:
            respuesta = "📋 No tenés ningún dispositivo bautizado o permitido todavía."
            
        bot.send_message(chat_id, respuesta, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error en comando milista: {e}")

def enviar_alerta_telegram(ip, mac, fab, codigo):
    usuario_ref = db.reference(f'usuarios/{codigo}').get()
    chat_id = usuario_ref.get('chat_id') if usuario_ref else None

    if chat_id:
        mensaje = (f"🚨 ¡INTRUSO DETECTADO en red {codigo}!\n\n"
                   f"📍 IP: `{ip}`\n"
                   f"🏷️ MAC: `{mac.replace('_', ':')}`\n"
                   f"⚙️ Fabricante: {fab}\n\n"
                   f"¿Querés darle permiso de acceso a tu red?")
        
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("✅ Permitir y Bautizar", callback_data=f"permitir_{mac}"))
        markup.add(telebot.types.InlineKeyboardButton("❌ Ignorar", callback_data=f"ignorar_{mac}"))
        
        bot.send_message(chat_id, mensaje, reply_markup=markup, parse_mode="Markdown")
    else:
        print(f"⚠️ Alerta no enviada: El usuario {codigo} aún no ha enlazado su chat_id en Firebase.")

# --- ESCANEO CON NPCAP ---
def escanear_red(codigo):
    try:
        ip_local = get_if_addr(conf.iface)
        rango_red = re.sub(r'\.\d+$', '.0/24', ip_local)
        
        paquete = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=rango_red)
        resultado, _ = srp(paquete, timeout=2, verbose=False)
        
        ref_dispositivos = db.reference(f'usuarios/{codigo}/dispositivos_detectados')
        
        for enviado, recibido in resultado:
            ip = recibido.psrc
            mac_raw = recibido.hwsrc
            mac_key = mac_raw.replace(":", "_").lower()
            
            disp_ref = ref_dispositivos.child(mac_key)
            disp_data = disp_ref.get()
            
            if not disp_data:
                # El dispositivo es totalmente nuevo en la red
                info_disp = {
                    'ip': ip,
                    'fabricante': obtener_fabricante(mac_raw),
                    'es_intruso': True,
                    'tipo': 'Desconocido'
                }
                disp_ref.set(info_disp)
                threading.Thread(target=enviar_alerta_telegram, args=(ip, mac_key, info_disp['fabricante'], codigo)).start()
            
            elif disp_data.get('es_intruso') is True:
                # El dispositivo ya estaba registrado pero SIGUE sin ser bautizado
                disp_ref.update({'ip': ip})
                
    except Exception as e:
        print(f"❌ Error en escaneo Npcap: {e}")

# --- MAIN ---
if __name__ == "__main__":
    codigo = generar_codigo()
    registrar_codigo_en_nube(codigo)
    print("\n" + "="*40)
    print(f"🔑 TU CÓDIGO DE SEGURIDAD ES: {codigo}")
    print("👉 Entrá a Telegram y mandale al bot: /start " + codigo)
    print("="*40 + "\n")
    
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    while True:
        if verificar_acceso(codigo):
            escanear_red(codigo)
        else:
            print("❌ Acceso suspendido o código inactivo.")
        time.sleep(30)