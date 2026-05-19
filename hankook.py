import streamlit as st
import requests
import time
import datetime
import pandas as pd
import FinanceDataReader as fdr
from telegram_bot import send_telegram_alert

# --- [1. 기본 웹페이지 설정] ---
st.set_page_config(page_title="실시간 주식 알림 봇", layout="wide")
st.title("🤖 한국투자증권 X 텔레그램 실시간 알림 봇")
st.write("여러 종목의 목표가를 설정해두면 08:00 ~ 15:20 동안 실시간 감시합니다.")

# --- [2. 종목명 <-> 종목코드 번역 기능] ---
@st.cache_data
def load_stock_dict():
    try:
        df = fdr.StockListing('KRX') 
        return df[['Code', 'Name']]
    except Exception as e:
        return pd.DataFrame(columns=['Code', 'Name'])

def name_to_code(input_text, df):
    if str(input_text).isdigit():
        return str(input_text).zfill(6)
    if df.empty:
        return None 
    result = df[df['Name'] == str(input_text)]
    if not result.empty:
        return result.iloc[0]['Code']
    else:
        return None

# --- [3. 한국투자증권 API 통신 함수] ---
def get_hantu_token(app_key, app_secret, is_vts=True):
    base_url = "https://openapivts.koreainvestment.com:29443" if is_vts else "https://openapi.koreainvestment.com:9443"
    url = f"{base_url}/oauth2/tokenP"
    payload = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}
    headers = {"content-type": "application/json"}
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    return None

def get_current_price(app_key, app_secret, token, stock_code, is_vts=True):
    base_url = "https://openapivts.koreainvestment.com:29443" if is_vts else "https://openapi.koreainvestment.com:9443"
    url = f"{base_url}/uapi/domestic-stock/v1/quoting/inquire-price"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010100"
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": stock_code}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        res_json = response.json()
        if 'output' in res_json:
            return int(res_json['output']['stck_prpr']), res_json['output']['hts_krn_snm']
    return None, None

# --- [4. UI 및 세션 상태 제어] ---
if "monitoring" not in st.session_state:
    st.session_state.monitoring = False

stock_dict_df = load_stock_dict()

with st.sidebar:
    st.header("🛡️ 보안 인증 정보")
    HANTU_APP_KEY = st.text_input("한투 APP KEY", type="password", value=st.secrets.get("HANTU_APP_KEY", ""))
    HANTU_APP_SECRET = st.text_input("한투 APP SECRET", type="password", value=st.secrets.get("HANTU_APP_SECRET", ""))
    is_simulation = st.checkbox("모의투자 계좌인가요?", value=True)

# 🌟 다중 종목 입력 UI (데이터프레임 에디터)
st.subheader("📋 감시 종목 리스트")
st.write("표 아래의 **[➕ 행 추가]** 버튼을 눌러 감시할 종목을 여러 개 등록하세요.")

if "watch_df" not in st.session_state:
    st.session_state.watch_df = pd.DataFrame([
        {"종목명_또는_코드": "삼성전자", "목표가격": 80000, "조건": "이상 (>=)"},
        {"종목명_또는_코드": "LIG넥스원", "목표가격": 250000, "조건": "이상 (>=)"}
    ])

edited_df = st.data_editor(
    st.session_state.watch_df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "조건": st.column_config.SelectboxColumn("조건", options=["이상 (>=)", "이하 (<=)"], required=True),
        "목표가격": st.column_config.NumberColumn("목표가격", step=100, required=True)
    }
)

btn_col1, btn_col2 = st.columns(2)
with btn_col1:
    if st.button("🚀 실시간 감시 시작", use_container_width=True):
        st.session_state.monitoring = True
        st.session_state.alerted_set = set() # 시작할 때마다 알림 기록 초기화
with btn_col2:
    if st.button("🛑 감시 중지", use_container_width=True):
        st.session_state.monitoring = False

# --- [5. 다중 종목 & 시간 제한 Core Loop] ---
if st.session_state.monitoring:
    token = get_hantu_token(HANTU_APP_KEY, HANTU_APP_SECRET, is_simulation)
    
    if token:
        status_box = st.empty()
        
        while st.session_state.monitoring:
            # 🌟 1. 시간 확인 로직 (UTC 시간을 KST로 변환)
            now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
            total_minutes = now_kst.hour * 60 + now_kst.minute
            
            # 08:00(480분) ~ 15:20(920분) 사이인지 확인
            if not (480 <= total_minutes <= 920):
                status_box.warning(f"⏳ 현재 시간({now_kst.strftime('%H:%M')})은 감시 시간(08:00~15:20)이 아닙니다. 대기 중입니다...")
                time.sleep(10) # 10초 대기 후 다시 시간 확인
                continue
            
            # 🌟 2. 장중일 경우 다중 종목 순회 검사
            display_texts = []
            
            for index, row in edited_df.iterrows():
                stock_input = str(row["종목명_또는_코드"])
                target_price = int(row["목표가격"])
                condition = row["조건"]
                
                actual_code = name_to_code(stock_input, stock_dict_df)
                if not actual_code:
                    display_texts.append(f"❌ {stock_input}: 종목 검색 실패")
                    continue
                
                # API 호출 간격 조절 (초당 1건 이상 요청 시 차단 방지)
                time.sleep(0.5) 
                current_p, stock_name = get_current_price(HANTU_APP_KEY, HANTU_APP_SECRET, token, actual_code, is_simulation)
                
                if current_p:
                    display_texts.append(f"🟢 {stock_name}({actual_code}): {current_p:,}원 (목표: {target_price:,}원)")
                    
                    is_triggered = False
                    if condition == "이상 (>=)" and current_p >= target_price: is_triggered = True
                    elif condition == "이하 (<=)" and current_p <= target_price: is_triggered = True
                    
                    # 목표가 도달 시 & 아직 알림을 안 보낸 종목일 경우에만 전송
                    if is_triggered and actual_code not in st.session_state.alerted_set:
                        msg = f"🚀 [돌파 알림]\n종목: {stock_name}\n현재가: {current_p:,}원\n설정조건: {target_price:,}원 {condition}"
                        send_telegram_alert(msg)
                        st.session_state.alerted_set.add(actual_code) # 알림 보냄 표시
                        display_texts.append(f"   └ 🔔 알림 발송 완료!")
                else:
                    display_texts.append(f"⚠️ {stock_input}: 가격 조회 실패 (장외 시간이거나 키 오류)")
            
            # 화면에 현재 모든 종목의 상태 업데이트
            status_box.info(f"🔄 실시간 감시 중 ({now_kst.strftime('%H:%M:%S')})\n\n" + "\n".join(display_texts))
            
            # 한 바퀴 다 돌면 5초 휴식 후 반복
            time.sleep(5)
