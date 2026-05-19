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
st.write("여러 종목의 목표가를 설정해두면 지정한 시간 동안만 실시간으로 감시합니다.")

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

# --- [3. 한국투자증권 API 통신 함수 (🚨 에러 출력 로직 복구)] ---
def get_hantu_token(app_key, app_secret, is_vts=True):
    base_url = "https://openapivts.koreainvestment.com:29443" if is_vts else "https://openapi.koreainvestment.com:9443"
    url = f"{base_url}/oauth2/tokenP"
    payload = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}
    headers = {"content-type": "application/json"}
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        # 실패 사유를 화면에 강제로 띄웁니다!
        st.error(f"❌ 토큰 발급 실패 (키 오류 또는 실전/모의투자 설정 확인): {response.text}")
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
    
    # 🚨 여기가 가장 중요합니다. 본인이 발급받은 키가 실계좌용인지 모의투자용인지 꼭 확인하세요!
    is_simulation = st.checkbox("모의투자 계좌인가요?", value=True)
    
    st.markdown("---")
    st.header("⏱️ 감시 시간 설정")
    start_time = st.time_input("시작 시간", value=datetime.time(8, 0))
    end_time = st.time_input("종료 시간", value=datetime.time(15, 20))

# 다중 종목 입력 UI
st.subheader("📋 감시 종목 리스트")
st.write("표 아래의 **[➕ 행 추가]** 버튼을 눌러 감시할 종목을 여러 개 등록하세요. (입력 후 반드시 Enter 키를 누르세요)")

if "watch_df" not in st.session_state:
    st.session_state.watch_df = pd.DataFrame([
        {"종목명_또는_코드": "삼성전자", "목표가격": 80000, "조건": "이상 (>=)"},
        {"종목명_또는_코드": "LIG넥스원", "목표가격": 250000, "조건": "이상 (>=)"}
    ])

st.session_state.watch_df = st.data_editor(
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
        st.session_state.alerted_set = set() 
with btn_col2:
    if st.button("🛑 감시 중지", use_container_width=True):
        st.session_state.monitoring = False

# --- [5. 다중 종목 & 시간 제한 Core Loop (🚨 에러 분기 추가)] ---
if st.session_state.monitoring:
    token = get_hantu_token(HANTU_APP_KEY, HANTU_APP_SECRET, is_simulation)
    
    # 🌟 토큰 발급 성공 시에만 루프 진입
    if token:
        status_box = st.empty()
        
        while st.session_state.monitoring:
            now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
            current_time_only = now_kst.time() 
            
            if not (start_time <= current_time_only <= end_time):
                waiting_stocks = ", ".join([str(row["종목명_또는_코드"]) for _, row in st.session_state.watch_df.iterrows()])
                status_box.warning(f"⏳ 현재 시간({now_kst.strftime('%H:%M')})은 설정된 감시 시간이 아닙니다.\n\n💤 대기 중인 종목: {waiting_stocks}")
                time.sleep(10) 
                continue
            
            display_texts = []
            
            for index, row in st.session_state.watch_df.iterrows():
                stock_input = str(row["종목명_또는_코드"])
                target_price = int(row["목표가격"])
                condition = row["조건"]
                
                actual_code = name_to_code(stock_input, stock_dict_df)
                if not actual_code:
                    display_texts.append(f"❌ {stock_input}: 종목 검색 실패")
                    continue
                
                time.sleep(0.5) 
                current_p, stock_name = get_current_price(HANTU_APP_KEY, HANTU_APP_SECRET, token, actual_code, is_simulation)
                
                if current_p:
                    display_texts.append(f"🟢 {stock_name}({actual_code}): {current_p:,}원 (목표: {target_price:,}원)")
                    
                    is_triggered = False
                    if condition == "이상 (>=)" and current_p >= target_price: is_triggered = True
                    elif condition == "이하 (<=)" and current_p <= target_price: is_triggered = True
                    
                    if is_triggered and actual_code not in st.session_state.alerted_set:
                        msg = f"🚀 [돌파 알림]\n종목: {stock_name}\n현재가: {current_p:,}원\n설정조건: {target_price:,}원 {condition}"
                        send_telegram_alert(msg)
                        st.session_state.alerted_set.add(actual_code) 
                        display_texts.append(f"   └ 🔔 알림 발송 완료!")
                else:
                    display_texts.append(f"⚠️ {stock_input}: 가격 조회 실패 (장외 시간이거나 키 오류)")
            
            status_box.info(f"🔄 실시간 감시 중 ({now_kst.strftime('%H:%M:%S')})\n\n" + "\n".join(display_texts))
            time.sleep(5) 
            
    # 🌟 토큰 발급 실패 시 아예 감시 상태를 꺼버리고 경고창 띄우기
    else:
        st.error("🚨 API 키 인증에 실패하여 시스템을 시작할 수 없습니다. 금고 파일(secrets)의 정보나 '모의투자' 체크박스를 확인해 주세요.")
        st.session_state.monitoring = False
