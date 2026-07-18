import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timedelta

# 1. CONFIGURACIÓN (DEBE SER LO PRIMERO)
st.set_page_config(layout="wide", page_title="Vigilante de Red - Panel")

# --- ESTILO FINAL OSCURO ---
page_bg_img = """
<style>
/* Fondo principal */
[data-testid="stAppViewContainer"] {
    background-image: url("https://i.imgur.com/3YmgikW.png");
    background-size: cover;
}
/* Barra lateral negra */
[data-testid="stSidebar"] {
    background-color: #000000 !important;
}
/* Texto general en blanco */
[data-testid="stSidebar"] *, h1, h2, h3, p, label, .stMarkdown {
    color: white !important;
}
/* Barra de carga de código negra */
[data-testid="stTextInput"] > div > div > input {
    background-color: #000000 !important;
    color: white !important;
    border: 1px solid #444 !important;
}
/* Botones de pago */
.btn-mp {
    background-color: #f0f2f6 !important;
    color: black !important;
    padding: 10px;
    border-radius: 8px;
    text-decoration: none;
    display: block;
    text-align: center;
    font-weight: bold;
    margin-bottom: 10px;
    border: 1px solid #ccc;
}
.btn-mp:hover { background-color: #e0e0e0 !important; }
</style>
"""
st.markdown(page_bg_img, unsafe_allow_html=True)

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

# --- PANEL DE CONTROL ---
st.title("🛡️ VIGILANTE DE RED - PANEL DE CONTROL")
codigo_usuario = st.text_input("Ingrese el código VIG-XXXX para monitorear").upper()

if codigo_usuario:
    ref = db.reference(f'usuarios/{codigo_usuario}')
    usuario_data = ref.get()
    
    if usuario_data:
        st.metric("Estado", "🟢 ACTIVO")
        st.subheader("📋 Estado de la Red")
        dispositivos = usuario_data.get('dispositivos_detectados', {})
        
        if dispositivos:
            for mac, info in dispositivos.items():
                mac_formateada = mac.replace("_", ":")
                nombre = info.get('nombre_bautizado', "Dispositivo sin nombre")
                col1, col2 = st.columns([3, 1])
                if info.get('es_intruso'):
                    col1.error(f"🚨 INTRUSO: {nombre} | IP: {info.get('ip')} | MAC: `{mac_formateada}`")
                else:
                    col1.success(f"✅ Confiable: {nombre} | MAC: `{mac_formateada}`")
                
                if col2.button("🗑️ Borrar", key=f"btn_{mac}"):
                    db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados/{mac}/nombre_bautizado').delete()
                    db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados/{mac}/es_intruso').set(True)
                    st.rerun()
        else:
            st.warning("Esperando reporte del escáner en la red...")
    else:
        st.error("Código no encontrado en el sistema.")

# --- BARRA LATERAL ---
with st.sidebar:
    st.subheader("Gestión de Acceso")
    logo_mp = "https://images.seeklogo.com/logo-png/19/1/mercadopago-logo-png_seeklogo-199533.png"
    st.markdown(f'<a href="https://mpago.li/2ATXsjE" class="btn-mp"><img src="{logo_mp}" width="20" style="vertical-align:middle"> Pagar 24hs ($10.000)</a>', unsafe_allow_html=True)
    st.markdown(f'<a href="https://mpago.li/1Kk977E" class="btn-mp"><img src="{logo_mp}" width="20" style="vertical-align:middle"> Pagar 30 días ($20.000)</a>', unsafe_allow_html=True)