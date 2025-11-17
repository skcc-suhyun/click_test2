import sys
import os
import json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
from modules.loader import load_actions
import modules.highlighter as highlighter
from modules.match_dom import match_clicked_dom
import importlib

# Reload module to ensure latest version is used
importlib.reload(highlighter)

# Use module-level access to avoid import issues
render_highlight = highlighter.render_highlight
render_point_highlight = getattr(highlighter, 'render_point_highlight', None)

# Fallback if function doesn't exist
if render_point_highlight is None:
    import base64
    
    def render_point_highlight(image_path, x, y, radius=10):
        """Render an image with a highlighted point (circle) at x, y coordinates."""
        if image_path is None or not os.path.exists(image_path):
            st.error("❌ 스크린샷 파일이 존재하지 않습니다.")
            return

        with open(image_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode()

        html = f"""
        <div style="position: relative; display: inline-block;">
            <img src="data:image/png;base64,{img_base64}" style="max-width: 100%;">
            <div style="
                position: absolute;
                top: {y - radius}px;
                left: {x - radius}px;
                width: {radius * 2}px;
                height: {radius * 2}px;
                border: 3px solid red;
                border-radius: 50%;
                background-color: rgba(255, 0, 0, 0.3);
                pointer-events: none;">
            </div>
        </div>
        """

        st.markdown(html, unsafe_allow_html=True)

st.title("📸 스크린샷 / 클릭 하이라이트 뷰어")

json_file = "data/actions/metadata_182.json"
actions = load_actions(json_file)

idx = st.number_input("액션 선택 (index)", 0, len(actions)-1, 0)

action = actions[idx]
st.subheader("선택된 액션 정보")
st.json(action)

# metadata 파싱 (문자열이므로 JSON 파싱 필요)
metadata = None
coordinates = None
bounds = None
x, y = None, None
dom_matched = None

if "metadata" in action and action["metadata"]:
    try:
        if isinstance(action["metadata"], str):
            metadata = json.loads(action["metadata"])
        else:
            metadata = action["metadata"]
        
        coordinates = metadata.get("coordinates", {})
        
        # elementBounds 우선 사용 (클릭한 DOM 요소의 위치)
        if "elementBounds" in coordinates:
            bounds = coordinates["elementBounds"]
        
        # 좌표 추출 (우선순위: pageX/pageY > clientX/clientY > x/y)
        # pageX/pageY: 전체 페이지 기준 좌표
        # clientX/clientY: 브라우저 viewport 기준 좌표
        x = None
        y = None
        coord_type = None
        
        if "pageX" in coordinates and "pageY" in coordinates:
            x = coordinates["pageX"]
            y = coordinates["pageY"]
            coord_type = "page"
        elif "clientX" in coordinates and "clientY" in coordinates:
            x = coordinates["clientX"]
            y = coordinates["clientY"]
            coord_type = "client"
        elif "x" in coordinates and "y" in coordinates:
            x = coordinates["x"]
            y = coordinates["y"]
            coord_type = "x/y"
        
        # DOM snapshot이 있으면 DOM 매칭 시도 (metadata는 이미 파싱됨)
        dom_snapshot = None
        if metadata:
            dom_snapshot = metadata.get("domSnapshot")
        
        if dom_snapshot and x is not None and y is not None:
            # match_clicked_dom은 metadata가 파싱된 상태를 기대하므로
            # 임시로 metadata를 업데이트
            temp_action = action.copy()
            if isinstance(temp_action.get("metadata"), str):
                temp_action["metadata"] = metadata
            
            try:
                dom_matched = match_clicked_dom(temp_action, dom_snapshot)
                if dom_matched and dom_matched.get("bounds"):
                    # DOM에서 찾은 bounds 사용 (elementBounds가 없을 때)
                    if not bounds:
                        bounds = dom_matched["bounds"]
            except Exception as e:
                st.warning(f"⚠️ DOM 매칭 오류: {e}")
                
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        st.warning(f"⚠️ metadata 파싱 오류: {e}")

image_path = action.get("screenshot_real_path", None)

# 이미지 표시
if image_path:
    # 경로 정규화 (백슬래시 통일)
    image_path = os.path.normpath(image_path)
    
    if os.path.exists(image_path):
        if bounds:
            st.subheader("🟥 클릭 하이라이트 이미지 (Element Bounds)")
            
            # 이미지 컨테이너
            with st.container():
                # action 전체를 전달하여 metadata에서 정보 추출
                render_highlight(action)
            
            # 정보를 컬럼으로 나누어 표시
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # elementBounds 정보 표시
                bounds_info = f"**Element Bounds (클릭한 DOM 요소의 위치):**\n"
                bounds_info += f"- 위치: top={bounds.get('top')}px, left={bounds.get('left')}px\n"
                bounds_info += f"- 크기: width={bounds.get('width')}px, height={bounds.get('height')}px"
                
                # 비율 정보가 있으면 표시
                if 'topRatio' in bounds:
                    bounds_info += f"\n- 비율: topRatio={bounds.get('topRatio'):.4f}, leftRatio={bounds.get('leftRatio'):.4f}"
                    bounds_info += f", widthRatio={bounds.get('widthRatio'):.4f}, heightRatio={bounds.get('heightRatio'):.4f}"
                
                st.info(bounds_info)
            
            with col2:
                if dom_matched:
                    st.info(f"**DOM 매칭 결과:**\n- 태그: `{dom_matched.get('tag')}`\n- 텍스트: `{dom_matched.get('text', 'N/A')}`")
        elif x is not None and y is not None:
            st.subheader("🟥 클릭 하이라이트 이미지 (좌표)")
            
            # 이미지 컨테이너
            with st.container():
                render_point_highlight(image_path, x, y)
            
            # 정보를 컬럼으로 나누어 표시
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # 좌표 정보 상세 표시
                coord_info = f"**클릭 좌표:** x={x}, y={y}"
                if coord_type == "page":
                    coord_info += " (전체 페이지 기준)"
                elif coord_type == "client":
                    coord_info += " (viewport 기준)"
                
                # 모든 좌표 정보 표시
                coord_details = []
                if "pageX" in coordinates:
                    coord_details.append(f"pageX={coordinates['pageX']}, pageY={coordinates['pageY']}")
                if "clientX" in coordinates:
                    coord_details.append(f"clientX={coordinates['clientX']}, clientY={coordinates['clientY']}")
                if coord_details:
                    coord_info += f"\n\n**상세 좌표:**\n- " + "\n- ".join(coord_details)
                
                st.info(coord_info)
            
            with col2:
                if dom_matched:
                    st.info(f"**DOM 매칭 결과:**\n- 태그: `{dom_matched.get('tag')}`\n- 텍스트: `{dom_matched.get('text', 'N/A')}`")
        else:
            st.subheader("📸 스크린샷")
            # 이미지 컨테이너
            with st.container():
                st.image(image_path, use_container_width=True)
            if not coordinates:
                st.warning("❗ 좌표 정보가 없는 액션입니다.")
    else:
        st.error(f"❌ 스크린샷 파일을 찾을 수 없습니다")
        st.info(f"**경로:** `{image_path}`")
        # 디렉토리 확인
        dir_path = os.path.dirname(image_path)
        if os.path.exists(dir_path):
            st.info(f"✅ 디렉토리는 존재합니다: `{dir_path}`")
            # 디렉토리 내 파일 목록 확인
            try:
                files = [f for f in os.listdir(dir_path) if f.endswith('.png')]
                if files:
                    st.info(f"📁 디렉토리 내 PNG 파일 수: {len(files)}개")
                    st.info(f"찾는 파일: `{os.path.basename(image_path)}`")
            except Exception as e:
                st.warning(f"⚠️ 디렉토리 읽기 오류: {e}")
        else:
            st.error(f"❌ 디렉토리도 존재하지 않습니다: `{dir_path}`")
else:
    st.warning("⚠️ 스크린샷 경로가 지정되지 않았습니다.")
