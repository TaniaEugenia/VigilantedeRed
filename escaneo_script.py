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
        
        # Recopilamos todas las MACs que respondieron activamente al ARP en este ciclo
        macs_vivas_en_red = set()

        for enviado, recibido in resultado:
            ip = recibido.psrc
            mac_raw = recibido.hwsrc
            mac_key = mac_raw.replace(":", "_").lower()
            macs_vivas_en_red.add(mac_key)
            
            disp_ref = ref_dispositivos.child(mac_key)
            disp_data = disp_ref.get()
            
            if not disp_data:
                # CASO 1: Dispositivo totalmente nuevo detectado en la red
                info_disp = {
                    'ip': ip,
                    'fabricante': obtener_fabricante(mac_raw),
                    'es_intruso': True,
                    'nombre_bautizado': "",
                    'alerta_enviada': False,
                    'tipo': 'Desconocido'
                }
                disp_ref.set(info_disp)
            else:
                # CASO 2: Dispositivo ya existente en Firebase
                updates = {'ip': ip}
                
                if not disp_data.get('nombre_bautizado'):
                    updates['es_intruso'] = True
                else:
                    updates['es_intruso'] = False
                
                disp_ref.update(updates)
        
        # --- LIMPIEZA DE DISPOSITIVOS FANTASMAS ---
        # Verificamos los registros guardados en Firebase que NO respondieron al ARP actual
        todos_registrados = ref_dispositivos.get()
        if todos_registrados:
            for mac_key_registrada in todos_registrados.keys():
                # Si un equipo está en Firebase pero NO apareció en el escaneo ARP actual,
                # significa que ya no está activo en la red local y se elimina para evitar "fantasmas".
                if mac_key_registrada not in macs_vivas_en_red:
                    ref_dispositivos.child(mac_key_registrada).delete()
                
    except Exception as e:
        print(f"❌ Error en escaneo Npcap: {e}")

# --- BUCLE DE EJECUCIÓN CONTINUA ---
def iniciar_monitoreo(codigo, intervalo_segundos=30):
    print(f"🚀 Iniciando monitoreo continuo para el usuario: {codigo} (Escaneando cada {intervalo_segundos}s)")
    while True:
        escanear_red(codigo)
        time.sleep(intervalo_segundos)