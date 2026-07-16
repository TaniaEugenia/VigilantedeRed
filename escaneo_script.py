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
CHAT_ID_TELEGRAM = '8640928982'
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

# --- NUEVA FUNCIÓN: GENERAR CÓDIGO ---
def generar_codigo():
    letras_numeros = string.ascii_uppercase + string.digits
    codigo = "VIG-" + ''.join(random.choices(letras_numeros, k=4))
    return codigo

# --- REGISTRO EN LA NUBE ---
def registrar_codigo_en_nube(codigo):
    try:
        ref = db.reference('usuarios')
        ref.child(codigo).set({
            'estado': 'pendiente',
            'fecha_creacion': str(datetime.datetime.now()),
            'dispositivos': 'esperando_conexion'
        })
        print(f"✅ Código {codigo} registrado en la nube con éxito.")
    except Exception as e:
        print(f"❌ Error al registrar en la nube: {e}")

# --- MEMORIA Y SUSCRIPCIÓN ---
def cargar_alertados():
    if os.path.exists(MEMORIA_FILE):
        with open(MEMORIA_FILE, "r") as f:
            return set(line.strip() for line in f)
    return set()

alertados = cargar_alertados()

def verificar_acceso():
    if not os.path.exists(SUBSCRIPCION_FILE):
        fecha_fin = datetime.datetime.now() + datetime.timedelta(hours=24)
        guardar_fecha(fecha_fin)
        return True
    with open(SUBSCRIPCION_FILE, "r") as f:
        try:
            fecha_fin = datetime.datetime.fromisoformat(f.read().strip())
            return datetime.datetime.now() < fecha_fin
        except:
            return False

def guardar_fecha(fecha):
    with open(SUBSCRIPCION_FILE, "w") as f:
        f.write(fecha.isoformat())

# --- LÓGICA DE TELEGRAM ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data.startswith("permitir_"):
        mac = call.data.split("_")[1]
        msg = bot.send_message(call.message.chat.id, f"✅ Autorizando {mac}. ¿Qué nombre le ponemos?")
        bot.register_next_step_handler(msg, guardar_nombre_dispositivo, mac)
    elif call.data == "ignorar":
        bot.edit_message_text("❌ Intruso ignorado.", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['pagar'])
def enviar_links_pago(message):
    texto = (
        "⏳ **Tu acceso ha expirado.**\n\n"
        "Elige una opción para continuar:\n"
        "1️⃣ 24 horas extra: $10.000 ARS\n"
        "🔗 [Pagar 24hs](https://mpago.li/2ATXsjE)\n\n"
        "2️⃣ 30 días de acceso: $20.000 ARS\n"
        "🔗 [Pagar 30 días](https://mpago.li/1Kk977E)\n\n"
        "Una vez realizado el pago, usa /extender [dias] para activar."
    )
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['extender'])
def comando_extender(message):
    try:
        dias = int(message.text.split()[1])
        fecha_actual = datetime.datetime.now()
        nueva_fecha = fecha_actual + datetime.timedelta(days=dias)
        guardar_fecha(nueva_fecha)
        bot.reply_to(message, f"✅ Acceso extendido por {dias} días exitosamente.")
    except:
        bot.reply_to(message, "Error. Usa /extender 1 o /extender 30")

def guardar_nombre_dispositivo(message, mac):
    usuario_telegram = message.from_user.username or "Usuario"
    nombre_dispositivo = message.text
    nombre_final = f"Autorizado por {usuario_telegram} - {nombre_dispositivo}"
    with open(WHITELIST_FILE, "a") as f:
        f.write(f"{mac.lower()},{nombre_final}\n")
    bot.reply_to(message, f"¡Listo! {nombre_final} ha sido guardado.")

def enviar_alerta_telegram(ip, mac, fab):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    texto = (f"🚨 ¡INTRUSO DETECTADO!\n\n📍 IP: {ip}\n🏷️ MAC: {mac}\n⚙️ Fabricante: {fab}\n🔍 Tipo estimado: Dispositivo\n🖥️ Nombre de red: (Sin asignar)")
    keyboard = {"inline_keyboard": [[{"text": "✅ Permitir y Bautizar", "callback_data": f"permitir_{mac}"}, {"text": "❌ Ignorar", "callback_data": "ignorar"}]]}
    try:
        requests.post(url, json={"chat_id": CHAT_ID_TELEGRAM, "text": texto, "reply_markup": keyboard})
    except Exception as e:
        print(f"Error Telegram: {e}")

# --- ESCANEO ---
def cargar_whitelist():
    whitelist = set()
    if os.path.exists(WHITELIST_FILE):
        with open(WHITELIST_FILE, "r") as f:
            for line in f:
                if "," in line:
                    mac, _ = line.strip().split(",", 1)
                    whitelist.add(mac.lower())
    return whitelist

def obtener_fabricante(mac):
    if mac in fabricantes_cache: return fabricantes_cache[mac]
    try:
        r = requests.get(f"https://api.macvendors.com/{mac}", timeout=2)
        nombre = r.text if r.status_code == 200 else "Desconocido"
        fabricantes_cache[mac] = nombre
        return nombre
    except: return "Desconocido"

def escanear_red():
    whitelist = cargar_whitelist()
    dispositivos = []
    try:
        subprocess.run("for /L %i in (1,1,254) do @start /b ping -n 1 -w 100 192.168.1.%i >nul", shell=True, timeout=5)
        time.sleep(2)
        resultado = subprocess.check_output("arp -a", shell=True).decode('utf-8', errors='ignore')
        patron = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([a-f0-9A-F-]{17})")
        dispositivos = patron.findall(resultado)
    except Exception as e:
        print(f"Error durante el escaneo: {e}")
        return

    for ip, mac_raw in dispositivos:
        mac = mac_raw.replace("-", ":").lower()
        if not ip.startswith("192.168.1.") or ip.endswith(".255") or ip.endswith(".0") or mac.startswith("01:00:5e"):
            continue
        if mac not in whitelist and mac not in alertados:
            alertados.add(mac)
            with open(MEMORIA_FILE, "a") as f:
                f.write(f"{mac}\n")
            threading.Thread(target=lambda: enviar_alerta_telegram(ip, mac, obtener_fabricante(mac))).start()

# --- ARRANQUE ---
if __name__ == "__main__":
    codigo = generar_codigo()
    registrar_codigo_en_nube(codigo)
    
    print("========================================")
    print(f"🔑 TU CÓDIGO DE VINCULACIÓN: {codigo}")
    print("Ingresa este código en nuestra página web.")
    print("========================================")
    
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    print("Vigilante activo y esperando vinculación...")
    
    while True:
        if verificar_acceso():
            escanear_red()
        else:
            print("Acceso denegado: suscripción vencida.")
        time.sleep(30)