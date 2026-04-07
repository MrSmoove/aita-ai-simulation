import streamlit as st
st.set_page_config(page_title="AITA Simulation", layout="wide")

st.title("AITA Simulation Prototype")

st.sidebar.header("Navigation")
page = st.sidebar.radio("Go to", ["Run simulation", "Thread viewer", "Results"])

if page == "Run simulation":
    from frontend.pages import run_simulation as rs
    rs.app()
elif page == "Thread viewer":
    from frontend.pages import thread_viewer as tv
    tv.app()
else:
    from frontend.pages import results as res
    res.app()