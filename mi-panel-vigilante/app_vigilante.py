from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, db
import datetime
import json
import os

app = Flask(__name__, static_folder='.')
CORS(app)

# --- INICIALIZACIÓN DE FIREBASE ---
if not firebase_admin._apps:
    try:
        cred_env = os.getenv("FIREBASE_CREDENTIALS")
        if cred_env:
            cred_dict = json.loads(cred_env)
            cred = credentials.Certificate(cred_dict)
        else:
            secret_path = "/etc/secrets/firebase_keys.json"
            local_path = "firebase_keys.json"
            
            path_to_use = secret_path if os.path.exists(secret_path) else local_path
            
            with open(path_to_use, "r") as f:
                cred_dict = json.load(f)
            cred = credentials.Certificate(cred_dict)

        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://vigilante-de-red-default-rtdb.firebaseio.com/'
        })
    except Exception as e:
        print(f"Error al inicializar Firebase: {e}")
        
# --- LÓGICA DE USUARIO ---
def obtener_y_verificar_usuario(codigo):
    ref = db.reference(f'usuarios/{codigo}')
    usuario_data = ref.get()
    
    # Si el código no existe en la base de datos, retornamos None limpiamente
    if not usuario_data or not isinstance(usuario_data, dict):
        return None
        
    estado_actual = usuario_data.get('estado', 'activo')
    fecha_venc_str = usuario_data.get('fecha_vencimiento')
    
    if not fecha_venc_str and usuario_data.get('fecha_creacion'):
        try:
            fecha_c_str = str(usuario_data.get('fecha_creacion')).split(".")[0]
            fecha_c = datetime.datetime.strptime(fecha_c_str, "%Y-%m-%d %H:%M:%S")
            fecha_venc = fecha_c + datetime.timedelta(hours=24)
            fecha_venc_str = fecha_venc.strftime("%Y-%m-%d %H:%M:%S")
            ref.update({'fecha_vencimiento': fecha_venc_str})
        except Exception:
            fecha_venc_str = (datetime.datetime.now() + datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    if fecha_venc_str:
        try:
            fecha_limite = datetime.datetime.strptime(str(fecha_venc_str).split(".")[0], "%Y-%m-%d %H:%M:%S")
            if datetime.datetime.now() > fecha_limite or estado_actual == 'suspendido':
                if estado_actual != 'suspendido':
                    ref.update({'estado': 'suspendido'})
                usuario_data['estado'] = 'suspendido'
        except Exception as e:
            print(f"Error verificando tiempos: {e}")
            
    if 'dispositivos_detectados' not in usuario_data or not isinstance(usuario_data['dispositivos_detectados'], dict):
        usuario_data['dispositivos_detectados'] = {}
            
    return usuario_data

# --- RUTAS DE LA API ---
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/api/usuario/<codigo>', methods=['GET'])
def get_usuario(codigo):
    data = obtener_y_verificar_usuario(codigo.upper())
    if data:
        return jsonify({"success": True, "data": data})
    return jsonify({"success": False, "message": "Código no encontrado"}), 404

@app.route('/api/bautizar', methods=['POST'])
def bautizar():
    payload = request.json
    codigo = payload.get('codigo')
    mac = payload.get('mac')
    nombre = payload.get('nombre')
    
    if codigo and mac and nombre:
        db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}').update({
            'nombre_bautizado': nombre.strip(),
            'es_intruso': False
        })
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Datos incompletos"}), 400

@app.route('/api/revocar', methods=['POST'])
def revocar():
    payload = request.json
    codigo = payload.get('codigo')
    mac = payload.get('mac')
    
    if codigo and mac:
        disp_ref = db.reference(f'usuarios/{codigo}/dispositivos_detectados/{mac}')
        disp_ref.child('nombre_bautizado').delete()
        disp_ref.update({
            'es_intruso': True,
            'alerta_enviada': False
        })
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Datos incompletos"}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)