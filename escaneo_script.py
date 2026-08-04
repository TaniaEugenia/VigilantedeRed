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

# --- ESCANEO OPTIMIZADO SOBRE DISPOSITIVOS_DETECTADOS ---
def escanear_red(codigo):
    try:
        # 1. Obtener interfaz local y armar rango /24
        ip_local = get_if_addr(conf.iface)
        rango_red = re.sub(r'\.\d+$', '.0/24', ip_local)
        
        # 2. Transmitir paquete ARP
        paquete = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=rango_red)
        resultado, _ = srp(paquete, timeout=2, verbose=False)
        
        # Referencia al usuario en Firebase
        ref_usuario = db.reference(f'usuarios/{codigo}')
        
        # Lectura de los datos actuales
        datos_usuario = ref_usuario.get() or {}
        chat_id_usuario = datos_usuario.get('chat_id')
        dispositivos_actuales = datos_usuario.get('dispositivos_detectados', {})
        
        # MACs detectadas en la ráfaga actual
        macs_detectadas_hoy = set()
        
        for enviado, recibido in resultado:
            ip = recibido.psrc
            mac_raw = recibido.hwsrc
            mac_key = mac_raw.replace(":", "_").lower()
            macs_detectadas_hoy.add(mac_key)
            
            # CASO A: Dispositivo ya existente en el nodo
            if mac_key in dispositivos_actuales:
                disp_info = dispositivos_actuales[mac_key]
                alerta_previa = disp_info.get('alerta_enviada', False)
                segundo_aviso = disp_info.get('segundo_aviso_enviado', False)
                
                # Actualizamos la IP y estado activo, preservando los flags y el chat_id
                ref_usuario.child(f'dispositivos_detectados/{mac_key}').update({
                    'ip': ip,
                    'activo': True,
                    'chat_id': chat_id_usuario,
                    'alerta_enviada': alerta_previa,
                    'segundo_aviso_enviado': segundo_aviso
                })
            
            # CASO B: Dispositivo totalmente NUEVO / Intruso potencial
            else:
                ref_usuario.child(f'dispositivos_detectados/{mac_key}').set({
                    'ip': ip,
                    'mac': mac_raw,
                    'fabricante': obtener_fabricante(mac_raw),
                    'activo': True,
                    'alerta_enviada': False,
                    'segundo_aviso_enviado': False,
                    'es_intruso': True,
                    'chat_id': chat_id_usuario,
                    'timestamp': time.time()
                })

        # --- LIMPIEZA DE INTRUSOS DESCONECTADOS ---
        # Solo se eliminan los dispositivos NO bautizados (intrusos) que ya no respondan al ARP
        for mac_k, datos in list(dispositivos_actuales.items()):
            if mac_k not in macs_detectadas_hoy and datos.get('es_intruso', True):
                ref_usuario.child(f'dispositivos_detectados/{mac_k}').delete()

    except Exception as e:
        print(f"❌ Error en escaneo Npcap: {e}")

# --- BUCLE DE EJECUCIÓN CONTINUA ---
def iniciar_monitoreo(codigo, intervalo_segundos=30):
    print(f"🚀 Monitoreo activo para el usuario: {codigo} (Intervalo: {intervalo_segundos}s)")
    while True:
        escanear_red(codigo)
        time.sleep(intervalo_segundos)