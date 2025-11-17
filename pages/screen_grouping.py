import sys
import os
import json
import base64
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
from PIL import Image
from modules.loader import load_actions
from modules.grouping import group_screens
from modules.match_dom import match_clicked_dom

# ==========================
# CSS (박스, 번호 스타일)
# ==========================
if not hasattr(st.session_state, 'screen_grouping_css_injected'):
    st.markdown("""
    <style>
    .original-img {
        max-width: none !important;
    }
    .overlay-wrapper {
        position: relative;
        display: inline-block;
    }
    .overlay-box {
        position: absolute;
        border: 3px solid red;
        pointer-events: none;
        box-sizing: border-box;
    }
    .overlay-label {
        position: absolute;
        background: red;
        color: white;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        line-height: 20px;
        text-align: center;
        font-weight: bold;
        pointer-events: none;
    }
    </style>
    """, unsafe_allow_html=True)
    st.session_state.screen_grouping_css_injected = True


# ==========================
# Utility
# ==========================
def parse_metadata(action):
    m = action.get("metadata")
    if isinstance(m, str):
        try:
            return json.loads(m)
        except:
            return {}
    return m or {}


# ==========================
# Renderer: 다중 박스 + 번호
# ==========================
def render_grouped_highlight(image_path, actions):
    """하나의 화면 안의 여러 액션을 동시에 표시."""

    # (1) elementBounds가 있는 액션만 필터링
    valid_actions = []
    for action in actions:
        meta = parse_metadata(action)
        coords = meta.get("coordinates", {})
        bounds = coords.get("elementBounds")
        if bounds:
            valid_actions.append(action)
    
    if len(valid_actions) == 0:
        st.warning("⚠️ elementBounds가 있는 액션이 없습니다.")
        return

    # (2) 실제 이미지 크기 읽기 (PIL 사용 - 초기값용)
    try:
        with Image.open(image_path) as pil_img:
            image_width = pil_img.width
            image_height = pil_img.height
    except Exception as e:
        st.error(f"❌ 이미지 읽기 오류: {e}")
        return

    # (3) 첫 액션에서 viewport 크기 획득
    meta0 = parse_metadata(valid_actions[0])
    coords0 = meta0.get("coordinates", {})

    vp_w = int(coords0.get("viewportWidth", 1859))
    vp_h = int(coords0.get("viewportHeight", 910))

    # (4) 이미지 base64 변환
    with open(image_path, "rb") as f:
        img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode()

    # (5) 고유 ID 생성 (이미지 경로 기반)
    wrapper_id = f"wrapper-{hash(image_path)}"
    img_id = f"img-{hash(image_path)}"

    # (6) elementBounds 데이터 수집 (JavaScript에서 사용)
    bounds_data = []
    for idx, action in enumerate(valid_actions):
        meta = parse_metadata(action)
        coords = meta.get("coordinates", {})
        bounds = coords.get("elementBounds", {})

        orig_top = bounds.get("top", 0)
        orig_left = bounds.get("left", 0)
        orig_width = bounds.get("width", 0)
        orig_height = bounds.get("height", 0)

        if orig_width <= 0 or orig_height <= 0:
            continue

        bounds_data.append({
            'idx': idx + 1,
            'top': orig_top,
            'left': orig_left,
            'width': orig_width,
            'height': orig_height
        })

    # (7) overlay HTML 구성 (초기값으로 설정, JavaScript에서 재계산)
    overlay_html = ""
    for data in bounds_data:
        box_id = f"box-{wrapper_id}-{data['idx']}"
        label_id = f"label-{wrapper_id}-{data['idx']}"
        
        # 초기값 (viewport 기준으로 설정, JS에서 재계산)
        overlay_html += f'<div id="{box_id}" class="overlay-box" style="display:none;"></div>'
        overlay_html += f'<div id="{label_id}" class="overlay-label" style="display:none;">{data["idx"]}</div>'

    # (8) JavaScript로 실제 렌더링 크기 기반 스케일링
    bounds_json = json.dumps(bounds_data)
    
    js_code = f"""
    <script>
    (function() {{
        const wrapper = document.getElementById('{wrapper_id}');
        const img = document.getElementById('{img_id}');
        
        if (!wrapper || !img) {{
            console.error('요소를 찾을 수 없습니다');
            return;
        }}
        
        const viewportWidth = {vp_w};
        const viewportHeight = {vp_h};
        const boundsData = {bounds_json};
        
        function adjustHighlights() {{
            // 이미지가 완전히 로드되지 않았으면 대기
            if (!img.complete || img.naturalWidth === 0 || img.naturalHeight === 0) {{
                setTimeout(adjustHighlights, 100);
                return;
            }}
            
            // 실제 렌더링된 이미지 크기 가져오기
            let imgDisplayWidth = img.offsetWidth || img.clientWidth;
            let imgDisplayHeight = img.offsetHeight || img.clientHeight;
            
            if (imgDisplayWidth === 0 || imgDisplayHeight === 0) {{
                const rect = img.getBoundingClientRect();
                imgDisplayWidth = rect.width;
                imgDisplayHeight = rect.height;
            }}
            
            if (imgDisplayWidth === 0 || imgDisplayHeight === 0) {{
                imgDisplayWidth = img.naturalWidth;
                imgDisplayHeight = img.naturalHeight;
            }}
            
            // 스케일 계산: 실제 렌더링 크기 / viewport 크기
            const scaleX = imgDisplayWidth / viewportWidth;
            const scaleY = imgDisplayHeight / viewportHeight;
            
            console.log('하이라이트 스케일링:', {{
                imgDisplay: `${{imgDisplayWidth}}x${{imgDisplayHeight}}`,
                viewport: `${{viewportWidth}}x${{viewportHeight}}`,
                scale: `${{scaleX.toFixed(4)}}x${{scaleY.toFixed(4)}}`
            }});
            
            // 각 박스와 라벨 업데이트
            boundsData.forEach(function(data) {{
                const boxId = 'box-{wrapper_id}-' + data.idx;
                const labelId = 'label-{wrapper_id}-' + data.idx;
                
                const box = document.getElementById(boxId);
                const label = document.getElementById(labelId);
                
                if (!box || !label) return;
                
                // elementBounds를 실제 렌더링 크기로 스케일링
                const drawTop = data.top * scaleY;
                const drawLeft = data.left * scaleX;
                const drawWidth = data.width * scaleX;
                const drawHeight = data.height * scaleY;
                
                // 박스 설정
                box.style.top = drawTop + 'px';
                box.style.left = drawLeft + 'px';
                box.style.width = drawWidth + 'px';
                box.style.height = drawHeight + 'px';
                box.style.display = 'block';
                
                // 라벨 설정
                const labelTop = Math.max(0, drawTop - 10);
                const labelLeft = Math.max(0, drawLeft - 10);
                label.style.top = labelTop + 'px';
                label.style.left = labelLeft + 'px';
                label.style.display = 'block';
            }});
        }}
        
        // 이미지 로드 완료 후 조정
        if (img.complete) {{
            setTimeout(adjustHighlights, 100);
        }} else {{
            img.addEventListener('load', function() {{
                setTimeout(adjustHighlights, 100);
            }});
        }}
        
        // DOM이 완전히 렌더링될 때까지 여러 번 시도
        let attempts = 0;
        const maxAttempts = 20;
        const checkInterval = setInterval(function() {{
            attempts++;
            const width = img.offsetWidth || img.getBoundingClientRect().width;
            if (width > 0 || attempts >= maxAttempts) {{
                clearInterval(checkInterval);
                adjustHighlights();
            }}
        }}, 100);
    }})();
    </script>
    """

    # (9) 전체 HTML 구성
    html = f"""
<div id="{wrapper_id}" class="overlay-wrapper" style="position:relative; width:{image_width}px; height:{image_height}px;">
    <img id="{img_id}" class="original-img"
         src="data:image/png;base64,{img_b64}"
         style="width:{image_width}px; height:{image_height}px; max-width:none !important; display:block;">
    {overlay_html}
</div>
{js_code}
"""

    st.markdown(html, unsafe_allow_html=True)
    
    # 디버깅 정보
    st.caption(f"🔍 디버깅: 이미지 원본={image_width}×{image_height}px, Viewport={vp_w}×{vp_h}px, 박스 개수={len(bounds_data)}개")



