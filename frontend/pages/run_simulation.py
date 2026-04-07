import streamlit as st
import requests
import json
from pydantic import BaseModel

API_BASE = st.secrets.get("api_base", "http://localhost:8000")


def app():
    st.header("Run simulation")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Load post")
        uploaded = st.file_uploader("Upload JSON post (post_id,title,body,...)")
        if uploaded:
            post = json.loads(uploaded.read())
            st.json(post)
        else:
            if st.button("Load sample post from backend"):
                r = requests.get(f"{API_BASE}/posts/sample")
                post = r.json()
                st.session_state["post"] = post
                st.experimental_rerun()
        post = st.session_state.get("post")

    with col2:
        st.subheader("Simulation config")
        model = st.text_input("Model name", value="oasis-small")
        num_commenters = st.number_input("Number of commenter agents", min_value=1, max_value=20, value=3)
        max_steps = st.number_input("Max steps", min_value=1, max_value=50, value=3)
        op_enabled = st.checkbox("Enable OP replies", value=True)

    if st.button("Start simulation") and post:
        config = {
            "model_name": model,
            "num_commenters": int(num_commenters),
            "max_steps": int(max_steps),
            "op_enabled": bool(op_enabled),
        }
        r = requests.post(f"{API_BASE}/simulate/run", json={"post": post, "config": config})
        st.write(r.json())
        st.success("Simulation started (runs in background). Check Results after a few seconds.")