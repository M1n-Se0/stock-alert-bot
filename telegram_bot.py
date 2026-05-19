# telegram_bot.py
import requests
import streamlit as st

def send_telegram_alert(text):
    """
    금고(secrets.toml)에서 토큰과 채팅 ID를 자동으로 꺼내와서
    텔레그램 메시지를 전송하는 함수입니다.
    """
    # 금고에서 안전하게 키값 꺼내오기
    token = st.secrets["TELEGRAM_TOKEN"]
    chat_id = st.secrets["TELEGRAM_CHAT_ID"]
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return True
        else:
            print(f"텔레그램 전송 실패 (상태코드: {response.status_code})")
            return False
    except Exception as e:
        print(f"텔레그램 통신 에러: {e}")
        return False