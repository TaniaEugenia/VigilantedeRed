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
WHITELIST_FILE = r"C:\Users\Noxi-PC\Desktop\Vigilante de Red\dispositivos_autorizados.txt"
MEMORIA_FILE = r"C:\Users\Noxi-PC\Desktop\Vigilante de Red\alertados.txt"
SUBSCRIPCION_FILE = r"C:\Users\Noxi-PC\Desktop\Vigilante de Red\suscripcion.txt"

# --- CONEXIÓN A FIREBASE ---
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
        db.reference(f'usuarios/{codigo}').set({
            'estado': 'activo',
            'fecha_creacion': str(datetime.datetime.now())
        })
        print(f"✅ Código {codigo} registrado en la nube.")
    except Exception as e:
        print(f"❌ Error al registrar: {e}")

def verificar_acceso():
    if not os.path.exists(SUBSCRIPCION_FILE): return True
    with open(SUBSCRIPCION_FILE, "r") as f:
        try:
            return datetime.datetime.now() < datetime.datetime.fromisoformat(f.read().strip())
        except: return False

# --- LÓGICA TELEGRAM PERSONALIZADA ---
def enviar_alerta_telegram(ip, mac, fab, codigo):
    # Buscamos el chat_id del usuario asociado al código
    usuario_ref = db.reference(f'usuarios/{codigo}').get()
    chat_id = usuario_ref.get('chat_id') if usuario_ref and 'chat_id' in usuario_ref else None

    if chat_id:
        url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
        texto = f"🚨 ¡INTRUSO DETECTADO en red {codigo}!\n\n📍 IP: {ip}\n🏷️ MAC: {mac}\n⚙️ Fabricante: {fab}"
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Permitir", "callback_data": f"permitir_{mac}"}, 
            {"text": "❌ Ignorar", "callback_data": "ignorar"}
        ]]}
        requests.post(url, json={"chat_id": chat_id, "text": texto, "reply_markup": keyboard})
    else:
        print(f"⚠️ Alerta no enviada: El usuario {codigo} aún no ha iniciado el bot (/start).")

# --- ESCANEO ---
def cargar_whitelist():
    whitelist = set()
    if os.path.exists(WHITELIST_FILE):
        with open(WHITELIST_FILE, "r") as f:
            for line in f:
                if "," in line: whitelist.add(line.split(",")[0].strip().lower())
    return whitelist

def obtener_fabricante(mac):
    if mac in fabricantes_cache: return fabricantes_cache[mac]
    try:
        r = requests.get(f"https://api.macvendors.com/{mac}", timeout=2)
        nombre = r.text if r.status_code == 200 else "Desconocido"
        fabricantes_cache[mac] = nombre
        return nombre
    except: return "Desconocido"

def escanear_red(codigo, alertados):
    whitelist = cargar_whitelist()
    try:
        subprocess.run("for /L %i in (1,1,254) do @start /b ping -n 1 -w 100 192.168.1.%i >nul", shell=True, timeout=5)
        time.sleep(2)
        resultado = subprocess.check_output("arp -a", shell=True).decode('utf-8', errors='ignore')
        dispositivos = re.findall(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([a-f0-9A-F-]{17})", resultado)
        
        for ip, mac_raw in dispositivos:
            mac = mac_raw.replace("-", ":").lower()
            if not ip.startswith("192.168.1.") or mac.startswith("01:00:5e"): continue
            
            if mac not in whitelist and mac not in alertados:
                alertados.add(mac)
                with open(MEMORIA_FILE, "a") as f: f.write(f"{mac}\n")
                threading.Thread(target=enviar_alerta_telegram, args=(ip, mac, obtener_fabricante(mac), codigo)).start()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    codigo = generar_codigo()
    registrar_codigo_en_nube(codigo)
    print(f"🔑 TU CÓDIGO: {codigo}")
    
    # Cargar memoria de alertados
    alertados = set()
    if os.path.exists(MEMORIA_FILE):
        with open(MEMORIA_FILE, "r") as f: alertados = set(l.strip() for l in f)

    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    while True:
        if verificar_acceso():
            escanear_red(codigo, alertados)
        time.sleep(30)