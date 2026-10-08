"""Agent UI (Streamlit) at https://agent.ai.local: the agent chat, and the Models page to pick
which model runs (one at a time)."""

import streamlit as st

st.set_page_config(page_title="Local AI agent", page_icon="🗂️")
st.navigation([
    st.Page("chat.py", title="Agent", icon="🗂️", default=True),
    st.Page("models_page.py", title="Models", icon="🧠", url_path="models"),
]).run()
