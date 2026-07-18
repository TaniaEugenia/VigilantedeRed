import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timedelta

# --- ESTILO CORREGIDO PARA BOTONES ---
page_bg_img = """
<style>
/* Fondo principal */
[data-testid="stAppViewContainer"] {
    background-image: url("https://images.unsplash.com/photo-1550751827-4bd374c3f58b?ixlib=rb-1.2.1&auto=format&fit=crop&w=1950&q=80");
    background-size: cover;
}

/* Barra lateral */
[data-testid="stSidebar"] {
    background-color: #121212;
}

/* Estilo para los botones (los que están blancos) */
div.stButton > button {
    background-color: #f0f2f6 !important; /* Fondo gris claro */
    color: #000000 !important;           /* Texto NEGRO para que se lea siempre */
    font-weight: bold;
    border-radius: 8px !important;
    border: none !important;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.3); /* Sombra para efecto 3D */
}

/* Efecto al pasar el mouse */
div.stButton > button:hover {
    background-color: #e0e0e0 !important;
    color: #000000 !important;
}

/* Entrada de código */
[data-testid="stTextInput"] > div > div > input {
    background-color: #1e1e1e !important;
    color: white !important;
    border: 1px solid #444 !important;
}

h1, h2, h3, p, label {
    color: white !important;
}
</style>
"""
st.markdown(page_bg_img, unsafe_allow_html=True)

# --- 1. CONFIGURACIÓN ---
st.set_page_config(layout="wide", page_title="Vigilante de Red - Panel")
...

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

# --- 3. PANEL DE CONTROL (MODIFICADO) ---
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
                nombre_dispositivo = info.get('nombre_bautizado', "Dispositivo sin nombre")
                
                # Crear columnas para alinear el estado y el botón
                col1, col2 = st.columns([3, 1])
                
                if info.get('es_intruso'):
                    col1.error(f"🚨 INTRUSO: {nombre_dispositivo} | IP: {info.get('ip')} | MAC: `{mac_formateada}`")
                else:
                    col1.success(f"✅ Confiable: {nombre_dispositivo} | MAC: `{mac_formateada}`")
                
                # Botón para borrar/desbautizar
                if col2.button("🗑️ Borrar", key=f"btn_{mac}"):
                    # Lógica para borrar en Firebase
                    # Si quieres borrar el nombre, usamos .update({None})
                    # Si quieres eliminar el nodo del dispositivo, usaríamos .delete()
                    db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados/{mac}/nombre_bautizado').delete()
                    db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados/{mac}/es_intruso').set(True) # Lo marcamos como intruso para que vuelva a alertar
                    st.rerun() # Refrescamos para mostrar el cambio al instante
        else:
            st.warning("Esperando reporte del escáner en la red...")
    else:
        st.error("Código no encontrado en el sistema.")

# --- 4. BARRA LATERAL (PAGOS) ---
with st.sidebar:
    st.subheader("Gestión de Acceso")
    st.link_button("Pagar 24hs ($10.000)", "https://mpago.li/2ATXsjE")
    st.link_button("Pagar 30 días ($20.000)", "https://mpago.li/1Kk977E")