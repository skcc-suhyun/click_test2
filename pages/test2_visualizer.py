"""
test2_visualizer.py - test2.py 분석 결과를 Streamlit으로 시각화

기능:
- 이미지 클러스터링 결과 시각화
- 각 클러스터의 대표 이미지와 클릭 좌표 표시
- DOM 매칭 정보 표시
- 이미지와 DOM 매칭 정도 확인
"""

import streamlit as st
import streamlit.components.v1 as components
import sys
import os
import json
import importlib
import base64
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
import imagehash
import numpy as np
from skimage.metrics import structural_similarity as ssim

# CSS 인젝션 (한 번만)
if not hasattr(st.session_state, 'test2_visualizer_css_injected'):
    st.markdown("""
    <style>
    .highlight-img {
        max-width: 100% !important;
        max-height: 100vh !important;
        width: auto !important;
        height: auto !important;
        object-fit: contain !important;
        position: relative !important;
        z-index: 1 !important;
    }
    .highlight-wrapper {
        position: relative !important;
        display: inline-block !important;
        max-width: 100% !important;
        max-height: 100vh !important;
    }
    .highlight-box {
        position: absolute !important;
        border: 4px solid red !important;
        background-color: rgba(255, 0, 0, 0.3) !important;
        pointer-events: none !important;
        box-sizing: border-box !important;
        z-index: 10 !important;
    }
    .highlight-label {
        position: absolute !important;
        background: white !important;
        color: red !important;
        border: 1px solid red !important;
        width: 24px !important;
        height: 24px !important;
        border-radius: 50% !important;
        line-height: 24px !important;
        text-align: center !important;
        font-weight: bold !important;
        font-size: 12px !important;
        pointer-events: none !important;
        z-index: 20 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    st.session_state.test2_visualizer_css_injected = True

# 상위 디렉터리를 sys.path에 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.loader import load_actions
from modules.match_dom import match_clicked_dom

# test2 모듈을 동적으로 import하고 reload (Streamlit 캐시 문제 해결)
import pages.test2 as test2_module
importlib.reload(test2_module)

from pages.test2 import (
    UIScreenshotAnalyzer,
    Action,
    ScreenCluster,
    safe_parse_metadata,
    load_image,
    compute_phash,
    phash_distance,
    calc_ssim,
)

st.set_page_config(
    page_title="화면 그룹핑 & DOM 매칭 분석",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🖼️ 화면 그룹핑 & DOM 매칭 분석")
st.markdown("---")

# 사이드바 설정
with st.sidebar:
    st.header("⚙️ 설정")
    
    # JSON 파일 선택
    json_files = []
    json_dir = os.path.join(os.path.dirname(__file__), "..", "data", "actions")
    if os.path.exists(json_dir):
        json_files = [f for f in os.listdir(json_dir) if f.endswith(".json")]
    
    if json_files:
        selected_json = st.selectbox(
            "JSON 파일 선택",
            json_files,
            index=0 if json_files else None
        )
        json_path = os.path.join(json_dir, selected_json)
    else:
        json_path = st.text_input(
            "JSON 파일 경로",
            value="data/actions/metadata_182.json"
        )
    
    st.markdown("---")
    st.subheader("클러스터링 파라미터")
    
    phash_threshold = st.slider(
        "pHash 임계값",
        min_value=5,
        max_value=30,
        value=18,
        help="작을수록 엄격한 매칭 (기본: 18)"
    )
    
    ssim_threshold = st.slider(
        "SSIM 임계값",
        min_value=0.80,
        max_value=0.99,
        value=0.95,
        step=0.01,
        help="클수록 엄격한 매칭 (기본: 0.95)"
    )
    
    st.markdown("---")
    
    filter_no_clicks = st.checkbox(
        "클릭이 없는 클러스터 제외",
        value=True,
        help="클릭이 0회인 클러스터는 결과에서 제외합니다"
    )
    
    st.markdown("---")
    
    if st.button("🔄 분석 시작", type="primary", use_container_width=True):
        st.session_state.analyze_clicked = True
        st.session_state.json_path = json_path
        st.session_state.phash_threshold = phash_threshold
        st.session_state.ssim_threshold = ssim_threshold
        st.session_state.filter_no_clicks = filter_no_clicks

# 분석 실행
if st.session_state.get("analyze_clicked", False):
    json_path = st.session_state.get("json_path", json_path)
    phash_threshold = st.session_state.get("phash_threshold", phash_threshold)
    ssim_threshold = st.session_state.get("ssim_threshold", ssim_threshold)
    filter_no_clicks = st.session_state.get("filter_no_clicks", True)
    
    if not os.path.exists(json_path):
        st.error(f"❌ JSON 파일을 찾을 수 없습니다: {json_path}")
        st.stop()
    
    # 진행 상황 표시
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 분석기 초기화 및 실행
    with st.spinner("분석 중..."):
        analyzer = UIScreenshotAnalyzer(
            json_path=json_path,
            phash_threshold=phash_threshold,
            ssim_threshold=ssim_threshold,
            filter_no_clicks=filter_no_clicks,
        )
        
        status_text.text("[1/6] 액션 로드 중...")
        progress_bar.progress(1/6)
        analyzer.load_actions()
        
        status_text.text("[2/6] 스크린샷 경로 수집 중...")
        progress_bar.progress(2/6)
        analyzer.collect_screenshot_paths()
        
        status_text.text("[3/6] 이미지 로드 및 pHash 계산 중...")
        progress_bar.progress(3/6)
        analyzer.load_images_and_hashes()
        
        status_text.text("[4/6] 이미지 클러스터링 중...")
        progress_bar.progress(4/6)
        analyzer.cluster_images()
        
        status_text.text("[5/6] 화면별 요약 정보 생성 중...")
        progress_bar.progress(5/6)
        analyzer.build_screen_summary()
        
        status_text.text("[6/6] 완료!")
        progress_bar.progress(1.0)
    
    # 결과를 세션 상태에 저장
    st.session_state.analyzer = analyzer
    st.session_state.analysis_complete = True
    
    progress_bar.empty()
    status_text.empty()

# 결과 표시
if st.session_state.get("analysis_complete", False):
    analyzer = st.session_state.analyzer
    
    # 전체 통계
    total_images = sum(len(sc.image_paths) for sc in analyzer.clusters)
    total_actions = sum(len(sc.actions) for sc in analyzer.clusters)
    total_clicks = sum(len([a for a in sc.actions if a.coordinates]) for sc in analyzer.clusters)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("총 클러스터 수", f"{len(analyzer.clusters)}개")
    with col2:
        st.metric("총 이미지 수", f"{total_images}개")
    with col3:
        st.metric("총 액션 수", f"{total_actions}개")
    with col4:
        st.metric("총 클릭 횟수", f"{total_clicks}회")
    
    st.markdown("---")
    
    # 클러스터 선택
    cluster_options = [f"Cluster {sc.cluster_id} ({len(sc.actions)}개 액션, {len(sc.image_paths)}개 이미지)" 
                       for sc in analyzer.clusters]
    selected_cluster_idx = st.selectbox(
        "클러스터 선택",
        range(len(analyzer.clusters)),
        format_func=lambda x: cluster_options[x]
    )
    
    if selected_cluster_idx is not None:
        cluster = analyzer.clusters[selected_cluster_idx]
        
        st.markdown("---")
        st.subheader(f"📊 Cluster {cluster.cluster_id} 상세 정보")
        
        # 기본 정보
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"**포함 이미지 수:** {len(cluster.image_paths)}개")
        with col2:
            click_count = len([a for a in cluster.actions if a.coordinates])
            st.info(f"**클릭 횟수:** {click_count}회")
        with col3:
            st.info(f"**포함 액션 수:** {len(cluster.actions)}개")
        
        # 대표 이미지 표시 (하이라이트 포함 - screen_grouping.py 방식)
        st.markdown("### 🖼️ 대표 이미지")
        if os.path.exists(cluster.representative_image):
            # 클러스터의 모든 클릭 액션 가져오기 (대표 이미지에 모두 표시)
            all_click_actions = [a for a in cluster.actions if a.coordinates]
            
            # 유효한 액션 필터링 (elementBounds 또는 x, y 좌표가 있는 액션)
            valid_actions = []
            for action in all_click_actions:
                if not action.coordinates:
                    continue
                coords = action.coordinates or {}
                bounds = coords.get("elementBounds")
                x = coords.get("pageX") or coords.get("clientX") or coords.get("x")
                y = coords.get("pageY") or coords.get("clientY") or coords.get("y")
                
                if bounds or (x is not None and y is not None):
                    valid_actions.append(action)
            
            if len(valid_actions) > 0:
                # 이미지 크기 읽기
                try:
                    with Image.open(cluster.representative_image) as pil_img:
                        image_width = pil_img.width
                        image_height = pil_img.height
                except Exception as e:
                    st.error(f"❌ 이미지 읽기 오류: {e}")
                    image_width = 1920
                    image_height = 1080
                
                # 첫 액션에서 viewport 크기 획득
                first_coords = valid_actions[0].coordinates or {}
                vp_w = int(first_coords.get("viewportWidth", image_width))
                vp_h = int(first_coords.get("viewportHeight", image_height))
                
                # 이미지 base64 변환
                with open(cluster.representative_image, "rb") as f:
                    img_bytes = f.read()
                    img_b64 = base64.b64encode(img_bytes).decode()
                
                # 고유 ID 생성
                wrapper_id = f"wrapper-{abs(hash(cluster.representative_image))}-{cluster.cluster_id}"
                img_id = f"img-{abs(hash(cluster.representative_image))}-{cluster.cluster_id}"
                
                # 하이라이트 데이터 수집 (screen_grouping.py 방식)
                bounds_data = []
                for idx, action in enumerate(valid_actions):
                    coords = action.coordinates or {}
                    bounds = coords.get("elementBounds", {})
                    
                    # elementBounds 우선 사용 (ratio 기반)
                    if bounds:
                        top_ratio = bounds.get("topRatio")
                        left_ratio = bounds.get("leftRatio")
                        width_ratio = bounds.get("widthRatio")
                        height_ratio = bounds.get("heightRatio")
                        
                        if all(r is not None for r in [top_ratio, left_ratio, width_ratio, height_ratio]):
                            bounds_data.append({
                                'idx': idx + 1,
                                'type': 'bounds',
                                'topRatio': top_ratio,
                                'leftRatio': left_ratio,
                                'widthRatio': width_ratio,
                                'heightRatio': height_ratio
                            })
                    else:
                        # x, y 좌표 사용
                        x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
                        y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
                        
                        if x is not None and y is not None:
                            bounds_data.append({
                                'idx': idx + 1,
                                'type': 'point',
                                'top': y - 10,
                                'left': x - 10,
                                'width': 20,
                                'height': 20,
                                'x': x,
                                'y': y
                            })
                
                # overlay HTML 구성
                overlay_html = ""
                for data in bounds_data:
                    box_id = f"box-{wrapper_id}-{data['idx']}"
                    label_id = f"label-{wrapper_id}-{data['idx']}"
                    
                    # 초기값 계산
                    if data.get('type') == 'point':
                        scale_x_init = image_width / vp_w if vp_w > 0 else 1.0
                        scale_y_init = image_height / vp_h if vp_h > 0 else 1.0
                        center_x = data.get('x', 0) * scale_x_init
                        center_y = data.get('y', 0) * scale_y_init
                        box_size = 30
                        init_left = center_x - box_size / 2
                        init_top = center_y - box_size / 2
                        init_width = box_size
                        init_height = box_size
                    else:
                        top_ratio = data.get('topRatio', 0)
                        left_ratio = data.get('leftRatio', 0)
                        width_ratio = data.get('widthRatio', 0)
                        height_ratio = data.get('heightRatio', 0)
                        
                        init_top = top_ratio * image_height
                        init_left = left_ratio * image_width
                        init_width = width_ratio * image_width
                        init_height = height_ratio * image_height
                    
                    overlay_html += f'<div id="{box_id}" class="highlight-box" style="position:absolute!important;top:{init_top}px!important;left:{init_left}px!important;width:{init_width}px!important;height:{init_height}px!important;border:4px solid red!important;background-color:rgba(255,0,0,0.5)!important;box-sizing:border-box!important;pointer-events:none!important;z-index:10!important;display:block!important;"></div>'
                    label_top_init = max(0, init_top - 15)
                    label_left_init = max(0, init_left - 15)
                    overlay_html += f'<div id="{label_id}" class="highlight-label" style="position:absolute!important;top:{label_top_init}px!important;left:{label_left_init}px!important;background:white!important;color:red!important;border:1px solid red!important;width:12px!important;height:12px!important;border-radius:50%!important;line-height:12px!important;text-align:center!important;font-weight:bold!important;font-size:7px!important;z-index:20!important;display:block!important;">{data["idx"]}</div>'
                
                # JavaScript로 스케일링 (screen_grouping.py 방식)
                bounds_json = json.dumps(bounds_data)
                js_code = f"""
                <script>
                (function() {{
                    const wrapperId = '{wrapper_id}';
                    const wrapper = document.getElementById(wrapperId);
                    const imgId = '{img_id}';
                    const img = document.getElementById(imgId);
                    
                    if (!wrapper || !img) {{
                        console.error('요소를 찾을 수 없습니다:', {{wrapperId, imgId}});
                        return;
                    }}
                    
                    const viewportWidth = {vp_w};
                    const viewportHeight = {vp_h};
                    const boundsData = {bounds_json};
                    
                    function adjustHighlights() {{
                        if (!img.complete || img.naturalWidth === 0 || img.naturalHeight === 0) {{
                            setTimeout(adjustHighlights, 500);
                            return;
                        }}
                        
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
                        
                        const scaleX = imgDisplayWidth / viewportWidth;
                        const scaleY = imgDisplayHeight / viewportHeight;
                        
                        boundsData.forEach(function(data) {{
                            const boxId = 'box-' + wrapperId + '-' + data.idx;
                            const labelId = 'label-' + wrapperId + '-' + data.idx;
                            
                            const box = document.getElementById(boxId);
                            const label = document.getElementById(labelId);
                            
                            if (!box || !label) return;
                            
                            let drawTop, drawLeft, drawWidth, drawHeight;
                            
                            if (data.type === 'point') {{
                                const centerX = data.x * scaleX;
                                const centerY = data.y * scaleY;
                                const boxSize = 20;
                                drawLeft = centerX - boxSize / 2;
                                drawTop = centerY - boxSize / 2;
                                drawWidth = boxSize;
                                drawHeight = boxSize;
                                box.style.setProperty('border-radius', '50%', 'important');
                            }} else {{
                                drawTop = data.topRatio * imgDisplayHeight;
                                drawLeft = data.leftRatio * imgDisplayWidth;
                                drawWidth = data.widthRatio * imgDisplayWidth;
                                drawHeight = data.heightRatio * imgDisplayHeight;
                                box.style.setProperty('border-radius', '0%', 'important');
                            }}
                            
                            box.style.setProperty('top', drawTop + 'px', 'important');
                            box.style.setProperty('left', drawLeft + 'px', 'important');
                            box.style.setProperty('width', Math.max(10, drawWidth) + 'px', 'important');
                            box.style.setProperty('height', Math.max(10, drawHeight) + 'px', 'important');
                            box.style.setProperty('display', 'block', 'important');
                            box.style.setProperty('border', '4px solid #ff0000', 'important');
                            box.style.setProperty('background-color', 'rgba(255, 0, 0, 0.5)', 'important');
                            box.style.setProperty('z-index', '100', 'important');
                            box.style.setProperty('opacity', '1', 'important');
                            
                            // 라벨 설정 (screen_grouping.py와 동일)
                            const labelTop = Math.max(0, drawTop - 10);
                            const labelLeft = Math.max(0, drawLeft - 10);
                            label.style.setProperty('top', labelTop + 'px', 'important');
                            label.style.setProperty('left', labelLeft + 'px', 'important');
                            label.style.setProperty('display', 'block', 'important');
                            label.style.setProperty('position', 'absolute', 'important');
                            label.style.setProperty('z-index', '20', 'important');
                            label.style.setProperty('background', 'white', 'important');
                            label.style.setProperty('color', 'red', 'important');
                            label.style.setProperty('border', '1px solid red', 'important');
                            label.style.setProperty('width', '10px', 'important');
                            label.style.setProperty('height', '10px', 'important');
                            label.style.setProperty('border-radius', '50%', 'important');
                            label.style.setProperty('line-height', '10px', 'important');
                            label.style.setProperty('text-align', 'center', 'important');
                            label.style.setProperty('font-weight', 'bold', 'important');
                            label.style.setProperty('font-size', '6px', 'important');
                            label.style.setProperty('pointer-events', 'none', 'important');
                        }});
                    }}
                    
                    if (img.complete) {{
                        setTimeout(adjustHighlights, 500);
                    }} else {{
                        img.addEventListener('load', function() {{
                            setTimeout(adjustHighlights, 500);
                        }});
                    }}
                    
                    let attempts = 0;
                    const checkInterval = setInterval(function() {{
                        attempts++;
                        const width = img.offsetWidth || img.getBoundingClientRect().width;
                        if (width > 0 || attempts >= 50) {{
                            clearInterval(checkInterval);
                            adjustHighlights();
                            setTimeout(adjustHighlights, 1000);
                            setTimeout(adjustHighlights, 2000);
                        }}
                    }}, 200);
                }})();
                </script>
                """
                
                # 전체 HTML 구성 (screen_grouping.py와 동일한 구조)
                html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }}
        .container {{
            width: 100% !important;
            height: 100vh !important;
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            overflow: hidden !important;
        }}
        .highlight-img {{
            max-width: 100% !important;
            max-height: 100vh !important;
            width: auto !important;
            height: auto !important;
            object-fit: contain !important;
            position: relative !important;
            z-index: 1 !important;
            display: block !important;
        }}
        .highlight-wrapper {{
            position: relative !important;
            display: inline-block !important;
            max-width: 100% !important;
            max-height: 100vh !important;
        }}
        .highlight-box {{
            position: absolute !important;
            border: 4px solid red !important;
            background-color: rgba(255, 0, 0, 0.5) !important;
            pointer-events: none !important;
            box-sizing: border-box !important;
            z-index: 10 !important;
        }}
        .highlight-label {{
            position: absolute !important;
            background: white !important;
            color: red !important;
            border: 1px solid red !important;
            width: 10px !important;
            height: 10px !important;
            border-radius: 50% !important;
            line-height: 10px !important;
            text-align: center !important;
            font-weight: bold !important;
            font-size: 6px !important;
            pointer-events: none !important;
            z-index: 20 !important;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div id="{wrapper_id}" class="highlight-wrapper">
            <img id="{img_id}" class="highlight-img"
                 src="data:image/png;base64,{img_b64}">
            {overlay_html}
        </div>
    </div>
    {js_code}
</body>
</html>
                """
                
                st.info(f"대표 이미지에 {len(bounds_data)}개의 클릭 위치가 표시됩니다.")
                components.html(html, height=min(image_height + 100, 800), scrolling=False)
            else:
                # 하이라이트할 액션이 없으면 일반 이미지만 표시
                rep_img = Image.open(cluster.representative_image)
                st.image(rep_img, caption=os.path.basename(cluster.representative_image), use_container_width=True)
        else:
            st.warning(f"이미지를 찾을 수 없습니다: {cluster.representative_image}")
        
        # 클릭 좌표와 DOM 매칭 정보
        click_actions = [a for a in cluster.actions if a.coordinates]
        
        if click_actions:
            st.markdown("### 🖱️ 클릭 좌표 및 DOM 매칭")
            
            for idx, action in enumerate(click_actions, 1):
                with st.expander(f"클릭 #{idx} - Action ID: {action.action_id}, Sequence: {action.sequence}", expanded=False):
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        # 스크린샷 이미지 표시 (하이라이트 없이 일반 이미지만)
                        if action.screenshot_path and os.path.exists(action.screenshot_path):
                            img = Image.open(action.screenshot_path)
                            st.image(img, caption=f"스크린샷 - Action ID: {action.action_id}", use_container_width=True)
                        else:
                            st.warning("스크린샷을 찾을 수 없습니다.")
                    
                    with col2:
                        # 좌표 정보
                        st.markdown("**📍 좌표 정보**")
                        coords = action.coordinates or {}
                        if coords:
                            st.json(coords)
                        else:
                            st.info("좌표 정보 없음")
                        
                        # 좌표 추출 (DOM 매칭에 필요)
                        x = coords.get("pageX") or coords.get("clientX") or coords.get("x")
                        y = coords.get("pageY") or coords.get("clientY") or coords.get("y")
                        
                        # DOM 매칭 시도
                        st.markdown("**🔍 DOM 매칭 결과**")
                        dom_matched = None
                        dom_match_info = {}
                        
                        try:
                            metadata = safe_parse_metadata(action.raw.get("metadata"))
                            dom_snapshot = metadata.get("domSnapshot") if metadata else None
                            
                            if dom_snapshot and x is not None and y is not None:
                                temp_action = action.raw.copy()
                                if isinstance(temp_action.get("metadata"), str):
                                    temp_action["metadata"] = metadata
                                
                                dom_matched = match_clicked_dom(temp_action, dom_snapshot)
                                
                                if dom_matched:
                                    dom_match_info = {
                                        "태그": dom_matched.get("tag", "N/A"),
                                        "텍스트": dom_matched.get("text", "N/A")[:50] if dom_matched.get("text") else "N/A",
                                        "노드 ID": dom_matched.get("nodeId", "N/A"),
                                        "속성": dom_matched.get("attributes", {}),
                                        "경계": dom_matched.get("bounds", {})
                                    }
                                    st.success("✅ DOM 매칭 성공")
                                    st.json(dom_match_info)
                                    
                                    # 매칭 점수 계산 (간단한 휴리스틱)
                                    if dom_matched.get("bounds"):
                                        bounds = dom_matched["bounds"]
                                        bounds_x = bounds.get("left", 0) + bounds.get("width", 0) / 2
                                        bounds_y = bounds.get("top", 0) + bounds.get("height", 0) / 2
                                        
                                        # 거리 계산
                                        distance = ((x - bounds_x) ** 2 + (y - bounds_y) ** 2) ** 0.5
                                        max_distance = 100  # 임계값
                                        match_score = max(0, 100 - (distance / max_distance * 100))
                                        
                                        st.metric("매칭 점수", f"{match_score:.1f}%")
                                else:
                                    st.warning("⚠️ DOM 매칭 실패")
                        except Exception as e:
                            st.error(f"❌ DOM 매칭 오류: {e}")
                        
                        # 액션 타입
                        st.markdown("**📋 액션 정보**")
                        st.info(f"타입: {action.action_type or 'N/A'}")
                        if action.http_url:
                            st.info(f"URL: {action.http_url[:50]}...")
        
        # 포함된 이미지 목록
        st.markdown("### 📸 포함된 이미지 목록")
        if len(cluster.image_paths) > 1:
            cols = st.columns(min(3, len(cluster.image_paths)))
            for idx, img_path in enumerate(cluster.image_paths):
                col_idx = idx % 3
                with cols[col_idx]:
                    if os.path.exists(img_path):
                        img = Image.open(img_path)
                        st.image(img, caption=os.path.basename(img_path), use_container_width=True)
                    else:
                        st.warning(f"이미지 없음:\n{os.path.basename(img_path)}")
        else:
            st.info("이 클러스터에는 대표 이미지만 포함되어 있습니다.")
        
        # API URL 목록
        request_actions = [a for a in cluster.actions if a.action_type == "request"]
        urls = sorted({a.http_url for a in request_actions if a.http_url})
        if urls:
            st.markdown("### 🌐 관련 API URL")
            for url in urls:
                st.code(url, language=None)
    
else:
    st.info("👈 좌측 사이드바에서 설정을 완료하고 '분석 시작' 버튼을 클릭하세요.")

