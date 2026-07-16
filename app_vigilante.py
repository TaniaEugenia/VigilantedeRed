import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timedelta

# --- 1. CONFIGURACIÓN ---
st.set_page_config(layout="wide", page_title="Vigilante de Red - Panel")

# INICIALIZACIÓN DE FIREBASE (Este es el bloque que debes reemplazar)
if not firebase_admin._apps:
    secrets = st.secrets["FIREBASE"]
    
    # Creamos el diccionario asegurando el formato correcto
    cred_dict = {
        "type": secrets["type"],
        "project_id": secrets["project_id"],
        "private_key_id": secrets["private_key_id"],
        "private_key": secrets["private_key"].replace("\\n", "\n"),
        "client_email": secrets["client_email"],
        "client_id": secrets["client_id"],
        "auth_uri": secrets["auth_uri"],
        "token_uri": secrets["token_uri"],
        "auth_provider_x509_cert_url": secrets["auth_provider_x509_cert_url"],
        "client_x509_cert_url": secrets["client_x509_cert_url"]
    }

# --- 2. LÓGICA DE VALIDACIÓN ---
def obtener_vencimiento(data):
    inicio = datetime.fromisoformat(data.get('fecha_inicio', datetime.now().isoformat()))
    horas_activas = data.get('horas_activas', 24)
    return inicio + timedelta(hours=horas_activas)

# --- 3. PANEL DE CONTROL ---
st.title("🛡️ VIGILANTE DE RED - PANEL DE CONTROL")

codigo_usuario = st.text_input("Ingrese el código VIG-XXXX para monitorear").upper()

if codigo_usuario:
    ref = db.reference(f'usuarios/{codigo_usuario}')
    usuario_data = ref.get()
    
    if usuario_data:
        vencimiento = obtener_vencimiento(usuario_data)
        restante = vencimiento - datetime.now()
        
        # Métricas de estado
        col1, col2 = st.columns(2)
        col1.metric("Estado", "🟢 ACTIVO" if restante.total_seconds() > 0 else "🔴 VENCIDO")
        col2.metric("Tiempo restante", f"{max(0, int(restante.total_seconds() / 3600))} hs")
        
        # Visualización de intrusos (Lo que sube el .exe)
        st.subheader("📋 Estado de la Red")
        dispositivos = usuario_data.get('dispositivos_detectados', {})
        
        if dispositivos:
            for mac, info in dispositivos.items():
                mac_formateada = mac.replace("_", ":")
                if info.get('es_intruso'):
                    st.error(f"🚨 INTRUSO DETECTADO | IP: {info.get('ip')} | MAC: `{mac_formateada}`")
                else:
                    st.success(f"✅ Dispositivo Confiable | MAC: `{mac_formateada}`")
        else:
            st.warning("Esperando reporte del escáner...")
    else:
        st.error("Código no encontrado en el sistema.")

# --- 4. BARRA LATERAL (PAGOS) ---
with st.sidebar:
    st.subheader("Gestión de Acceso")
    st.link_button("Pagar 24hs ($10.000)", "https://mpago.li/2ATXsjE")
    st.link_button("Pagar 30 días ($20.000)", "https://mpago.li/1Kk977E")
    st.divider()
    st.markdown("[📄 Términos y condiciones](https://tu-enlace-a-terminos.com)")