import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
from modules.loader import load_actions
from modules.grouping import group_screens


st.title("📄 메뉴얼 자동 생성")

json_file = "data/actions/metadata_182.json"
actions = load_actions(json_file)

screens = group_screens(actions)

manual_md = ""

for s in screens:
    manual_md += f"## 📘 {s['screen_name']}\n"
    manual_md += f"대표 이미지: `{s['representative_image']}`\n\n"

    for a in s["actions"]:
        manual_md += f"- `{a['action_type']}` | seq:{a['action_sequence']}\n"

    manual_md += "\n---\n"

st.markdown(manual_md)