# ==========================
# MAIN UI
# ==========================
st.title("🧩 그룹 화면 다중 DOM 하이라이트 뷰어")

json_file = "data/actions/metadata_182.json"
actions = load_actions(json_file)

screens = group_screens(actions)
st.success(f"총 {len(screens)}개의 화면으로 묶였습니다.")


# ==========================
# 화면(그룹) 하나씩 렌더링
# ==========================
for screen_idx, screen in enumerate(screens):

    with st.expander(f"📄 Screen {screen_idx + 1}: {screen['screen_name']}", expanded=False):

        actions_in_screen = screen["actions"]
        st.write(f"🔸 액션 개수: **{len(actions_in_screen)}**")

        # 이미지 찾기
        image_path = screen.get("representative_image")
        if not image_path:
            for a in actions_in_screen:
                p = a.get("screenshot_real_path")
                if p and os.path.exists(p):
                    image_path = p
                    break

        if image_path and os.path.exists(image_path):
            render_grouped_highlight(image_path, actions_in_screen)
        else:
            st.error("❌ 이미지 없음")
            continue

        # ================================
        # 상세 액션 정보
        # ================================
        st.write("### 📝 액션 상세 정보")

        for idx, action in enumerate(actions_in_screen):
            meta = parse_metadata(action)
            coords = meta.get("coordinates", {})
            bounds = coords.get("elementBounds", {})

            st.markdown(f"""
**[{idx+1}] 액션 요약**
- action_type: `{action.get("action_type")}`
- description: `{action.get("description")}`
- tag_name: `{action.get("tag_name")}`
- class_name: `{action.get("class_name")}`
- text_content: `{action.get("text_content")}`
- label: `{meta.get("label")}`
- elementBounds: `{bounds}`
""")
