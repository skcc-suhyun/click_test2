import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import streamlit as st
from modules.loader import load_actions
from modules.grouping import group_screens

st.title("🧩 화면 그룹핑")

json_file = "data/actions/metadata_182.json"
actions = load_actions(json_file)

screens = group_screens(actions)

st.success(f"총 {len(screens)}개의 화면으로 묶였습니다.")

for i, screen in enumerate(screens):
    with st.expander(f"📄 Screen {i+1}: {screen['screen_name']}", expanded=True):
        st.write(f"**대표 이미지 경로:** `{screen['representative_image']}`")
        st.write(f"**액션 수:** {len(screen['actions'])}")
        
        # 이미지 표시
        image_path = screen.get('representative_image')
        if image_path and os.path.exists(image_path):
            st.image(image_path, caption=f"Screen {i+1}: {screen['screen_name']}", use_container_width=True)
        elif image_path:
            st.warning(f"⚠️ 이미지 파일을 찾을 수 없습니다: {image_path}")
        else:
            st.info("ℹ️ 대표 이미지가 지정되지 않았습니다.")
        
        # 액션 목록
        st.write("**액션 목록:**")
        for j, action in enumerate(screen['actions']):
            action_type = action.get('action_type', 'unknown')
            description = action.get('description', 'No description')
            st.write(f"- [{j+1}] `{action_type}`: {description}")
