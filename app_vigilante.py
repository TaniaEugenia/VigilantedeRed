import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
import datetime
import json
import os

# 1. CONFIGURACIÓN
st.set_page_config(layout="wide", page_title="Vigilante de Red - Panel")

# ESTILO
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

# 2. INICIALIZACIÓN DE FIREBASE
if not firebase_admin._apps:
    try:
        cred_env = os.getenv("FIREBASE_CREDENTIALS")
        if cred_env:
            cred_dict = json.loads(cred_env)
        else:
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

# 3. LÓGICA DE USUARIO Y SUSCRIPCIÓN
def obtener_y_verificar_usuario(codigo):
    ref = db.reference(f'usuarios/{codigo}')
    usuario_data = ref.get()
    
    if not usuario_data:
        return None
        
    estado_actual = usuario_data.get('estado', 'activo')
    fecha_venc_str = usuario_data.get('fecha_vencimiento')
    
    if not fecha_venc_str and usuario_data.get('fecha_creacion'):
        try:
            fecha_c_str = usuario_data.get('fecha_creacion').split(".")[0]
            fecha_c = datetime.datetime.strptime(fecha_c_str, "%Y-%m-%d %H:%M:%S")
            fecha_venc = fecha_c + datetime.timedelta(hours=24)
            fecha_venc_str = fecha_venc.strftime("%Y-%m-%d %H:%M:%S")
            ref.update({'fecha_vencimiento': fecha_venc_str})
        except Exception as e:
            fecha_venc_str = (datetime.datetime.now() + datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    if fecha_venc_str:
        try:
            fecha_limite = datetime.datetime.strptime(fecha_venc_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
            if datetime.datetime.now() > fecha_limite or estado_actual == 'suspendido':
                if estado_actual != 'suspendido':
                    ref.update({'estado': 'suspendido'})
                usuario_data['estado'] = 'suspendido'
        except Exception as e:
            print(f"Error verificando tiempos: {e}")
            
    return usuario_data

# 4. INTERFAZ GRÁFICA
st.title("🛡️ VIGILANTE DE RED - PANEL DE CONTROL")
codigo_usuario = st.text_input("Ingrese el código VIG-XXXX para monitorear").upper()

if codigo_usuario:
    usuario_data = obtener_y_verificar_usuario(codigo_usuario)
    
    if usuario_data:
        estado = usuario_data.get('estado', 'activo')
        fecha_venc = usuario_data.get('fecha_vencimiento', 'No disponible')
        
        if estado == 'activo':
            st.metric("Estado del Servicio", "🟢 ACTIVO / PROTEGIDO")
            st.info(f"📅 *Tu suscripción está al día.* Vence el: `{fecha_venc}`")
        else:
            st.metric("Estado del Servicio", "🔴 SUSPENDIDO / VENCIDO")
            st.error("⚠️ *El tiempo de protección de tu licencia expiró.* El escaneo automático está pausado.")
            
        st.subheader("📋 Gestión de Dispositivos de Red")
        dispositivos = usuario_data.get('dispositivos_detectados', {})
        
        if dispositivos:
            bautizados = {k: v for k, v in dispositivos.items() if v.get('nombre_bautizado')}
            sin_bautizar = {k: v for k, v in dispositivos.items() if not v.get('nombre_bautizado')}
            
            tab1, tab2 = st.tabs([f"✅ Bautizados ({len(bautizados)})", f"⚠️ Sin Bautizar ({len(sin_bautizar)})"])
            
            # --- SECCIÓN BAUTIZADOS ---
            with tab1:
                if bautizados:
                    for mac, info in bautizados.items():
                        mac_formateada = mac.replace("_", ":")
                        nombre = info.get('nombre_bautizado')
                        
                        col1, col2 = st.columns([3, 1])
                        col1.success(f"🟢 **{nombre}** | IP: `{info.get('ip', 'N/A')}` | MAC: `{mac_formateada}` | Fab: {info.get('fabricante', 'Desconocido')}")
                        
                        if col2.button("🗑️ Revocar / Borrar", key=f"del_{mac}"):
                            # Se elimina el nombre, se marca como intruso y se reinicia el estado de alerta para Telegram
                            disp_ref = db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados/{mac}')
                            disp_ref.child('nombre_bautizado').delete()
                            disp_ref.update({
                                'es_intruso': True,
                                'alerta_enviada': False
                            })
                            st.rerun()
                else:
                    st.info("No hay dispositivos bautizados todavía.")

            # --- SECCIÓN SIN BAUTIZAR ---
            with tab2:
                if sin_bautizar:
                    for mac, info in sin_bautizar.items():
                        mac_formateada = mac.replace("_", ":")
                        
                        col1, col2, col3 = st.columns([2, 2, 1])
                        col1.warning(f"⚠️ MAC: `{mac_formateada}` | IP: `{info.get('ip', 'N/A')}` | Fab: {info.get('fabricante', 'Desconocido')}")
                        
                        nuevo_nombre = col2.text_input("Asignar nombre", key=f"input_{mac}", placeholder="Ej: Smart TV Living")
                        
                        if col3.button("✍️ Bautizar", key=f"bautizar_{mac}"):
                            if nuevo_nombre.strip():
                                db.reference(f'usuarios/{codigo_usuario}/dispositivos_detectados/{mac}').update({
                                    'nombre_bautizado': nuevo_nombre.strip(),
                                    'es_intruso': False
                                })
                                st.rerun()
                            else:
                                st.error("Ingresá un nombre.")
                else:
                    st.info("¡Excelente! Todos los dispositivos detectados están bautizados.")
        else:
            st.warning("Esperando reporte inicial del escáner instalado en la red local...")
    else:
        st.error("Código no encontrado en el sistema. Verifique los caracteres ingresados.")

# 5. BARRA LATERAL
with st.sidebar:
    st.subheader("Gestión de Acceso")
    logo_mp = "https://images.seeklogo.com/logo-png/19/1/mercadopago-logo-png_seeklogo-199533.png"
    st.markdown(f'<a href="https://mpago.la/1NqWsQf" target="_blank" class="btn-mp"><img src="{logo_mp}" width="20" style="vertical-align:middle"> Pagar 24hs ($10.000)</a>', unsafe_allow_html=True)
    st.markdown(f'<a href="https://mpago.la/2N8NvtF" target="_blank" class="btn-mp"><img src="{logo_mp}" width="20" style="vertical-align:middle"> Pagar 30 días ($20.000)</a>', unsafe_allow_html=True)