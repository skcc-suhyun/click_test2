"""
test2_visualizer.py - test2.py 분석 결과를 Streamlit으로 시각화

기능:
- 이미지 클러스터링 결과 시각화
- 각 클러스터의 대표 이미지와 클릭 좌표 표시
- DOM 매칭 정보 표시
- 이미지와 DOM 매칭 정도 확인
"""

import streamlit as st
import sys
import os
import json
import importlib
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
import imagehash
import numpy as np
from skimage.metrics import structural_similarity as ssim

# OCR 라이브러리 (선택적)
try:
    import easyocr
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False

# OCR 리더 초기화 (캐시, 지연 로딩)
@st.cache_resource
def get_ocr_reader():
    """EasyOCR 리더 초기화 (한국어, 영어 지원) - 첫 사용 시에만 로드"""
    if not HAS_EASYOCR:
        return None
    try:
        # GPU 사용 안 함으로 설정하여 리소스 사용 최소화
        return easyocr.Reader(['ko', 'en'], gpu=False, verbose=False)
    except Exception as e:
        st.warning(f"OCR 리더 초기화 실패: {e}")
        return None

@st.cache_data(ttl=3600)  # 1시간 캐시
def extract_text_from_image(image_path: str) -> List[Dict[str, Any]]:
    """이미지에서 텍스트 추출 (리소스 최적화: 이미지 크기 축소)"""
    if not HAS_EASYOCR or not os.path.exists(image_path):
        return []
    
    try:
        reader = get_ocr_reader()
        if reader is None:
            return []
        
        original_path = image_path
        temp_path = None
        
        # 이미지 크기 축소하여 OCR 처리 시간 단축 (최대 너비 800px)
        img = Image.open(image_path)
        max_width = 800
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            # 임시 파일로 저장
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                img.save(tmp.name, 'PNG')
                temp_path = tmp.name
                image_path = temp_path
        
        results = reader.readtext(image_path, paragraph=False)
        
        # 임시 파일 삭제
        if temp_path and temp_path != original_path:
            try:
                os.unlink(temp_path)
            except:
                pass
        
        return [
            {
                "text": result[1],
                "confidence": float(result[2]),
                "bbox": result[0]  # [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
            }
            for result in results
        ]
    except Exception as e:
        st.warning(f"OCR 오류: {e}")
        return []

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
        
        # 대표 이미지 표시
        st.markdown("### 🖼️ 대표 이미지")
        if os.path.exists(cluster.representative_image):
            rep_img = Image.open(cluster.representative_image)
            st.image(rep_img, caption=os.path.basename(cluster.representative_image), use_container_width=True)
            
            # OCR로 텍스트 추출 (선택적, 버튼 클릭 시에만 실행)
            if HAS_EASYOCR:
                ocr_key = f"ocr_btn_{cluster.cluster_id}"
                if st.button("📝 텍스트 추출 (OCR)", key=ocr_key, help="이미지에서 텍스트를 추출합니다. 리소스를 많이 사용할 수 있습니다."):
                    with st.spinner("텍스트 추출 중... (이 작업은 시간이 걸릴 수 있습니다)"):
                        ocr_results = extract_text_from_image(cluster.representative_image)
                        if ocr_results:
                            st.markdown("**추출된 텍스트:**")
                            for idx, result in enumerate(ocr_results, 1):
                                confidence = result["confidence"]
                                text = result["text"]
                                color = "🟢" if confidence > 0.8 else "🟡" if confidence > 0.5 else "🔴"
                                st.markdown(f"{color} **{idx}.** `{text}` (신뢰도: {confidence:.2%})")
                            
                            # 전체 텍스트 합치기
                            all_text = " ".join([r["text"] for r in ocr_results])
                            st.markdown("---")
                            st.markdown("**전체 텍스트:**")
                            st.text_area("", all_text, height=100, key=f"ocr_text_{cluster.cluster_id}")
                        else:
                            st.info("텍스트를 찾을 수 없습니다.")
            else:
                st.info("💡 OCR 기능을 사용하려면 `pip install easyocr`를 실행하세요.")
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
                        # 스크린샷 이미지 표시
                        if action.screenshot_path and os.path.exists(action.screenshot_path):
                            img = Image.open(action.screenshot_path)
                            
                            # 클릭 좌표 표시를 위한 이미지 복사
                            img_with_marker = img.copy()
                            
                            # 좌표 추출
                            coords = action.coordinates or {}
                            x = coords.get("pageX") or coords.get("clientX") or coords.get("x")
                            y = coords.get("pageY") or coords.get("clientY") or coords.get("y")
                            
                            # 클릭 위치에 마커 그리기
                            if x is not None and y is not None:
                                from PIL import ImageDraw
                                draw = ImageDraw.Draw(img_with_marker)
                                # 빨간 원으로 클릭 위치 표시
                                radius = 10
                                draw.ellipse(
                                    [(x - radius, y - radius), (x + radius, y + radius)],
                                    fill="red",
                                    outline="darkred",
                                    width=3
                                )
                                # 십자선 그리기
                                draw.line([(x - 20, y), (x + 20, y)], fill="red", width=2)
                                draw.line([(x, y - 20), (x, y + 20)], fill="red", width=2)
                            
                            st.image(img_with_marker, caption=f"클릭 위치: ({x}, {y})", use_container_width=True)
                            
                            # OCR로 텍스트 추출 (선택적, 버튼 클릭 시에만 실행)
                            if HAS_EASYOCR:
                                ocr_click_key = f"ocr_click_btn_{action.action_id}"
                                if st.button("📝 텍스트 추출 (OCR)", key=ocr_click_key, help="이미지에서 텍스트를 추출합니다. 리소스를 많이 사용할 수 있습니다."):
                                    with st.spinner("텍스트 추출 중... (이 작업은 시간이 걸릴 수 있습니다)"):
                                        ocr_results = extract_text_from_image(action.screenshot_path)
                                        if ocr_results:
                                            st.markdown("**추출된 텍스트:**")
                                            for idx, result in enumerate(ocr_results, 1):
                                                confidence = result["confidence"]
                                                text = result["text"]
                                                color = "🟢" if confidence > 0.8 else "🟡" if confidence > 0.5 else "🔴"
                                                st.markdown(f"{color} **{idx}.** `{text}` (신뢰도: {confidence:.2%})")
                                            
                                            # 전체 텍스트 합치기
                                            all_text = " ".join([r["text"] for r in ocr_results])
                                            st.markdown("---")
                                            st.markdown("**전체 텍스트:**")
                                            st.text_area("", all_text, height=100, key=f"ocr_click_{action.action_id}")
                                        else:
                                            st.info("텍스트를 찾을 수 없습니다.")
                        else:
                            st.warning("스크린샷을 찾을 수 없습니다.")
                    
                    with col2:
                        # 좌표 정보
                        st.markdown("**📍 좌표 정보**")
                        if action.coordinates:
                            coords = action.coordinates
                            st.json(coords)
                        else:
                            st.info("좌표 정보 없음")
                        
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

