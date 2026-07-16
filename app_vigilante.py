import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timedelta

# --- 1. CONFIGURACIÓN ---
st.set_page_config(layout="wide", page_title="Vigilante de Red - Panel")

# INICIALIZACIÓN DE FIREBASE
if not firebase_admin._apps:
    secrets = st.secrets["FIREBASE"]
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
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'})

# --- 2. LÓGICA DE VALIDACIÓN ---
def obtener_vencimiento(data):
    # Ajustamos para leer desde la nueva estructura si es necesario
    fecha_inicio_str = data.get('fecha_creacion', datetime.now().isoformat())
    try:
        inicio = datetime.fromisoformat(fecha_inicio_str)
    except:
        inicio = datetime.now()
    return inicio + timedelta(hours=24) # Ajusta según tu lógica de suscripción

# --- 3. PANEL DE CONTROL ---
st.title("🛡️ VIGILANTE DE RED - PANEL DE CONTROL")

codigo_usuario = st.text_input("Ingrese el código VIG-XXXX para monitorear").upper()

if codigo_usuario:
    ref = db.reference(f'usuarios/{codigo_usuario}')
    usuario_data = ref.get()
    
    if usuario_data:
        # Métricas de estado
        col1, col2 = st.columns(2)
        col1.metric("Estado", "🟢 ACTIVO")
        col2.metric("Red", codigo_usuario)
        
        # Visualización de intrusos
        st.subheader("📋 Estado de la Red")
        # Buscamos en la ruta que usa el .exe: dispositivos_detectados
        dispositivos = usuario_data.get('dispositivos_detectados', {})
        
        if dispositivos:
            for mac, info in dispositivos.items():
                mac_formateada = mac.replace("_", ":")
                if info.get('es_intruso'):
                    st.error(f"🚨 INTRUSO DETECTADO | IP: {info.get('ip')} | MAC: `{mac_formateada}`")
                else:
                    st.success(f"✅ Dispositivo Confiable | MAC: `{mac_formateada}`")
        else:
            st.warning("Esperando reporte del escáner en la red...")
    else:
        st.error("Código no encontrado en el sistema.")

# --- 4. BARRA LATERAL (PAGOS) ---
with st.sidebar:
    st.subheader("Gestión de Acceso")
    st.link_button("Pagar 24hs ($10.000)", "https://mpago.li/2ATXsjE")
    st.link_button("Pagar 30 días ($20.000)", "https://mpago.li/1Kk977E")