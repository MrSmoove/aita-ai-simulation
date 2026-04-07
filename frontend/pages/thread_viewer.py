import streamlit as st
import requests

API_BASE = st.secrets.get("api_base", "http://localhost:8000")


def app():
    st.header("Thread viewer")
    run_id = st.text_input("Enter run_id")
    if st.button("Load thread") and run_id:
        r = requests.get(f"{API_BASE}/simulate/run/{run_id}")
        if r.status_code != 200:
            st.error("Run not found yet")
            return
        data = r.json()
        st.subheader(f"Post: {data['post']['title']}")
        st.markdown(data["post"]["body"])
        for action in data["timeline"]:
            st.write(f"{action['step']} | {action['role']} | {action['agent_id']}: {action['text']}")