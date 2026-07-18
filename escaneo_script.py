import os
import requests
import time
import threading
import telebot
import subprocess
import re
import datetime
import random
import string
import firebase_admin
from firebase_admin import credentials, db

# --- CONFIGURACIÓN ---
TOKEN_TELEGRAM = '8709241753:AAGBhWXccYJBoP4BQrCbFgeO-YmuyEDGv30'

# --- CONEXIÓN A FIREBASE ---
# Asegúrate de que el archivo serviceAccountKey.json esté en la misma carpeta
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'
})

bot = telebot.TeleBot(TOKEN_TELEGRAM)
fabricantes_cache = {} 

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

def enviar_alerta_telegram(ip, mac, fab, codigo):
    # Recuperamos el chat_id registrado en la nube por el usuario
    usuario_ref = db.reference(f'usuarios/{codigo}').get()
    chat_id = usuario_ref.get('chat_id') if usuario_ref else None

    if chat_id:
        mensaje = (f"🚨 ¡INTRUSO DETECTADO en red {codigo}!\n\n"
                   f"📍 IP: `{ip}`\n"
                   f"🏷️ MAC: `{mac.replace('_', ':')}`\n"
                   f"⚙️ Fabricante: {fab}")
        
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("✅ Permitir", callback_data=f"permitir_{mac}"))
        markup.add(telebot.types.InlineKeyboardButton("❌ Ignorar", callback_data=f"ignorar_{mac}"))
        
        bot.send_message(chat_id, mensaje, reply_markup=markup, parse_mode="Markdown")
    else:
        print(f"⚠️ Alerta no enviada: El usuario {codigo} aún no ha iniciado el bot (/start).")

def escanear_red(codigo):
    try:
        # Escaneo ARP
        subprocess.run("for /L %i in (1,1,254) do @start /b ping -n 1 -w 100 192.168.1.%i >nul", shell=True, timeout=5)
        time.sleep(2)
        resultado = subprocess.check_output("arp -a", shell=True).decode('utf-8', errors='ignore')
        dispositivos = re.findall(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([a-f0-9A-F-]{17})", resultado)
        
        ref_dispositivos = db.reference(f'usuarios/{codigo}/dispositivos_detectados')
        
        for ip, mac_raw in dispositivos:
            mac_key = mac_raw.replace("-", "_").lower()
            
            # Solo procesamos si no existe en la base de datos
            if not ref_dispositivos.child(mac_key).get():
                info_disp = {
                    'ip': ip,
                    'fabricante': obtener_fabricante(mac_raw.replace("-", ":")),
                    'es_intruso': True,
                    'tipo': 'Desconocido'
                }
                ref_dispositivos.child(mac_key).set(info_disp)
                threading.Thread(target=enviar_alerta_telegram, args=(ip, mac_key, info_disp['fabricante'], codigo)).start()
                
    except Exception as e:
        print(f"Error en escaneo: {e}")

# --- MAIN ---
if __name__ == "__main__":
    codigo = generar_codigo()
    registrar_codigo_en_nube(codigo)
    print(f"🔑 TU CÓDIGO: {codigo}")
    
    # Hilo para el bot (para procesar callbacks como permitir/ignorar)
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    while True:
        if verificar_acceso(codigo):
            escanear_red(codigo)
        else:
            print("❌ Acceso suspendido o código inactivo.")
        time.sleep(30)