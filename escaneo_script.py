import re
import threading
import time
from scapy.all import Ether, ARP, srp, conf, get_if_addr
from firebase_admin import db

# Función auxiliar para consultar el fabricante según el OUI de la MAC
def obtener_fabricante(mac):
    try:
        import requests
        res = requests.get(f"https://api.macvendors.com/{mac}", timeout=2)
        if res.status_code == 200:
            return res.text
    except Exception:
        pass
    return "Desconocido"

# --- ESCANEO CON NPCAP ADAPTADO ---
def escanear_red(codigo):
    try:
        # 1. Obtener la interfaz local y armar el rango /24
        ip_local = get_if_addr(conf.iface)
        rango_red = re.sub(r'\.\d+$', '.0/24', ip_local)
        
        # 2. Transmitir paquete ARP
        paquete = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=rango_red)
        resultado, _ = srp(paquete, timeout=2, verbose=False)
        
        ref_dispositivos = db.reference(f'usuarios/{codigo}/dispositivos_detectados')
        
        # Traemos todos los registros actuales de Firebase de una sola vez para fusionar y evitar fantasmas
        registros_actuales = ref_dispositivos.get() or {}
        
        # Armamos el nuevo diccionario limpio que reemplazará la foto actual en Firebase
        nuevo_estado_red = {}

        for enviado, recibido in resultado:
            ip = recibido.psrc
            mac_raw = recibido.hwsrc
            mac_key = mac_raw.replace(":", "_").lower()
            
            # Verificamos si ya existía previamente en la base de datos
            if mac_key in registros_actuales:
                disp_data = registros_actuales[mac_key]
                nombre_bautizado = disp_data.get('nombre_bautizado', "")
                es_intruso = False if nombre_bautizado else True
                
                info_disp = {
                    'ip': ip,
                    'fabricante': disp_data.get('fabricante', obtener_fabricante(mac_raw)),
                    'es_intruso': es_intruso,
                    'nombre_bautizado': nombre_bautizado,
                    'alerta_enviada': disp_data.get('alerta_enviada', False),
                    'tipo': disp_data.get('tipo', 'Desconocido')
                }
            else:
                # Dispositivo totalmente nuevo detectado en la red
                info_disp = {
                    'ip': ip,
                    'fabricante': obtener_fabricante(mac_raw),
                    'es_intruso': True,
                    'nombre_bautizado': "",
                    'alerta_enviada': False,
                    'tipo': 'Desconocido'
                }
            
            # Agregamos al diccionario limpio del ciclo actual
            nuevo_estado_red[mac_key] = info_disp
        
        # --- APLICACIÓN DE LA FOTO ACTUAL (LIMPIEZA DE FANTASMAS Y RESGUARDO DE BAUTIZADOS) ---
        # Pisamos directamente el nodo. Todo lo que no respondió al ARP de este ciclo se borra automáticamente,
        # pero conservamos intactos los nombres de los dispositivos que siguen conectados físicamente.
        ref_dispositivos.set(nuevo_estado_red)
        
    except Exception as e:
        print(f"❌ Error en escaneo Npcap: {e}")

# --- BUCLE DE EJECUCIÓN CONTINUA ---
def iniciar_monitoreo(codigo, intervalo_segundos=30):
    print(f"🚀 Iniciando monitoreo continuo para el usuario: {codigo} (Escaneando cada {intervalo_segundos}s)")
    while True:
        escanear_red(codigo)
        time.sleep(intervalo_segundos)