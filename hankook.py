import streamlit as st
import requests
import time
import pandas as pd  # 🌟 빈 사전을 만들기 위해 pandas 라이브러리 추가
import FinanceDataReader as fdr  
from telegram_bot import send_telegram_alert

# --- [1. 기본 웹페이지 설정] ---
# (이 부분은 기존과 동일합니다)

# --- [🌟 2. 종목명 <-> 종목코드 번역 기능 (방어 로직 추가)] ---
@st.cache_data
def load_stock_dict():
    try:
        # 정상적으로 한국거래소(KRX)에서 데이터를 가져오기 시도
        df = fdr.StockListing('KRX') 
        return df[['Code', 'Name']]
    except Exception as e:
        # 🚨 해외 클라우드 IP 차단으로 실패할 경우, 프로그램이 죽지 않도록 '빈 사전'을 반환
        return pd.DataFrame(columns=['Code', 'Name'])

def name_to_code(input_text, df):
    # 1. 6자리 숫자를 입력했다면 무조건 그대로 통과 (항상 작동)
    if input_text.isdigit():
        return input_text
    
    # 2. 만약 사전이 비어있다면 (서버 차단 상태), 이름 검색 불가 처리
    if df.empty:
        return None 
        
    # 3. 사전이 정상이라면 이름으로 검색
    result = df[df['Name'] == input_text]
    if not result.empty:
        return result.iloc[0]['Code']
    else:
        return None

# --- [이하 3. 4. API 함수 및 UI 코드는 기존과 동일하게 둡니다] ---
