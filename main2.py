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
from fpdf import FPDF

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
# 1. FUNÇÕES AUXILIARES
# ==========================================
def get_manager():
    return stx.CookieManager()

cookie_manager = get_manager()

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

def salvar_config_usuario(username, config_dict):
    sheet = conectar_gsheets()
    if sheet:
        try:
            cell = sheet.find(username, in_column=1)
            if cell:
                config_json = json.dumps(config_dict)
                sheet.update_cell(cell.row, 4, config_json)
                st.toast("✅ Configurações salvas!", icon="☁️")
        except: st.error("Erro ao salvar")

def carregar_config_usuario(username):
    sheet = conectar_gsheets()
    if sheet:
        try:
            cell = sheet.find(username, in_column=1)
            if cell: return json.loads(sheet.cell(cell.row, 4).value)
        except: pass 
    return {}

# --- GERADOR DE PDF ---
def gerar_relatorio_pdf(username, exercicio, dados_log, placar, config_usada):
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"Relatorio de Performance: {exercicio}", ln=True, align="C")
    
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Atleta: {username} | Data: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)

    # Resumo
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Resumo da Sessao", ln=True)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 8, f"Total de Repeticoes: {placar['total']}", ln=True)
    pdf.set_text_color(0, 128, 0)
    pdf.cell(0, 8, f"Execucoes Corretas: {placar['ok']}", ln=True)
    pdf.set_text_color(255, 0, 0)
    pdf.cell(0, 8, f"Execucoes com Erro: {placar['no']}", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    # Regras
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Parametros de Seguranca Ativos", ln=True)
    pdf.set_font("Courier", "", 9)
    prefixo = f"{exercicio}_"
    tem_config = False
    for chave, valor in config_usada.items():
        if chave.startswith(prefixo):
            nome = chave.replace(prefixo, "").upper()
            val_str = "ATIVADO" if isinstance(valor, bool) and valor else str(valor)
            pdf.cell(0, 5, f"{nome}: {val_str}", ln=True)
            tem_config = True
    if not tem_config: pdf.cell(0, 5, "Padrao do sistema.", ln=True)
    pdf.ln(5)

    # Log Detalhado
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Detalhamento", ln=True)
    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", "B", 9)
    pdf.cell(20, 8, "REP", 1, 0, 'C', 1)
    pdf.cell(30, 8, "STATUS", 1, 0, 'C', 1)
    pdf.cell(30, 8, "TEMPO", 1, 0, 'C', 1)
    pdf.cell(0, 8, "OBSERVACOES", 1, 1, 'C', 1)

    pdf.set_font("Arial", "", 9)
    for log in dados_log:
        status_txt = "CORRETO" if log['status'] else "ERRO"
        if log['status']: pdf.set_text_color(0, 100, 0)
        else: pdf.set_text_color(200, 0, 0)
        
        pdf.cell(20, 8, str(log['rep']), 1, 0, 'C')
        pdf.cell(30, 8, status_txt, 1, 0, 'C')
        pdf.set_text_color(0, 0, 0)
        pdf.cell(30, 8, log['tempo'], 1, 0, 'C')
        
        msg = log['erros'] if log['erros'] else "-"
        if len(msg) > 60:
             x, y = pdf.get_x(), pdf.get_y()
             pdf.multi_cell(0, 8, msg, 1, 'L')
             pdf.set_xy(x, y + 8) 
        else:
             pdf.cell(0, 8, msg, 1, 1, 'L')

    return pdf.output(dest="S").encode("latin-1")

# --- LÓGICA DE LOGIN ---
cookie_user = cookie_manager.get(cookie="user_treino_ai")

if 'logged_in' not in st.session_state:
    if cookie_user:
        st.session_state['logged_in'] = True
        st.session_state['username'] = cookie_user
        st.session_state['user_name'] = cookie_user 
        saved = carregar_config_usuario(cookie_user)
        st.session_state['user_configs'] = saved if saved else {}
    else:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ""
        st.session_state['user_configs'] = {}

def login_page():
    st.markdown("<h1 style='text-align: center;'>🔒 Login AI Fitness</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.button("Entrar", use_container_width=True):
            sheet = conectar_gsheets()
            if sheet:
                try:
                    records = sheet.get_all_records()
                    for reg in records:
                        if str(reg['username']) == u and str(reg['password']) == hash_senha(p):
                            st.session_state['logged_in'] = True
                            st.session_state['user_name'] = reg.get('name', u)
                            st.session_state['username'] = u
                            st.session_state['user_configs'] = carregar_config_usuario(u) or {}
                            cookie_manager.set("user_treino_ai", u, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
                            st.rerun()
                except: st.error("Erro login")

if not st.session_state['logged_in']:
    login_page()
    st.stop()

# ==========================================
# 3. APP PRINCIPAL
# ==========================================

st.sidebar.write(f"Olá, **{st.session_state.get('user_name', 'Atleta')}** 👋")
if st.sidebar.button("Sair"):
    st.session_state['logged_in'] = False
    cookie_manager.delete("user_treino_ai")
    st.rerun()

st.title("Análise de Exercícios com Visão Computacional")

MOVEMENT_CONSTANTS = {
    "Agachamento Búlgaro": { "stages": {"UP": "EM PE", "DOWN": "AGACHAMENTO OK", "TRANSITION": "DESCENDO"} },
    "Agachamento Padrão": { "stages": {"UP": "EM PE", "DOWN": "AGACHAMENTO OK", "TRANSITION": "DESCENDO"} },
    "Supino Máquina": { "stages": {"UP": "BRACO ESTICADO", "DOWN": "NA BASE", "TRANSITION": "EMPURRANDO"} },
    "Flexão de Braço": { "stages": {"UP": "EM CIMA (OK)", "DOWN": "EMBAIXO (OK)", "TRANSITION": "MOVIMENTO"} },
    "Rosca Direta": { "stages": {"UP": "ESTICADO", "DOWN": "CONTRAIDO", "TRANSITION": "MOVIMENTO"} },
    "Desenvolvimento (Ombro)": { "stages": {"UP": "TOPO (LOCKOUT)", "DOWN": "BASE", "TRANSITION": "MOVIMENTO"} },
    "Afundo (Lunge)": { "stages": {"UP": "DESCENDO", "DOWN": "BOM AFUNDO", "TRANSITION": "DESCENDO"} },
    "Levantamento Terra": { "stages": {"UP": "TOPO (ERETO)", "DOWN": "POSICAO INICIAL", "TRANSITION": "LEVANTANDO"} },
    "Prancha (Plank)": { "stages": {"UP": "QUADRIL ALTO", "DOWN": "QUADRIL CAINDO", "TRANSITION": "PERFEITO"} },
    "Abdominal (Crunch)": { "stages": {"UP": "DEITADO", "DOWN": "CONTRAIDO", "TRANSITION": "MOVIMENTO"} },
    "Elevação Lateral": { "stages": {"UP": "ALTURA CORRETA", "DOWN": "DESCANSO", "TRANSITION": "SUBINDO"} }
}

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
    cv2.putText(frame, f"{label}: {text}", (int(p2[0])+15, int(p2[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)

# ==========================================
# 4. SIDEBAR E CONFIGS
# ==========================================
st.sidebar.header("1. Exercício & Configs")
EXERCISE_OPTIONS = list(MOVEMENT_CONSTANTS.keys())

def reset_counters():
    st.session_state.counter_total = 0
    st.session_state.counter_ok = 0
    st.session_state.counter_no = 0
    st.session_state.stage = None 
    st.session_state.has_error = False
    st.session_state.rep_log = [] 
    st.session_state.erros_na_rep_atual = set()
    st.session_state.processed = False # Resetar estado de processamento

exercise_type = st.sidebar.selectbox("Selecionar:", EXERCISE_OPTIONS, on_change=reset_counters)

if 'user_configs' not in st.session_state: st.session_state['user_configs'] = {}
def get_val(key, default): return st.session_state['user_configs'].get(f"{exercise_type}_{key}", default)
user_thresholds = {} 

if "counter_total" not in st.session_state: reset_counters()
if "processed" not in st.session_state: st.session_state.processed = False

# --- PLACAR ---
st.sidebar.markdown("### 📊 Placar Atual")
placar_placeholder = st.sidebar.empty()
# --- BOTÃO DOWNLOAD (PLACEHOLDER) ---
btn_placeholder = st.sidebar.empty()

def update_sidebar_metrics():
    with placar_placeholder.container():
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", st.session_state.counter_total)
        c2.metric("✅", st.session_state.counter_ok)
        c3.metric("❌", st.session_state.counter_no)

update_sidebar_metrics()

# --- REGRAS DINÂMICAS ---
st.sidebar.markdown("---")
def render_headers(): st.sidebar.markdown("### 📏 Configuração")
render_headers()

if exercise_type == "Agachamento Búlgaro":
    user_thresholds['knee_min'] = st.sidebar.number_input("Ângulo Baixo", value=get_val('knee_min', 75), key=f"{exercise_type}_knee_min")
    user_thresholds['knee_max'] = st.sidebar.number_input("Ângulo Alto", value=get_val('knee_max', 160), key=f"{exercise_type}_knee_max")
    user_thresholds['check_torso'] = st.sidebar.checkbox("Alerta Tronco", value=get_val('check_torso', True), key=f"{exercise_type}_check_torso")
    if user_thresholds['check_torso']:
        user_thresholds['torso_limit'] = st.sidebar.slider("Limite Tronco", 50, 90, value=get_val('torso_limit', 70), key=f"{exercise_type}_torso_limit")

elif exercise_type == "Agachamento Padrão":
    user_thresholds['stand_max'] = st.sidebar.slider("Limite Em Pé", 0, 40, value=get_val('stand_max', 32), key=f"{exercise_type}_stand_max")
    user_thresholds['pass_min'] = st.sidebar.slider("Limite Agachado", 70, 110, value=get_val('pass_min', 80), key=f"{exercise_type}_pass_min")
    user_thresholds['check_valgo'] = st.sidebar.checkbox("Alerta Valgo (Joelho)", value=get_val('check_valgo', True), key=f"{exercise_type}_check_valgo")

elif exercise_type == "Supino Máquina":
    user_thresholds['extended_min'] = st.sidebar.slider("Braço Esticado", 140, 180, value=get_val('extended_min', 160), key=f"{exercise_type}_extended_min")
    user_thresholds['flexed_max'] = st.sidebar.slider("Braço Base", 40, 100, value=get_val('flexed_max', 80), key=f"{exercise_type}_flexed_max")
    user_thresholds['check_safety'] = st.sidebar.checkbox("Alerta Cotovelo", value=get_val('check_safety', True), key=f"{exercise_type}_check_safety")
    if user_thresholds['check_safety']:
        user_thresholds['safety_limit'] = st.sidebar.slider("Limite Abertura", 60, 90, value=get_val('safety_limit', 80), key=f"{exercise_type}_safety_limit")

elif exercise_type == "Flexão de Braço":
    user_thresholds['pu_down'] = st.sidebar.slider("Ângulo Baixo", 60, 100, value=get_val('pu_down', 90), key=f"{exercise_type}_pu_down")
    user_thresholds['pu_up'] = st.sidebar.slider("Ângulo Alto", 150, 180, value=get_val('pu_up', 165), key=f"{exercise_type}_pu_up")
    user_thresholds['check_hip_drop'] = st.sidebar.checkbox("Alerta Coluna/Quadril", value=get_val('check_hip_drop', True), key=f"{exercise_type}_check_hip_drop")

elif exercise_type == "Rosca Direta":
    user_thresholds['bc_flex'] = st.sidebar.slider("Contração Máx", 30, 60, value=get_val('bc_flex', 45), key=f"{exercise_type}_bc_flex")
    user_thresholds['bc_ext'] = st.sidebar.slider("Extensão Total", 140, 180, value=get_val('bc_ext', 160), key=f"{exercise_type}_bc_ext")
    user_thresholds['check_swing'] = st.sidebar.checkbox("Alerta Gangorra", value=get_val('check_swing', True), key=f"{exercise_type}_check_swing")

elif exercise_type == "Desenvolvimento (Ombro)":
    user_thresholds['sp_up'] = st.sidebar.slider("Lockout", 150, 180, value=get_val('sp_up', 165), key=f"{exercise_type}_sp_up")
    user_thresholds['sp_down'] = st.sidebar.slider("Base", 60, 100, value=get_val('sp_down', 80), key=f"{exercise_type}_sp_down")
    user_thresholds['check_back_arch'] = st.sidebar.checkbox("Alerta Hiperlordose", value=get_val('check_back_arch', True), key=f"{exercise_type}_check_back_arch")

elif exercise_type == "Afundo (Lunge)":
    user_thresholds['lg_knee'] = st.sidebar.slider("Profundidade", 70, 110, value=get_val('lg_knee', 90), key=f"{exercise_type}_lg_knee")
    user_thresholds['check_torso'] = st.sidebar.checkbox("Alerta Tronco", value=get_val('check_torso', True), key=f"{exercise_type}_check_torso")
    if user_thresholds['check_torso']:
        user_thresholds['lg_torso'] = st.sidebar.slider("Inclinação Mínima", 70, 90, value=get_val('lg_torso', 80), key=f"{exercise_type}_lg_torso")

elif exercise_type == "Levantamento Terra":
    user_thresholds['dl_hip'] = st.sidebar.slider("Extensão Final", 160, 180, value=get_val('dl_hip', 170), key=f"{exercise_type}_dl_hip")
    user_thresholds['dl_back'] = st.sidebar.slider("Limite Costas", 40, 90, value=get_val('dl_back', 60), key=f"{exercise_type}_dl_back")
    user_thresholds['check_round_back'] = st.sidebar.checkbox("Alerta Coluna", value=get_val('check_round_back', True), key=f"{exercise_type}_check_round_back")

elif exercise_type == "Prancha (Plank)":
    user_thresholds['pk_min'] = st.sidebar.slider("Mínimo (Cair)", 150, 175, value=get_val('pk_min', 165), key=f"{exercise_type}_pk_min")
    user_thresholds['pk_max'] = st.sidebar.slider("Máximo (Empinar)", 175, 190, value=get_val('pk_max', 185), key=f"{exercise_type}_pk_max")

elif exercise_type == "Abdominal (Crunch)":
    user_thresholds['cr_flex'] = st.sidebar.slider("Contração", 40, 100, value=get_val('cr_flex', 70), key=f"{exercise_type}_cr_flex")
    user_thresholds['cr_ext'] = st.sidebar.slider("Retorno", 110, 150, value=get_val('cr_ext', 130), key=f"{exercise_type}_cr_ext")
    user_thresholds['check_neck'] = st.sidebar.checkbox("Alerta Pescoço", value=get_val('check_neck', True), key=f"{exercise_type}_check_neck")

elif exercise_type == "Elevação Lateral":
    user_thresholds['lr_height'] = st.sidebar.slider("Topo (Ombro)", 70, 100, value=get_val('lr_height', 85), key=f"{exercise_type}_lr_height")
    user_thresholds['lr_low'] = st.sidebar.slider("Baixo (Descanso)", 10, 30, value=get_val('lr_low', 20), key=f"{exercise_type}_lr_low")
    user_thresholds['check_high_shoulder'] = st.sidebar.checkbox("Alerta Ombro Alto", value=get_val('check_high_shoulder', True), key=f"{exercise_type}_check_high_shoulder")

st.sidebar.markdown("---")
if st.sidebar.button("💾 Salvar Minhas Configs", type="primary"):
    for key, value in user_thresholds.items():
        st.session_state['user_configs'][f"{exercise_type}_{key}"] = value
    salvar_config_usuario(st.session_state['username'], st.session_state['user_configs'])

# ==========================================
# 7. PROCESSAMENTO
# ==========================================
st.sidebar.markdown("---")
def on_upload_change(): reset_counters()

uploaded_file = st.sidebar.file_uploader("3. Carregar Vídeo", type=["mp4", "mov", "avi", "webm"], on_change=on_upload_change)

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

def download_model_if_missing(model_path):
    url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    if not os.path.exists(model_path) or os.path.getsize(model_path) < 1000000:
        with st.spinner("Baixando modelo de IA..."):
            try:
                r = requests.get(url)
                if r.status_code == 200:
                    with open(model_path, 'wb') as f: f.write(r.content)
                    return True
            except: st.error("Erro modelo"); return False
    return True

if run_btn and video_path:
    # Reset inicial
    reset_counters()
    update_sidebar_metrics()
    
    if not download_model_if_missing(MODEL_PATH): st.stop()

    try:
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.PoseLandmarkerOptions(base_options=base_options, running_mode=vision.RunningMode.VIDEO, min_pose_detection_confidence=0.5, min_pose_presence_confidence=0.5, min_tracking_confidence=0.5)
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

        COUNT_ON_RETURN_TO = CONSTANTS['stages']['UP']
        if exercise_type == "Elevação Lateral": COUNT_ON_RETURN_TO = CONSTANTS['stages']['DOWN']

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break

            frame = cv2.resize(frame, (target_width, target_height))
            h, w, _ = frame.shape
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = detector.detect_for_video(mp_image, int(timestamp_ms))
            timestamp_ms += (1000.0 / fps)

            current_state = st.session_state.last_state
            main_angle_display = 0
            alert_msg = ""
            vis_p1, vis_p2, vis_p3 = None, None, None
            label_angle = "" 

            if result.pose_landmarks:
                lm = result.pose_landmarks[0]
                draw_pose_landmarks(frame, lm, w, h)
                def get_pt(idx): return [lm[idx].x * w, lm[idx].y * h]
                
                nose = get_pt(0)
                sh_l, hip_l, knee_l, ank_l = get_pt(11), get_pt(23), get_pt(25), get_pt(27)
                sh_r, hip_r, knee_r, ank_r = get_pt(12), get_pt(24), get_pt(26), get_pt(28)
                elb_l, wr_l = get_pt(13), get_pt(15)
                ear_l = get_pt(7)

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
                        if torso_angle < user_thresholds.get('torso_limit', 70): alert_msg = "TRONCO INCLINADO"

                elif exercise_type == "Agachamento Padrão":
                    vertical_ref = [knee_l[0], knee_l[1] - 100]
                    femur_angle = calculate_angle(hip_l, knee_l, vertical_ref)
                    main_angle_display = femur_angle; vis_p1,vis_p2,vis_p3 = hip_l,knee_l,vertical_ref; label_angle = "Coxa"
                    if femur_angle <= user_thresholds['stand_max']: current_state = CONSTANTS['stages']['UP']
                    elif user_thresholds['stand_max'] < femur_angle < user_thresholds['pass_min']: current_state = CONSTANTS['stages']['TRANSITION']
                    elif femur_angle >= user_thresholds['pass_min']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    if user_thresholds.get('check_valgo'):
                        dist_knees = abs(knee_l[0] - knee_r[0])
                        dist_ankles = abs(ank_l[0] - ank_r[0])
                        if dist_knees < (dist_ankles * 0.8): alert_msg = "JOELHOS P/ DENTRO (VALGO)"

                elif exercise_type == "Supino Máquina":
                    elbow_angle = calculate_angle(sh_l, elb_l, wr_l)
                    main_angle_display = elbow_angle; vis_p1,vis_p2,vis_p3 = sh_l,elb_l,wr_l; label_angle = "Cotovelo"
                    if elbow_angle >= user_thresholds['extended_min']: current_state = CONSTANTS['stages']['UP']
                    elif elbow_angle <= user_thresholds['flexed_max']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    else: current_state = CONSTANTS['stages']['TRANSITION']
                    if user_thresholds.get('check_safety'):
                        abduction_angle = calculate_angle(hip_l, sh_l, elb_l)
                        if abduction_angle > user_thresholds.get('safety_limit', 80): alert_msg = "COTOVELOS ABERTOS!"

                elif exercise_type == "Flexão de Braço":
                    angle_elb = calculate_angle(sh_l, elb_l, wr_l)
                    main_angle_display = angle_elb; vis_p1,vis_p2,vis_p3 = sh_l,elb_l,wr_l; label_angle = "Cotovelo"
                    if angle_elb < user_thresholds['pu_down']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    elif angle_elb > user_thresholds['pu_up']: current_state = CONSTANTS['stages']['UP']
                    else: current_state = CONSTANTS['stages']['TRANSITION']
                    if user_thresholds.get('check_hip_drop'):
                        body_line = calculate_angle(sh_l, hip_l, knee_l)
                        if body_line < 160: alert_msg = "QUADRIL BAIXO"
                        elif body_line > 190: alert_msg = "QUADRIL ALTO"

                elif exercise_type == "Rosca Direta":
                    angle_elb = calculate_angle(sh_l, elb_l, wr_l)
                    main_angle_display = angle_elb; vis_p1,vis_p2,vis_p3 = sh_l,elb_l,wr_l; label_angle = "Biceps"
                    if angle_elb < user_thresholds['bc_flex']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    elif angle_elb > user_thresholds['bc_ext']: current_state = CONSTANTS['stages']['UP']
                    else: current_state = CONSTANTS['stages']['TRANSITION']
                    if user_thresholds.get('check_swing'):
                        trunk_angle = calculate_angle(knee_l, hip_l, sh_l)
                        if trunk_angle > 195: alert_msg = "NAO BALANCE O TRONCO"

                elif exercise_type == "Desenvolvimento (Ombro)":
                    angle_elb = calculate_angle(sh_l, elb_l, wr_l)
                    main_angle_display = angle_elb; vis_p1,vis_p2,vis_p3 = sh_l,elb_l,wr_l
                    if angle_elb > user_thresholds['sp_up']: current_state = CONSTANTS['stages']['UP']
                    elif angle_elb < user_thresholds['sp_down']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    else: current_state = CONSTANTS['stages']['TRANSITION']
                    if user_thresholds.get('check_back_arch'):
                        back_angle = calculate_angle(knee_l, hip_l, sh_l)
                        if back_angle > 195: alert_msg = "COLUNA ARQUEADA"

                elif exercise_type == "Afundo (Lunge)":
                    angle_knee = calculate_angle(hip_l, knee_l, ank_l)
                    main_angle_display = angle_knee; vis_p1,vis_p2,vis_p3 = hip_l,knee_l,ank_l; label_angle = "Joelho"
                    if angle_knee <= user_thresholds['lg_knee']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    else: current_state = CONSTANTS['stages']['UP']
                    if user_thresholds.get('check_torso'):
                        angle_torso = calculate_angle(sh_l, hip_l, knee_l)
                        if angle_torso < user_thresholds.get('lg_torso', 80): alert_msg = "POSTURA RUIM"

                elif exercise_type == "Levantamento Terra":
                    angle_hip = calculate_angle(sh_l, hip_l, knee_l)
                    main_angle_display = angle_hip; vis_p1,vis_p2,vis_p3 = sh_l,hip_l,knee_l; label_angle = "Quadril"
                    if angle_hip > user_thresholds['dl_hip']: current_state = CONSTANTS['stages']['UP']
                    elif angle_hip < user_thresholds['dl_back']: current_state = CONSTANTS['stages']['DOWN']; st.session_state.stage = "down"
                    else: current_state = CONSTANTS['stages']['TRANSITION']
                    if user_thresholds.get('check_round_back'):
                        if current_state == CONSTANTS['stages']['DOWN']:
                            if hip_l[1] < sh_l[1]: alert_msg = "QUADRIL MUITO ALTO"

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
                    if user_thresholds.get('check_neck'):
                        dist_ear_sh = np.linalg.norm(np.array(ear_l) - np.array(sh_l))
                        if dist_ear_sh < 40: alert_msg = "NAO PUXE O PESCOCO"

                elif exercise_type == "Elevação Lateral":
                    angle_abd = calculate_angle(hip_l, sh_l, elb_l)
                    main_angle_display = angle_abd; vis_p1,vis_p2,vis_p3 = hip_l,sh_l,elb_l; label_angle = "Ombro"
                    if angle_abd >= user_thresholds['lr_height']: current_state = CONSTANTS['stages']['UP']; st.session_state.stage = "down"
                    elif angle_abd < user_thresholds['lr_low']: current_state = CONSTANTS['stages']['DOWN']
                    else: current_state = CONSTANTS['stages']['TRANSITION']
                    if user_thresholds.get('check_high_shoulder'):
                        if angle_abd > 100: alert_msg = "BRACOS MUITO ALTOS"

                # LÓGICA DE CONTADOR
                if alert_msg:
                    st.session_state.has_error = True
                    st.session_state.erros_na_rep_atual.add(alert_msg)

                if current_state == COUNT_ON_RETURN_TO and st.session_state.stage == "down":
                    st.session_state.counter_total += 1
                    status_rep = True
                    if st.session_state.has_error:
                        st.session_state.counter_no += 1
                        status_rep = False
                    else:
                        st.session_state.counter_ok += 1
                    
                    # LOG
                    erros_consolidados = ", ".join(st.session_state.erros_na_rep_atual)
                    st.session_state.rep_log.append({
                        "rep": st.session_state.counter_total,
                        "status": status_rep,
                        "tempo": f"{timestamp_ms/1000:.1f}s",
                        "erros": erros_consolidados
                    })
                    
                    update_sidebar_metrics()
                    st.session_state.stage = None
                    st.session_state.has_error = False
                    st.session_state.erros_na_rep_atual = set()

                st.session_state.last_state = current_state
                s_color = (0, 255, 0) if current_state in [CONSTANTS['stages']['UP'], CONSTANTS['stages']['DOWN']] else (0, 255, 255)
                if alert_msg: s_color = (0, 0, 255)

                if vis_p1: draw_visual_angle(frame, vis_p1, vis_p2, vis_p3, f"{int(main_angle_display)}", s_color, label_angle)
                
                cv2.rectangle(frame, (0, 0), (400, 100), (0, 0, 0), -1)
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
        
        # SINALIZA QUE O VÍDEO FOI PROCESSADO
        st.session_state.processed = True
        
        # NÃO RENDERIZA NADA AQUI (O bloco abaixo cuida disso)

    except Exception as e:
        st.error(f"Erro Crítico: {e}")

# ==========================================
# 8. EXIBIÇÃO DE RESULTADOS PERSISTENTES
# ==========================================
# Este bloco roda sempre que a página recarrega, se houver um vídeo processado.
if st.session_state.get('processed', False):
    
    # 1. Mostra o Vídeo
    if os.path.exists(OUTPUT_PATH):
        st.video(OUTPUT_PATH, format="video/webm")
    
    # 2. Mostra o Botão de Download (na sidebar, abaixo do placar)
    placar_dados = {
        'total': st.session_state.counter_total,
        'ok': st.session_state.counter_ok,
        'no': st.session_state.counter_no
    }
    
    pdf_bytes = gerar_relatorio_pdf(
        st.session_state.get('user_name', 'Atleta'),
        exercise_type,
        st.session_state.rep_log,
        placar_dados,
        st.session_state['user_configs']
    )
    
    btn_placeholder.download_button(
        label="📄 Baixar Relatório PDF",
        data=pdf_bytes,
        file_name=f"relatorio_{exercise_type.replace(' ', '_')}_{int(time.time())}.pdf",
        mime="application/pdf",
        use_container_width=True
    )
