"""Agent UI (Streamlit) at http://agent.local: chat with the agent and see every tool call."""

import os
import uuid

import httpx
import streamlit as st

AGENT_URL = os.environ.get("AGENT_URL", "http://agent.agent.svc.cluster.local:8000")

st.set_page_config(page_title="Local AI agent", page_icon="🗂️")
st.title("Local AI agent")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.history = []  # [{"role", "content", "steps", "seconds"}]

with st.sidebar:
    try:
        info = httpx.get(f"{AGENT_URL}/tools", timeout=30).json()
        st.caption(f"Model alias: `{info['model']}`")
        st.caption("Tools: " + ", ".join(f"`{t['name']}`" for t in info["tools"]))
    except Exception as e:
        st.warning(f"Agent not reachable: {e}")
    if st.button("New conversation"):
        st.session_state.clear()
        st.rerun()
    st.caption("Runs on a CPU: answers that use tools take 20–90 s.")


def show(msg):
    with st.chat_message(msg["role"]):
        for s in msg.get("steps", []):
            with st.expander(f"🔧 {s['tool']}({', '.join(f'{k}={v!r}' for k, v in s['args'].items())})"):
                st.code(s["result"][:4000] or "(no output)", language=None)
        st.markdown(msg["content"])
        if "seconds" in msg:
            st.caption(f"{msg['seconds']} s")


for m in st.session_state.history:
    show(m)

if prompt := st.chat_input("Ask about your files…"):
    user = {"role": "user", "content": prompt}
    st.session_state.history.append(user)
    show(user)
    with st.spinner("Thinking…"):
        try:
            r = httpx.post(
                f"{AGENT_URL}/chat",
                json={"message": prompt, "thread_id": st.session_state.thread_id},
                timeout=900,
            )
            r.raise_for_status()
            d = r.json()
            reply = {"role": "assistant", "content": d["answer"], "steps": d["steps"], "seconds": d["seconds"]}
        except Exception as e:
            reply = {"role": "assistant", "content": f"⚠️ {e}"}
    st.session_state.history.append(reply)
    show(reply)
