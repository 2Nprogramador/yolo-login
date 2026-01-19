import streamlit as st
import cv2
import numpy as np
import os
import tempfile
import time
import hashlib
import json 
import datetime
import requests

# --- BIBLIOTECA DE COOKIES ---
import extra_streamlit_components as stx

# --- GOOGLE SHEETS ---
import gspread
from google.oauth2.service_account import Credentials

from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import mediapipe as mp

# ==========================================
# 0. CONFIGURAÇÃO DA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Treino Completo AI", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# ==========================================
# 1. GERENCIADOR DE COOKIES
# ==========================================
def get_manager():
    return stx.CookieManager()

cookie_manager = get_manager()

# ==========================================
# 2. SISTEMA DE LOGIN E BANCO DE DADOS
# ==========================================

def conectar_gsheets():
    scope = ['https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = dict(st.secrets["google_sheets_credentials"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(credentials)
        return client.open("usuarios_app").sheet1
    except Exception as e:
        st.error(f"Erro no Google Sheets: {e}")
        return None

def hash_senha(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

# --- FUNÇÕES PARA SALVAR/CARREGAR CONFIGURAÇÕES ---

def salvar_config_usuario(username, config_dict):
    sheet = conectar_gsheets()
    if sheet:
        try:
            cell = sheet.find(username, in_column=1)
            if cell:
                config_json = json.dumps(config_dict)
                sheet.update_cell(cell.row, 4, config_json)
                st.toast("✅ Configurações salvas na nuvem!", icon="☁️")
            else:
                st.error("Usuário não encontrado.")
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")

def carregar_config_usuario(username):
    sheet = conectar_gsheets()
    if sheet:
        try:
            cell = sheet.find(username, in_column=1)
            if cell:
                config_json = sheet.cell(cell.row, 4).value
                if config_json and len(config_json) > 2:
                    return json.loads(config_json)
        except Exception as e:
            pass 
    return {}

# --- LÓGICA DE LOGIN COM COOKIE ---

cookie_user = cookie_manager.get(cookie="user_treino_ai")

if 'logged_in' not in st.session_state:
    if cookie_user:
        st.session_state['logged_in'] = True
        st.session_state['username'] = cookie_user
        st.session_state['user_name'] = cookie_user 
        
        saved_configs = carregar_config_usuario(cookie_user)
        st.session_state['user_configs'] = saved_configs if saved_configs else {}
    else:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ""
        st.session_state['user_configs'] = {}

# --- TELA DE LOGIN ---

def login_page():
    st.markdown("<h1 style='text-align: center;'>🔒 Login AI Fitness</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    
    with col2:
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        
        c1, c2 = st.columns(2)
        if c1.button("Entrar", type="primary", use_container_width=True):
            sheet = conectar_gsheets()
            if sheet:
                try:
                    records = sheet.get_all_records()
                    user_found = False
                    for user in records:
                        if str(user['username']) == username and str(user['password']) == hash_senha(password):
                            
                            st.session_state['logged_in'] = True
                            st.session_state['user_name'] = user.get('name', username)
                            st.session_state['username'] = username
                            
                            saved_configs = carregar_config_usuario(username)
                            st.session_state['user_configs'] = saved_configs if saved_configs else {}
                            
                            cookie_manager.set("user_treino_ai", username, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
                                
                            st.success("Logado!")
                            time.sleep(1)
                            st.rerun()
                            user_found = True
                            break
                    if not user_found: st.error("Dados incorretos.")
                except Exception as e: st.error(f"Erro: {e}")

        if c2.button("Criar Conta", use_container_width=True):
            if username and password:
                sheet = conectar_gsheets()
                if sheet:
                    records = sheet.get_all_records()
                    users = [str(r['username']) for r in records]
                    if username in users:
                        st.warning("Usuário já existe.")
                    else:
                        sheet.append_row([username, hash_senha(password), username, "{}"])
                        st.success("Criado! Faça login.")
            else: st.warning("Preencha tudo.")

if not st.session_state['logged_in']:
    login_page()
    st.stop()

# ==========================================
# 3. APLICAÇÃO PRINCIPAL
# ==========================================

st.sidebar.write(f"Olá, **{st.session_state.get('username', 'Atleta')}** 👋")

if st.sidebar.button("Sair"):
    st.session_state['logged_in'] = False
    st.session_state['user_configs'] = {}
    cookie_manager.delete("user_treino_ai")
    st.rerun()

st.title("Análise de Exercícios com Visão Computacional")

# ==========================================
# 4. CONSTANTES (FÍSICA)
# ==========================================
MOVEMENT_CONSTANTS = {
    "Agachamento Búlgaro": { "stages": {"UP": "EM PE", "DOWN": "AGACHAMENTO OK", "TRANSITION": "DESCENDO"} },
    "Agachamento Padrão": { "stages": {"UP": "EM PE", "DOWN": "AGACHAMENTO OK", "TRANSITION": "DESCENDO"} },
    "Supino Máquina": { "stages": {"UP": "BRACO ESTICADO", "DOWN": "NA BASE", "TRANSITION": "EMPURRANDO"} },
    "Flexão de Braço": { "stages": {"UP": "EM CIMA (OK)", "DOWN": "EMBAIXO (OK)", "TRANSITION": "MOVIMENTO"} },
    "Rosca Direta": { "stages": {"UP": "ESTICADO", "DOWN": "CONTRAIDO", "TRANSITION": "EM ACAO"} },
    "Desenvolvimento (Ombro)": { "stages": {"UP": "TOPO (LOCKOUT)", "DOWN": "BASE", "TRANSITION": "MOVIMENTO"} },
    "Afundo (Lunge)": { "stages": {"UP": "DESCENDO", "DOWN": "BOM AFUNDO", "TRANSITION": "DESCENDO"} },
    "Levantamento Terra": { "stages": {"UP": "TOPO (ERETO)", "DOWN": "POSICAO INICIAL", "TRANSITION": "LEVANTANDO"} },
    "Prancha (Plank)": { "stages": {"UP": "QUADRIL ALTO", "DOWN": "QUADRIL CAINDO", "TRANSITION": "PERFEITO"} },
    "Abdominal (Crunch)": { "stages": {"UP": "DEITADO", "DOWN": "CONTRAIDO", "TRANSITION": "MOVIMENTO"} },
    "Elevação Lateral": { "stages": {"UP": "ALTURA CORRETA", "DOWN": "DESCANSO", "TRANSITION": "SUBINDO"} }
}

# ==========================================
# 5. FUNÇÕES MATEMÁTICAS E VISUALIZAÇÃO
# ==========================================
def calculate_angle(a, b, c):
    a, b, c = np.array(a), np.array(b), np.array(c)
    radians = np.arctan2(c[1]-b[1], c[0]-b[0]) - np.arctan2(a[1]-b[1], a[0]-b[0])
    angle = np.abs(radians * 180.0 / np.pi)
    if angle > 180.0: angle = 360 - angle
    return angle

def draw_pose_landmarks(frame, landmarks, w, h):
    connections = [(11,13),(13,15),(12,14),(14,16),(11,12),(11,23),(12,24),(23,24),(23,25),(25,27),(24,26),(26,28)]
    for s, e in connections:
        cv2.line(frame, (int(landmarks[s].x*w), int(landmarks[s].y*h)), (int(landmarks[e].x*w), int(landmarks[e].y*h)), (200,200,200), 2)
    for lm in landmarks:
        cv2.circle(frame, (int(lm.x*w), int(lm.y*h)), 4, (0,0,255), -1)

def draw_visual_angle(frame, p1, p2, p3, text, color=(255,255,255), label=""):
    cv2.line(frame, (int(p1[0]),int(p1[1])), (int(p2[0]),int(p2[1])), (255,255,255), 2)
    cv2.line(frame, (int(p2[0]),int(p2[1])), (int(p3[0]),int(p3[1])), (255,255,255), 2)
    cv2.circle(frame, (int(p2[0]),int(p2[1])), 6, color, -1)
    display = f"{label}: {text}" if label else text
    cv2.putText(frame, display, (int(p2[0])+15, int(p2[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)

# ==========================================
# 6. SIDEBAR COM LÓGICA DE SALVAR/CARREGAR
# ==========================================

st.sidebar.header("1. Exercício & Configs")
EXERCISE_OPTIONS = list(MOVEMENT_CONSTANTS.keys())

# --- FUNÇÃO DE RESET AUTOMÁTICO ---
def reset_counters():
    st.session_state.counter_total = 0
    st.session_state.counter_ok = 0
    st.session_state.counter_no = 0
    st.session_state.stage = None 
    st.session_state.has_error = False

# Selectbox com callback para zerar ao mudar
exercise_type = st.sidebar.selectbox(
    "Selecionar:", 
    EXERCISE_OPTIONS,
    on_change=reset_counters # Zera ao trocar exercício
)

# --- CONFIGS INICIAIS ---
if 'user_configs' not in st.session_state:
    st.session_state['user_configs'] = {}

def get_val(key, default):
    full_key = f"{exercise_type}_{key}"
    return st.session_state['user_configs'].get(full_key, default)

user_thresholds = {} 

# --- ESTADOS DO CONTADOR ---
if "counter_total" not in st.session_state: st.session_state.counter_total = 0
if "counter_ok" not in st.session_state: st.session_state.counter_ok = 0
if "counter_no" not in st.session_state: st.session_state.counter_no = 0
if "stage" not in st.session_state: st.session_state.stage = None 
if "has_error" not in st.session_state: st.session_state.has_error = False

# --- EXIBIÇÃO DE PLACAR NA SIDEBAR (CONTAINER ÚNICO) ---
st.sidebar.markdown("### 📊 Placar Atual")
placar_placeholder = st.sidebar.empty() # Container único

# Função para atualizar o placar
def update_sidebar_metrics():
    with placar_placeholder.container():
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", st.session_state.counter_total)
        c2.metric("✅", st.session_state.counter_ok)
        c3.metric("❌", st.session_state.counter_no)

# Renderiza o estado inicial
update_sidebar_metrics()

st.sidebar.markdown("---")

def render_movement_header():
    st.sidebar.markdown("### 📏 Estado do Movimento")
def render_safety_header():
    st.sidebar.markdown("### 🛡️ Segurança")

# --- WIDGETS DINÂMICOS ---

if exercise_type == "Agachamento Búlgaro":
    render_movement_header()
    user_thresholds['knee_min'] = st.sidebar.number_input("Ângulo Baixo", value=get_val('knee_min', 75), key=f"{exercise_type}_knee_min")
    user_thresholds['knee_max'] = st.sidebar.number_input("Ângulo Alto", value=get_val('knee_max', 160), key=f"{exercise_type}_knee_max")
    render_safety_header()
    check = st.sidebar.checkbox("Alerta Tronco", value=get_val('check_torso', True), key=f"{exercise_type}_check_torso")
    user_thresholds['check_torso'] = check
    if check:
        user_thresholds['torso_limit'] = st.sidebar.slider("Limite Tronco", 50, 90, value=get_val('torso_limit', 70), key=f"{exercise_type}_torso_limit")

elif exercise_type == "Agachamento Padrão":
    render_movement_header()
    user_thresholds['stand_max'] = st.sidebar.slider("Limite Em Pé", 0, 40, value=get_val('stand_max', 32), key=f"{exercise_type}_stand_max")
    user_thresholds['pass_min'] = st.sidebar.slider("Limite Agachado", 70, 110, value=get_val('pass_min', 80), key=f"{exercise_type}_pass_min")

elif exercise_type == "Supino Máquina":
    render_movement_header()
    user_thresholds['extended_min'] = st.sidebar.slider("Braço Esticado", 140, 180, value=get_val('extended_min', 160), key=f"{exercise_type}_extended_min")
    user_thresholds['flexed_max'] = st.sidebar.slider("Braço Base", 40, 100, value=get_val('flexed_max', 80), key=f"{exercise_type}_flexed_max")
    render_safety_header()
    check = st.sidebar.checkbox("Alerta Cotovelo", value=get_val('check_safety', True), key=f"{exercise_type}_check_safety")
    user_thresholds['check_safety'] = check
    if check:
        user_thresholds['safety_limit'] = st.sidebar.slider("Limite Abertura", 60, 90, value=get_val('safety_limit', 80), key=f"{exercise_type}_safety_limit")

elif exercise_type == "Flexão de Braço":
    render_movement_header()
    user_thresholds['pu_down'] = st.sidebar.slider("Ângulo Baixo", 60, 100, value=get_val('pu_down', 90), key=f"{exercise_type}_pu_down")
    user_thresholds['pu_up'] = st.sidebar.slider("Ângulo Alto", 150, 180, value=get_val('pu_up', 165), key=f"{exercise_type}_pu_up")

elif exercise_type == "Rosca Direta":
    render_movement_header()
    user_thresholds['bc_flex'] = st.sidebar.slider("Contração Máx", 30, 60, value=get_val('bc_flex', 45), key=f"{exercise_type}_bc_flex")
    user_thresholds['bc_ext'] = st.sidebar.slider("Extensão Total", 140, 180, value=get_val('bc_ext', 160), key=f"{exercise_type}_bc_ext")

elif exercise_type == "Desenvolvimento (Ombro)":
    render_movement_header()
    user_thresholds['sp_up'] = st.sidebar.slider("Lockout", 150, 180, value=get_val('sp_up', 165), key=f"{exercise_type}_sp_up")
    user_thresholds['sp_down'] = st.sidebar.slider("Base", 60, 100, value=get_val('sp_down', 80), key=f"{exercise_type}_sp_down")

elif exercise_type == "Afundo (Lunge)":
    render_movement_header()
    user_thresholds['lg_knee'] = st.sidebar.slider("Profundidade", 70, 110, value=get_val('lg_knee', 90), key=f"{exercise_type}_lg_knee")
    render_safety_header()
    check = st.sidebar.checkbox("Alerta Tronco", value=get_val('check_torso', True), key=f"{exercise_type}_check_torso")
    user_thresholds['check_torso'] = check
    if check:
        user_thresholds['lg_torso'] = st.sidebar.slider("Inclinação Mínima", 70, 90, value=get_val('lg_torso', 80), key=f"{exercise_type}_lg_torso")

elif exercise_type == "Levantamento Terra":
    render_movement_header()
    user_thresholds['dl_hip'] = st.sidebar.slider("Extensão Final", 160, 180, value=get_val('dl_hip', 170), key=f"{exercise_type}_dl_hip")
    user_thresholds['dl_back'] = st.sidebar.slider("Limite Costas", 40, 90, value=get_val('dl_back', 60), key=f"{exercise_type}_dl_back")

elif exercise_type == "Prancha (Plank)":
    render_movement_header()
    user_thresholds['pk_min'] = st.sidebar.slider("Mínimo (Cair)", 150, 175, value=get_val('pk_min', 165), key=f"{exercise_type}_pk_min")
    user_thresholds['pk_max'] = st.sidebar.slider("Máximo (Empinar)", 175, 190, value=get_val('pk_max', 185), key=f"{exercise_type}_pk_max")

elif exercise_type == "Abdominal (Crunch)":
    render_movement_header()
    user_thresholds['cr_flex'] = st.sidebar.slider("Contração", 40, 100, value=get_val('cr_flex', 70), key=f"{exercise_type}_cr_flex")
    user_thresholds['cr_ext'] = st.sidebar.slider("Retorno", 110, 150, value=get_val('cr_ext', 130), key=f"{exercise_type}_cr_ext")

elif exercise_type == "Elevação Lateral":
    render_movement_header()
    user_thresholds['lr_height'] = st.sidebar.slider("Topo (Ombro)", 70, 100, value=get_val('lr_height', 85), key=f"{exercise_type}_lr_height")
    user_thresholds['lr_low'] = st.sidebar.slider("Baixo (Descanso)", 10, 30, value=get_val('lr_low', 20), key=f"{exercise_type}_lr_low")

# --- LÓGICA DE SALVAR ---
st.sidebar.markdown("---")
if st.sidebar.button("💾 Salvar Minhas Configs", type="primary", use_container_width=True):
    for key, value in user_thresholds.items():
        st.session_state['user_configs'][f"{exercise_type}_{key}"] = value
    salvar_config_usuario(st.session_state['username'], st.session_state['user_configs'])

# ==========================================
# 7. UPLOAD E PROCESSAMENTO
# ==========================================
st.sidebar.markdown("---")
# Adicionamos on_change para zerar ao trocar arquivo
def on_upload_change():
    reset_counters()

uploaded_file = st.sidebar.file_uploader(
    "3. Carregar Vídeo", 
    type=["mp4", "mov", "avi", "webm"],
    on_change=on_upload_change
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "pose_landmarker_lite.task")
OUTPUT_PATH = os.path.join(BASE_DIR, "output_final.webm")

video_path = None
if uploaded_file:
    tfile = tempfile.NamedTemporaryFile(delete=False) 
    tfile.write(uploaded_file.read())
    video_path = tfile.name
else:
    default = os.path.join(BASE_DIR, "gravando4.mp4")
    if os.path.exists(default): video_path = default

if "last_state" not in st.session_state: st.session_state.last_state = "INICIO"

run_btn = st.sidebar.button("⚙️ PROCESSAR VÍDEO")

# --- FUNÇÃO DE SEGURANÇA: BAIXA MODELO ---
def download_model_if_missing(model_path):
    url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    if not os.path.exists(model_path) or os.path.getsize(model_path) < 1000000:
        with st.spinner("Baixando modelo de IA (Correção automática)..."):
            try:
                response = requests.get(url)
                if response.status_code == 200:
                    with open(model_path, 'wb') as f:
                        f.write(response.content)
                    return True
            except:
                st.error("Erro ao baixar modelo.")
                return False
    return True

if run_btn and video_path:
    # Reset para garantir frescor
    reset_counters()
    update_sidebar_metrics() # Limpa visualmente o placar
    
    if not download_model_if_missing(MODEL_PATH):
        st.stop()

    try:
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options, 
            running_mode=vision.RunningMode.VIDEO,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )
        detector = vision.PoseLandmarker.create_from_options(options)

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width_orig = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        target_width = 640
        scale = target_width / width_orig
        target_height = int(int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) * scale)

        fourcc = cv2.VideoWriter_fourcc(*'vp80') 
        out = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps, (target_width, target_height))

        progress = st.progress(0)
        status = st.empty()
        timestamp_ms = 0
        frames_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_idx = 0
        CONSTANTS = MOVEMENT_CONSTANTS[exercise_type]

        # Define lógica de contagem
        COUNT_ON_RETURN_TO = CONSTANTS['stages']['UP'] # Padrão
        if exercise_type == "Elevação Lateral":
            COUNT_ON_RETURN_TO = CONSTANTS['stages']['DOWN']

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break

            frame = cv2.resize(frame, (target_width, target_height))
            h, w, _ = frame.shape
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = detector.detect_for_video(mp_image, int(timestamp_ms))
            timestamp_ms += (1000.0 / fps)

            # --- Variáveis Locais ---
            current_state = st.session_state.last_state
            main_angle_display = 0
            alert_msg = ""
            vis_p1, vis_p2, vis_p3 = None, None, None
            label_angle = "" 

            if result.pose_landmarks:
                lm = result.pose_landmarks[0]
                draw_pose_landmarks(frame, lm, w, h)
                def get_pt(idx): return [lm[idx].x * w, lm[idx].y * h]
                sh_l, hip_l, knee_l, ank_l = get_pt(11), get_pt(23), get_pt(25), get_pt(27)
                elb_l, wr_l = get_pt(13), get_pt(15)

                # --- LÓGICA DO PROCESSAMENTO ---
                if exercise_type == "Agachamento Búlgaro":
                    if lm[27].y > lm[28].y: s_idx, h_idx, k_idx, a_idx = 11, 23, 25, 27
                    else: s_idx, h_idx, k_idx, a_idx = 12, 24, 26, 28
                    p_sh, p_hip, p_knee, p_ank = get_pt(s_idx), get_pt(h_idx), get_pt(k_idx), get_pt(a_idx)
                    knee_angle = calculate_angle(p_hip, p_knee, p_ank)
                    main_angle_display = knee_angle; vis_p1,vis_p2,vis_p3 = p_hip,p_knee,p_ank; label_angle = "Joelho"
                    
                    if knee_angle > user_thresholds['knee_max']: current_state = CONSTANTS['stages']['UP']
                    elif user_thresholds['knee_min'] <= knee_angle <= user_thresholds['knee_max']: current_state = CONSTANTS['stages']['TRANSITION']
                    elif knee_angle < user_thresholds['knee_min']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    
                    if user_thresholds.get('check_torso'):
                        torso_angle = calculate_angle(p_sh, p_hip, p_knee)
                        if torso_angle < user_thresholds.get('torso_limit', 70): alert_msg = "TRONCO INCLINADO"; st.session_state.has_error = True

                elif exercise_type == "Agachamento Padrão":
                    vertical_ref = [knee_l[0], knee_l[1] - 100]
                    femur_angle = calculate_angle(hip_l, knee_l, vertical_ref)
                    main_angle_display = femur_angle; vis_p1,vis_p2,vis_p3 = hip_l,knee_l,vertical_ref; label_angle = "Coxa"
                    if femur_angle <= user_thresholds['stand_max']: current_state = CONSTANTS['stages']['UP']
                    elif user_thresholds['stand_max'] < femur_angle < user_thresholds['pass_min']: current_state = CONSTANTS['stages']['TRANSITION']
                    elif femur_angle >= user_thresholds['pass_min']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"

                elif exercise_type == "Supino Máquina":
                    elbow_angle = calculate_angle(sh_l, elb_l, wr_l)
                    main_angle_display = elbow_angle; vis_p1,vis_p2,vis_p3 = sh_l,elb_l,wr_l; label_angle = "Cotovelo"
                    if elbow_angle >= user_thresholds['extended_min']: current_state = CONSTANTS['stages']['UP']
                    elif elbow_angle <= user_thresholds['flexed_max']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    else: current_state = CONSTANTS['stages']['TRANSITION']
                    if user_thresholds.get('check_safety'):
                        abduction_angle = calculate_angle(hip_l, sh_l, elb_l)
                        if abduction_angle > user_thresholds.get('safety_limit', 80): alert_msg = "COTOVELOS ABERTOS!"; st.session_state.has_error = True

                elif exercise_type == "Flexão de Braço":
                    angle_elb = calculate_angle(sh_l, elb_l, wr_l)
                    main_angle_display = angle_elb; vis_p1,vis_p2,vis_p3 = sh_l,elb_l,wr_l; label_angle = "Cotovelo"
                    if angle_elb < user_thresholds['pu_down']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    elif angle_elb > user_thresholds['pu_up']: current_state = CONSTANTS['stages']['UP']
                    else: current_state = CONSTANTS['stages']['TRANSITION']

                elif exercise_type == "Rosca Direta":
                    angle_elb = calculate_angle(sh_l, elb_l, wr_l)
                    main_angle_display = angle_elb; vis_p1,vis_p2,vis_p3 = sh_l,elb_l,wr_l; label_angle = "Biceps"
                    if angle_elb < user_thresholds['bc_flex']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    elif angle_elb > user_thresholds['bc_ext']: current_state = CONSTANTS['stages']['UP']
                    else: current_state = CONSTANTS['stages']['TRANSITION']

                elif exercise_type == "Desenvolvimento (Ombro)":
                    angle_elb = calculate_angle(sh_l, elb_l, wr_l)
                    main_angle_display = angle_elb; vis_p1,vis_p2,vis_p3 = sh_l,elb_l,wr_l
                    if angle_elb > user_thresholds['sp_up']: current_state = CONSTANTS['stages']['UP']
                    elif angle_elb < user_thresholds['sp_down']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    else: current_state = CONSTANTS['stages']['TRANSITION']

                elif exercise_type == "Afundo (Lunge)":
                    angle_knee = calculate_angle(hip_l, knee_l, ank_l)
                    main_angle_display = angle_knee; vis_p1,vis_p2,vis_p3 = hip_l,knee_l,ank_l; label_angle = "Joelho"
                    if angle_knee <= user_thresholds['lg_knee']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    else: current_state = CONSTANTS['stages']['UP']
                    if user_thresholds.get('check_torso'):
                        angle_torso = calculate_angle(sh_l, hip_l, knee_l)
                        if angle_torso < user_thresholds.get('lg_torso', 80): alert_msg = "POSTURA RUIM"; st.session_state.has_error = True

                elif exercise_type == "Levantamento Terra":
                    angle_hip = calculate_angle(sh_l, hip_l, knee_l)
                    main_angle_display = angle_hip; vis_p1,vis_p2,vis_p3 = sh_l,hip_l,knee_l; label_angle = "Quadril"
                    if angle_hip > user_thresholds['dl_hip']: current_state = CONSTANTS['stages']['UP']
                    elif angle_hip < user_thresholds['dl_back']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    else: current_state = CONSTANTS['stages']['TRANSITION']

                elif exercise_type == "Prancha (Plank)":
                    angle_body = calculate_angle(sh_l, hip_l, ank_l)
                    main_angle_display = angle_body; vis_p1,vis_p2,vis_p3 = sh_l,hip_l,ank_l; label_angle = "Corpo"
                    if user_thresholds['pk_min'] <= angle_body <= user_thresholds['pk_max']: current_state = CONSTANTS['stages']['TRANSITION']
                    elif angle_body < user_thresholds['pk_min']: 
                        current_state = CONSTANTS['stages']['DOWN']; st.session_state.has_error = True
                    else: 
                        current_state = CONSTANTS['stages']['UP']; st.session_state.has_error = True

                elif exercise_type == "Abdominal (Crunch)":
                    angle_crunch = calculate_angle(sh_l, hip_l, knee_l)
                    main_angle_display = angle_crunch; vis_p1,vis_p2,vis_p3 = sh_l,hip_l,knee_l
                    if angle_crunch < user_thresholds['cr_flex']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    elif angle_crunch > user_thresholds['cr_ext']: current_state = CONSTANTS['stages']['UP']
                    else: current_state = CONSTANTS['stages']['TRANSITION']

                elif exercise_type == "Elevação Lateral":
                    angle_abd = calculate_angle(hip_l, sh_l, elb_l)
                    main_angle_display = angle_abd; vis_p1,vis_p2,vis_p3 = hip_l,sh_l,elb_l; label_angle = "Ombro"
                    if angle_abd >= user_thresholds['lr_height']: current_state = CONSTANTS['stages']['UP']; st.session_state.stage = "down"
                    elif angle_abd < user_thresholds['lr_low']: current_state = CONSTANTS['stages']['DOWN']
                    else: current_state = CONSTANTS['stages']['TRANSITION']

                # --- MÁQUINA DE ESTADOS DO CONTADOR ---
                if current_state == COUNT_ON_RETURN_TO and st.session_state.stage == "down":
                    st.session_state.counter_total += 1
                    if st.session_state.has_error:
                        st.session_state.counter_no += 1
                    else:
                        st.session_state.counter_ok += 1
                    
                    # Atualiza placar lateral
                    update_sidebar_metrics()
                    
                    # Reset
                    st.session_state.stage = None
                    st.session_state.has_error = False

                st.session_state.last_state = current_state
                s_color = (0, 255, 0) if current_state in [CONSTANTS['stages']['UP'], CONSTANTS['stages']['DOWN']] else (0, 255, 255)
                if alert_msg: s_color = (0, 0, 255)

                if vis_p1: draw_visual_angle(frame, vis_p1, vis_p2, vis_p3, f"{int(main_angle_display)}", s_color, label_angle)
                
                # PLACAR NO VÍDEO (Pode manter se quiser, mas agora a sidebar já mostra)
                cv2.rectangle(frame, (0, 0), (320, 100), (0, 0, 0), -1)
                cv2.putText(frame, f"STATUS: {current_state}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
                if alert_msg: cv2.putText(frame, f"ALERTA: {alert_msg}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                
                cv2.putText(frame, f"TOTAL: {st.session_state.counter_total}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(frame, f"OK: {st.session_state.counter_ok}", (140, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(frame, f"NO: {st.session_state.counter_no}", (230, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            out.write(frame)
            frame_idx += 1
            if frames_total > 0: progress.progress(frame_idx / frames_total)
            status.text(f"Processando {frame_idx}/{frames_total}...")

        cap.release()
        out.release()
        detector.close()
        status.success("Análise Finalizada!")
        
        # O vídeo fica aqui, sem as colunas de métricas embaixo
        st.video(OUTPUT_PATH, format="video/webm")

    except Exception as e:
        st.error(f"Erro Crítico: {e}")
