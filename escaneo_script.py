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

# --- ESCANEO OPTIMIZADO CON SEPARACIÓN DE NODOS ---
def escanear_red(codigo):
    try:
        # 1. Obtener interfaz local y armar rango /24
        ip_local = get_if_addr(conf.iface)
        rango_red = re.sub(r'\.\d+$', '.0/24', ip_local)
        
        # 2. Transmitir paquete ARP
        paquete = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=rango_red)
        resultado, _ = srp(paquete, timeout=2, verbose=False)
        
        # Referencias en Firebase
        ref_usuario = db.reference(f'usuarios/{codigo}')
        ref_registrados = ref_usuario.child('dispositivos_registrados')
        ref_intrusos = ref_usuario.child('intrusos')
        
        # Leemos los datos actuales
        registrados_actuales = ref_registrados.get() or {}
        intrusos_actuales = ref_intrusos.get() or {}
        
        # MACs detectadas en la ráfaga actual
        macs_detectadas_hoy = set()
        
        for enviado, recibido in resultado:
            ip = recibido.psrc
            mac_raw = recibido.hwsrc
            mac_key = mac_raw.replace(":", "_").lower()
            macs_detectadas_hoy.add(mac_key)
            
            # CASO A: Es un dispositivo registrado/bautizado
            if mac_key in registrados_actuales:
                # Solo actualizamos la IP por si cambió en el DHCP, sin tocar alertas
                ref_registrados.child(f"{mac_key}/ip").set(ip)
            
            # CASO B: Es un dispositivo no registrado (Intruso potencial)
            else:
                if mac_key in intrusos_actuales:
                    # Ya estaba como intruso: preservamos 'alerta_enviada' para NO re-notificar
                    alerta_previa = intrusos_actuales[mac_key].get('alerta_enviada', False)
                    ref_intrusos.child(mac_key).update({
                        'ip': ip,
                        'activo': True,
                        'alerta_enviada': alerta_previa
                    })
                else:
                    # Intruso totalmente NUEVO: creamos el registro con alerta_enviada = False
                    ref_intrusos.child(mac_key).set({
                        'ip': ip,
                        'mac': mac_raw,
                        'fabricante': obtener_fabricante(mac_raw),
                        'activo': True,
                        'alerta_enviada': False,
                        'timestamp': time.time()
                    })

        # --- LIMPIEZA DE INTRUSOS QUE SE DESCONECTARON ---
        # Si un intruso ya no responde al escaneo ARP, lo removemos de Firebase
        for mac_k, datos in list(intrusos_actuales.items()):
            if mac_k not in macs_detectadas_hoy:
                ref_intrusos.child(mac_k).delete()

    except Exception as e:
        print(f"❌ Error en escaneo Npcap: {e}")

# --- BUCLE DE EJECUCIÓN CONTINUA ---
def iniciar_monitoreo(codigo, intervalo_segundos=30):
    print(f"🚀 Monitoreo activo para el usuario: {codigo} (Intervalo: {intervalo_segundos}s)")
    while True:
        escanear_red(codigo)
        time.sleep(intervalo_segundos)