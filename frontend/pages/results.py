import streamlit as st
import requests
import json

API_BASE = st.secrets.get("api_base", "http://localhost:8000")


def app():
    st.header("Results")
    run_id = st.text_input("run_id to fetch")
    if st.button("Fetch") and run_id:
        r = requests.get(f"{API_BASE}/simulate/run/{run_id}")
        if r.status_code != 200:
            st.error("Not found")
            return
        data = r.json()
        st.json(data)
        if st.button("Download JSON"):
            st.download_button("Download run JSON", json.dumps(data, indent=2), file_name=f"{run_id}.json")