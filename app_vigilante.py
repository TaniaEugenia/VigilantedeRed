import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
import datetime
import json
import os

# 1. CONFIGURACIÓN (DEBE SER LO PRIMERO)
st.set_page_config(layout="wide", page_title="Vigilante de Red - Panel")

# --- ESTILO FINAL OSCURO MANTENIDO ---
page_bg_img = """
<style>
[data-testid="stAppViewContainer"] { background-image: url("https://i.imgur.com/3YmgikW.png"); background-size: cover; }
[data-testid="stSidebar"] { background-color: #000000 !important; }
[data-testid="stSidebar"] *, h1, h2, h3, p, label, .stMarkdown { color: white !important; }
[data-testid="stTextInput"] > div > div > input { background-color: #000000 !important; color: white !important; border: 1px solid #444 !important; }
.btn-mp {
    background-color: #333333 !important;
    color: white !important;
    padding: 10px;
    border-radius: 8px;
    text-decoration: none;
    display: block;
    text-align: center;
    font-weight: bold;
    margin-bottom: 10px;
    border: 1px solid #555;
}
.btn-mp:hover { background-color: #444444 !important; }
</style>
"""
st.markdown(page_bg_img, unsafe_allow_html=True)

# INICIALIZACIÓN DE FIREBASE (Segura para producción)
if not firebase_admin._apps:
    try:
        # Intenta primero leer variables de entorno (Ideal para entornos fuera de Streamlit como VS Code/Railway)
        cred_env = os.getenv("FIREBASE_CREDENTIALS")
        if cred_env:
            cred_dict = json.loads(cred_env)
        else:
            # Si no, recurre a st.secrets de Streamlit
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
    except Exception as e:
        st.error(f"Error al inicializar Firebase: {e}")

# =====================================================================
# LÓGICA DE BACKEND REUTILIZABLE (Copiable al 100% para tu app en Visual Studio)
# =====================================================================

def obtener_y_verificar_usuario(codigo):
    """
    Trae los datos de la red y procesa el estado comercial en tiempo real.
    Si detecta expiración, actualiza Firebase automáticamente.
    """
    ref = db.reference(f'usuarios/{codigo}')
    usuario_data = ref.get()
    
    if not usuario_data:
        return None
        
    estado_actual = usuario_data.get('estado', 'activo')
    fecha_venc_str = usuario_data.get('fecha_vencimiento')
    
    # 1. Autocalcular vencimiento inicial de cortesía si no existe
    if not fecha_venc_str and usuario_data.get('fecha_creacion'):
        try:
            fecha_c_str = usuario_data.get('fecha_creacion').split(".")[0]
            fecha_c = datetime.datetime.strptime(fecha_c_str, "%Y-%m-%d %H:%M:%S")
            fecha_venc = fecha_c + datetime.timedelta(hours=24) # 24 horas gratis de prueba
            fecha_venc_str = fecha_venc.strftime("%Y-%m-%d %H:%M:%S")
            ref.update({'fecha_vencimiento': fecha_venc_str})
        except Exception as e:
            print(f"Error parseando fecha_creacion: {e}")
            fecha_venc_str = (datetime.datetime.now() + datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    # 2. Verificar si la licencia expiró en base al tiempo actual
    if fecha_venc_str:
        try:
            fecha_limite = datetime.datetime.strptime(fecha_venc_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
            if datetime.datetime.now() > fecha_limite or estado_actual == 'suspendido':
                if estado_actual != 'suspendido':
                    ref.update({'estado': 'suspendido'})
                usuario_data['estado'] = 'suspendido' # Sincroniza la respuesta local
        except Exception as e:
            print(f"Error verificando tiempos: {e}")
            
    return usuario_data

# =====================================================================
# INTERFAZ GRÁFICA (FRONTEND ACTUAL EN STREAMLIT)
# =====================================================================

st.title("🛡️ VIGILANTE DE RED - PANEL DE CONTROL")
codigo_usuario = st.text_input("Ingrese el código VIG-XXXX para monitorear").upper()

if codigo_usuario:
    # Usamos la función modular reutilizable
    usuario_data = obtener_y_verificar_usuario(codigo_usuario)
    
    if usuario_data:
        estado = usuario_data.get('estado', 'activo')
        fecha_venc = usuario_data.get('fecha_vencimiento', 'No disponible')
        
        # Muestra métricas de estado según su situación comercial
        if estado == 'activo':
            st.metric("Estado del Servicio", "🟢 ACTIVO / PROTEGIDO")
            st.info(f"📅 *Tu suscripción está al día.* Vence el: `{fecha_venc}`")
        else:
            st.metric("Estado del Servicio", "🔴 SUSPENDIDO / VENCIDO")
            st.error(f"⚠️ *El tiempo de protección de tu licencia expiró.* El escaneo automático está pausado. Podés renovar tu plan desde los botones de la barra lateral izquierda.")
            
        st.subheader("📋 Historial de Dispositivos en Red")
        dispositivos = usuario_data.get('dispositivos_detectados', {})
        
        if dispositivos:
            for mac, info in dispositivos.items():
                mac_formateada = mac.replace("_", ":")
                nombre = info.get('nombre_bautizado', "Dispositivo sin nombre")
                
                col1, col2 = st.columns([3, 1])
                
                # Renderizado de condiciones
                if info.get('es_intruso'):
                    col1.error(f"🚨 INTRUSO: {nombre} | IP: {info.get('ip')} | MAC: `{mac_formateada}`")
                else:
                    col1.success(f"✅ Confiable: {nombre} | MAC: `{mac_formateada}`")
                
                # Botón para revocar permisos (Bautismo)
                if col2.button("🗑️ Borrar", key=f"btn_{mac}"):
                    db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados/{mac}/nombre_bautizado').delete()
                    db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados/{mac}/es_intruso').set(True)
                    st.rerun()
        else:
            st.warning("Esperando reporte inicial del escáner instalado en la red local...")
    else:
        st.error("Código no encontrado en el sistema. Verifique los caracteres ingresados.")

# --- BARRA LATERAL (Con tus links reales de Mercado Pago agregados) ---
with st.sidebar:
    st.subheader("Gestión de Acceso")
    logo_mp = "https://images.seeklogo.com/logo-png/19/1/mercadopago-logo-png_seeklogo-199533.png"
    
    # Links definitivos de Mercado Pago
    st.markdown(f'<a href="https://mpago.la/1NqWsQf" target="_blank" class="btn-mp"><img src="{logo_mp}" width="20" style="vertical-align:middle"> Pagar 24hs ($10.000)</a>', unsafe_allow_html=True)
    st.markdown(f'<a href="https://mpago.la/2N8NvtF" target="_blank" class="btn-mp"><img src="{logo_mp}" width="20" style="vertical-align:middle"> Pagar 30 días ($20.000)</a>', unsafe_allow_html=True)