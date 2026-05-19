# hankook.py
import streamlit as st
import requests
import time
# 🌟 우리가 방금 위에서 만든 텔레그램 모듈을 불러옵니다!
from telegram_bot import send_telegram_alert

# --- [1. 기본 웹페이지 설정] ---
st.set_page_config(page_title="실시간 주식 알림 봇", layout="wide")
st.title("🤖 한국투자증권 X 텔레그램 실시간 알림 봇")
st.write("목표 가격을 설정해두면 실시간으로 감시하여 텔레그램으로 알림을 보냅니다.")

# --- [2. 한국투자증권 API 함수 정의] ---

def get_hantu_token(app_key, app_secret, is_vts=True):
    """한국투자증권 접근 토큰(Access Token) 발급"""
    base_url = "https://openapivts.koreainvestment.com:29443" if is_vts else "https://openapi.koreainvestment.com:9443"
    url = f"{base_url}/oauth2/tokenP"
    
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    headers = {"content-type": "application/json"}
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        st.error(f"❌ 한투 토큰 발급 실패: {response.text}")
        return None

def get_current_price(app_key, app_secret, token, stock_code, is_vts=True):
    """한국투자증권 현재가 조회"""
    base_url = "https://openapivts.koreainvestment.com:29443" if is_vts else "https://openapi.koreainvestment.com:9443"
    url = f"{base_url}/uapi/domestic-stock/v1/quoting/inquire-price"
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        res_json = response.json()
        if 'output' in res_json:
            return int(res_json['output']['stck_prpr']), res_json['output']['hts_krn_snm']
    return None, None

# --- [3. UI 및 세션 상태 제어] ---
if "monitoring" not in st.session_state:
    st.session_state.monitoring = False

# 사이드바: 금고(secrets.toml)에서 자동으로 값을 읽어와 마스킹 처리하여 보여줍니다.
with st.sidebar:
    st.header("🛡️ 보안 인증 정보 (금고 연동)")
    # 안전하게 금고에서 값을 읽어오므로 코드 해킹 위험이 없습니다.
    HANTU_APP_KEY = st.text_input("한투 APP KEY", type="password", value=st.secrets["HANTU_APP_KEY"])
    HANTU_APP_SECRET = st.text_input("한투 APP SECRET", type="password", value=st.secrets["HANTU_APP_SECRET"])
    is_simulation = st.checkbox("모의투자 계좌인가요?", value=True)
    
    st.markdown("---")
    st.info("💬 텔레그램 연결 정보는 내장된 금고 파일에서 안전하게 로드되었습니다.")

# 메인 화면 설정 조건 입력창
col1, col2, col3 = st.columns(3)
with col1:
    stock_code = st.text_input("📈 종목코드 (6자리 숫자)", value="005930")
with col2:
    target_price = st.number_input("🎯 목표 가격 (원)", value=70000, step=100)
with col3:
    condition = st.selectbox("🔔 알림 조건", ["이상 (>=)", "이하 (<=)"])

btn_col1, btn_col2 = st.columns(2)
with btn_col1:
    if st.button("🚀 실시간 감시 시작", use_container_width=True):
        st.session_state.monitoring = True

with btn_col2:
    if st.button("🛑 감시 중지", use_container_width=True):
        st.session_state.monitoring = False

# --- [4. 실시간 감시 Core Loop] ---
if st.session_state.monitoring:
    st.info("🔄 실시간 시세 감시가 작동 중입니다...")
    
    token = get_hantu_token(HANTU_APP_KEY, HANTU_APP_SECRET, is_simulation)
    
    if token:
        status_box = st.empty()
        
        while st.session_state.monitoring:
            current_p, stock_name = get_current_price(HANTU_APP_KEY, HANTU_APP_SECRET, token, stock_code, is_simulation)
            
            if current_p:
                status_box.metric(
                    label=f"🟢 감시 중: {stock_name} ({stock_code})", 
                    value=f"{current_p:,} 원", 
                    delta=f"목표가까지 {current_p - target_price:,} 원"
                )
                
                # 조건 검사
                is_triggered = False
                if condition == "이상 (>=)" and current_p >= target_price:
                    is_triggered = True
                elif condition == "이하 (<=)" and current_p <= target_price:
                    is_triggered = True
                
                # 알림 발송
                if is_triggered:
                    msg = f"🔔 [목표가 도달 알림]\n종목: {stock_name}\n현재가: {current_p:,}원\n설정조건: {target_price:,}원 {condition}"
                    
                    # 🌟 업그레이드된 텔레그램 모듈 함수 호출!
                    send_telegram_alert(msg)
                    
                    st.balloons()
                    st.success("🎉 목표가 도달! 텔레그램 알림을 전송하고 감시를 종료합니다.")
                    st.session_state.monitoring = False
                    break
            else:
                status_box.error("❌ 현재가를 가져오지 못했습니다. 장외 시간이거나 키 설정을 확인하세요.")
            
            time.sleep(5) # 5초마다 조회