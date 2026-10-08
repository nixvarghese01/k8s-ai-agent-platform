"""Models page: which chat model runs, switch to another, download or delete one."""

import time

import pandas as pd
import streamlit as st

import models

st.title("Models")
st.caption("One chat model runs at a time: chat, the agent and n8n all use it. The embedding model for "
           "document search stays loaded next to it.")

try:
    kube = models.Kube()
    active = kube.active()
    have = models.installed()
    loaded = models.in_memory()
except Exception as e:
    st.error(f"Can't reach Ollama or Kubernetes: {e}")
    st.stop()

chat_models = [m for m in have if not models.is_embedding(m["name"])]
st.metric("Active model", active, help="Used by chat-default (Open WebUI, n8n) and chat-tools (the agent)")
if active not in {m["name"] for m in have}:
    st.warning(f"`{active}` isn't downloaded: download it below or switch to another.")

for key in ("done", "error"):  # messages from the action before the last rerun
    if msg := st.session_state.pop(key, None):
        (st.success if key == "done" else st.error)(msg)


def do_switch(name: str):
    with st.status(f"Switching to {name}…", expanded=True) as status:
        if "tools" not in models.capabilities(name):
            st.warning(f"{name} can't call tools: chat works, but the agent's file, calendar and web steps won't.")
        freed = models.switch(kube, name)
        st.write("Restarting the LLM gateway (LiteLLM)…")
        for _ in range(90):
            if kube.litellm_ready():
                break
            time.sleep(2)
        if freed:
            st.write("Freed from RAM: " + ", ".join(freed))
        st.write(f"Loading {name} and asking it one question…")
        reply, seconds = models.smoke_test()
        status.update(label=f"{name} is active", state="complete")
    st.session_state.done = f"{name} is active. First answer: “{reply[:60]}” in {seconds} s (includes loading it)."


# ---- downloaded models -------------------------------------------------------------------
st.subheader("Downloaded")
rows = []
for m in chat_models:
    caps = models.capabilities(m["name"])
    rows.append({"Model": m["name"], "Size (GB)": m["gb"], "Parameters": m["params"], "Quantization": m["quant"],
                 "Tool calling": "✅" if "tools" in caps else "—", "In RAM": "●" if m["name"] in loaded else "",
                 "Active": "✅" if m["name"] == active else ""})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

others = [m["name"] for m in chat_models if m["name"] != active]
col1, col2 = st.columns(2)
with col1:
    pick = st.selectbox("Switch to", others, index=None, placeholder="choose a model")
    if st.button("Use this model", type="primary", disabled=not pick):
        try:
            do_switch(pick)
        except Exception as e:
            st.session_state.error = f"Switching failed: {e}"
        st.rerun()
with col2:
    drop = st.selectbox("Delete from disk", others, index=None, placeholder="choose a model",
                        help="The active model and the embedding model can't be deleted here")
    sure = st.checkbox("Yes, delete it", disabled=not drop)
    if st.button("Delete", disabled=not (drop and sure)):
        try:
            models.delete(drop)
            st.session_state.done = f"Deleted {drop}."
        except Exception as e:
            st.session_state.error = f"Delete failed: {e}"
        st.rerun()

# ---- download a new one ------------------------------------------------------------------
st.subheader("Download a model")
st.caption("Any name from [ollama.com/library](https://ollama.com/library) works. CPU-only laptop: stay at "
           "4B parameters or below; ~4 GB of RAM is free for the model.")
suggest = st.selectbox("Suggestions", list(models.SUGGESTED), index=None, placeholder="pick one, or type below",
                       format_func=lambda n: f"{n}: {models.SUGGESTED[n]}")
name = st.text_input("Model name", value=suggest or "", placeholder="e.g. qwen3:4b").strip()
then_use = st.checkbox("Switch to it when the download finishes", value=True)
if st.button("Download", disabled=not name):
    if not models.valid_name(name):
        st.error("That isn't a model name (letters, digits, . _ - : / only).")
    else:
        bar, note = st.progress(0.0), st.empty()
        try:
            for status, frac in models.pull(name):
                note.caption(status)
                if frac is not None:
                    bar.progress(min(frac, 1.0))
            bar.progress(1.0)
            if then_use:
                do_switch(name)
            else:
                st.session_state.done = f"Downloaded {name}."
        except Exception as e:
            st.session_state.error = f"Download failed: {e}"
        st.rerun()

st.divider()
st.caption("Same from a terminal: `.\\infra\\scripts\\platform.ps1 model use <name>` (Windows) or "
           "`make model M=<name>` (Ubuntu). Compare models with `make e2e` after switching.")
