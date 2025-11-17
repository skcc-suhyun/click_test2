import streamlit as st

import sys
import os
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

st.set_page_config(
    page_title="Manual AI",
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📘 Manual AI Dashboard")
st.markdown("---")

st.markdown("""
### 🎯 주요 기능

좌측 사이드바에서 다음 기능을 사용할 수 있습니다:

- **📸 스크린샷 뷰어**: 개별 액션의 스크린샷과 하이라이트 확인
- **🧩 화면 그룹핑**: 액션들을 화면별로 그룹화하여 확인
- **📄 메뉴얼 자동 생성**: 그룹화된 화면 기반 메뉴얼 생성

### 📝 사용 방법

1. 좌측 메뉴에서 원하는 기능을 선택하세요
2. 각 페이지에서 액션 데이터를 확인하고 분석할 수 있습니다
3. 스크린샷과 하이라이트를 통해 클릭 위치를 시각적으로 확인할 수 있습니다
""")

st.markdown("---")
st.info("💡 **팁**: 좌측 사이드바 메뉴를 통해 다양한 기능에 접근할 수 있습니다.")
