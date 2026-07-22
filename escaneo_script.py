import re
import threading
from scapy.all import Ether, ARP, srp, conf, get_if_addr
from firebase_admin import db

# Función auxiliar para consultar el fabricante según el OUI de la MAC
def obtener_fabricante(mac):
    try:
        # Petición a API pública OUI o tu librería local
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
        
        for enviado, recibido in resultado:
            ip = recibido.psrc
            mac_raw = recibido.hwsrc
            # Normalizamos la MAC para usarla de clave válida en Firebase (ej: 00_11_22_33_44_55)
            mac_key = mac_raw.replace(":", "_").lower()
            
            disp_ref = ref_dispositivos.child(mac_key)
            disp_data = disp_ref.get()
            
            if not disp_data:
                # CASO 1: Dispositivo totalmente nuevo detectado en la red
                info_disp = {
                    'ip': ip,
                    'fabricante': obtener_fabricante(mac_raw),
                    'es_intruso': True,
                    'nombre_bautizado': "",   # Queda vacío a la espera del bautismo
                    'alerta_enviada': False,  # Permite al bot de Telegram saber que debe notificar
                    'tipo': 'Desconocido'
                }
                disp_ref.set(info_disp)
                
            else:
                # CASO 2: Dispositivo ya existente en Firebase
                updates = {'ip': ip} # Mantenemos actualizada la IP dinámica por si cambió
                
                # Si no fue bautizado aún o sigue marcado como intruso, nos aseguramos que mantenga su estado
                if not disp_data.get('nombre_bautizado'):
                    updates['es_intruso'] = True
                else:
                    updates['es_intruso'] = False
                
                disp_ref.update(updates)
                
    except Exception as e:
        print(f"❌ Error en escaneo Npcap: {e}")