"""Models page: which model each use case runs, whether it fits this laptop, downloads."""

import time

import pandas as pd
import streamlit as st

import models

st.title("Models")
st.caption("Pick a model for each use case. Same model everywhere = one model in RAM; different ones swap "
           "(Ollama keeps at most 2 loaded). The embedding model for document search stays as it is.")

try:
    kube = models.Kube()
    choice = kube.choice()
    speeds = kube.speeds()
    have = models.installed()
    loaded = models.in_memory()
    sysinfo = models.system()
except Exception as e:
    st.error(f"Can't reach Ollama or Kubernetes: {e}")
    st.stop()

chat_models = [m for m in have if not models.is_embedding(m["name"])]
sizes = {m["name"]: m["gb"] for m in chat_models}
caps = {m["name"]: models.capabilities(m["name"]) for m in chat_models}
# RAM each model takes: what Ollama reports while it's loaded, else the estimate
ram = {n: loaded.get(n) or models.expected_ram_gb(gb) for n, gb in sizes.items()}
freeable = sum(gb for m, gb in loaded.items() if not models.is_embedding(m))
free_gb = sysinfo["available_gb"] + freeable  # if every chat model were unloaded


def speed_of(name: str) -> tuple[float | None, bool]:
    return models.expected_speed(name, sizes.get(name, 0), speeds, sizes)


def describe(name: str) -> str:
    tps, measured = speed_of(name)
    fit = models.verdict(ram[name], free_gb)
    speed = f"{tps} tok/s{'' if measured else ' (est.)'}" if tps else "speed not measured"
    return f"{models.ICON[fit]} {name} · ~{ram[name]} GB RAM · {speed}"


for key in ("done", "error"):  # messages from the action before the last rerun
    if msg := st.session_state.pop(key, None):
        (st.success if key == "done" else st.error)(msg)

# ---- sidebar: the laptop -------------------------------------------------------------------
with st.sidebar:
    st.subheader("This laptop (WSL)")
    st.progress(sysinfo["used_gb"] / sysinfo["total_gb"],
                text=f"RAM {sysinfo['used_gb']} of {sysinfo['total_gb']} GB used · {sysinfo['available_gb']} GB free")
    st.progress(sysinfo["cpu_pct"] / 100, text=f"CPU load {sysinfo['load']} on {sysinfo['cpus']} cores ({sysinfo['cpu_pct']}%)")
    st.caption("Ollama may use at most 4 cores (thermal cap, README §12).")
    st.markdown("**In RAM now**")
    for name, gb in sorted(loaded.items()):
        st.caption(f"● {name}: {gb} GB" + (" (document search)" if models.is_embedding(name) else ""))
    if not loaded:
        st.caption("nothing (models load on first use, unload after 5 min idle)")
    st.caption(f"Free for a chat model: **{free_gb:.1f} GB** (free RAM + chat models that would be unloaded), "
               f"keeping {models.HEADROOM_GB:.0f} GB spare.")
    if st.button("Refresh"):
        st.rerun()

# ---- a model for each use case -------------------------------------------------------------
st.subheader("Model for each use case")
picked = {}
for uc, (label, _, alias, needs_tools) in models.USE_CASES.items():
    options = [n for n in sizes if not needs_tools or "tools" in caps[n]]
    current = choice[uc] if choice[uc] in options else (options[0] if options else None)
    picked[uc] = st.selectbox(label, options, index=options.index(current) if current else None, format_func=describe,
                              key=f"uc-{uc}", help=f"LiteLLM alias `{alias}`" + (" · tool-calling models only" if needs_tools else ""))
    if choice[uc] not in sizes:
        st.warning(f"`{choice[uc]}` is set for this but isn't downloaded.")

if all(picked.values()):
    plan = models.plan_fit(picked, ram, loaded, sysinfo["available_gb"])
    text = (f"**{len(plan['models'])} model{'s' if len(plan['models']) > 1 else ''}** ({', '.join(plan['models'])}): "
            f"needs ~{plan['need_gb']} GB, {plan['free_gb']} GB free after unloading the current ones.")
    {"fits": st.success, "tight": st.warning, "too big": st.error}[plan["verdict"]](
        f"{models.ICON[plan['verdict']]} {text} " + {"fits": "Fits.", "tight": "Tight: it may run out of memory when other "
        "services are busy.", "too big": "Too big: Ollama would fail to load it or WSL would start swapping."}[plan["verdict"]])
    if plan["swaps"]:
        st.info("Different models per use case: going from one use case to another reloads a model (+10–25 s).")
    rows = []
    for uc, (label, _, _, _) in models.USE_CASES.items():
        tps, measured = speed_of(picked[uc])
        rows.append({"Use case": label, "Model": picked[uc],
                     "Expected answer": f"~{round(models.ANSWER_TOKENS / tps)} s" + ("" if measured else " (est.)") if tps else "?"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"Expected answer: generating ~{models.ANSWER_TOKENS} tokens; tool steps and long prompts add to it.")

    changed = any(picked[uc] != choice[uc] for uc in models.USE_CASES)
    anyway = plan["verdict"] != "too big" or st.checkbox("Apply anyway")
    if st.button("Apply", type="primary", disabled=not (changed and anyway)):
        try:
            with st.status("Applying…", expanded=True) as status:
                freed = models.apply(kube, picked)
                st.write("Restarting the LLM gateway (LiteLLM)…")
                for _ in range(90):
                    if kube.litellm_ready():
                        break
                    time.sleep(2)
                if freed:
                    st.write("Freed from RAM: " + ", ".join(freed))
                results = []
                for m in plan["models"]:
                    st.write(f"Loading {m} and measuring its speed…")
                    tps, secs = models.speed_test(m)
                    kube.save_speed(m, tps)
                    results.append(f"{m}: {tps} tok/s (first answer {secs} s incl. loading)")
                reply, _ = models.smoke_test("chat-tools")
                status.update(label="Applied", state="complete")
            st.session_state.done = "Applied. " + "; ".join(results) + f". Agent alias answers: “{reply[:30]}”."
        except Exception as e:
            st.session_state.error = f"Applying failed: {e}"
        st.rerun()

# ---- downloaded models ---------------------------------------------------------------------
st.subheader("Downloaded")
rows = []
for n, gb in sizes.items():
    tps, measured = speed_of(n)
    used_for = [models.USE_CASES[uc][0].split(" ")[0].rstrip(":") for uc in models.USE_CASES if choice[uc] == n]
    rows.append({"Model": n, "Download (GB)": gb, "RAM (GB)": f"{ram[n]}" + ("" if n in loaded else " (est.)"),
                 "Speed (tok/s)": (f"{tps}" + ("" if measured else " (est.)")) if tps else "—",
                 "Fits": models.ICON[models.verdict(ram[n], free_gb)], "Tool calling": "✅" if "tools" in caps[n] else "—",
                 "Used for": ", ".join(used_for), "In RAM": "●" if n in loaded else ""})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

unused = [n for n in sizes if n not in choice.values()]
drop = st.selectbox("Delete from disk", unused, index=None, placeholder="a model no use case uses")
if st.button("Delete", disabled=not (drop and st.checkbox("Yes, delete it", disabled=not drop))):
    try:
        models.delete(drop)
        st.session_state.done = f"Deleted {drop}."
    except Exception as e:
        st.session_state.error = f"Delete failed: {e}"
    st.rerun()

# ---- download a new one ------------------------------------------------------------------
st.subheader("Download a model")
st.caption("Any name from [ollama.com/library](https://ollama.com/library) works. On this CPU-only laptop, 4B "
           "parameters or fewer answer in reasonable time.")


def suggest_label(n: str) -> str:
    what, gb = models.SUGGESTED[n]
    need = models.expected_ram_gb(gb)
    fit = models.verdict(need, free_gb)
    tps, _ = models.expected_speed(n, gb, speeds, sizes)
    return f"{models.ICON[fit]} {n}: {what} · {gb} GB download · ~{need} GB RAM" + (f" · ~{tps} tok/s" if tps else "")


suggest = st.selectbox("Suggestions", [n for n in models.SUGGESTED if n not in sizes], index=None,
                       placeholder="pick one, or type a name below", format_func=suggest_label)
name = st.text_input("Model name", value=suggest or "", placeholder="e.g. qwen3:4b").strip()
then_use = st.checkbox("Use it for every use case when the download finishes", value=False)
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
            msg = f"Downloaded {name}."
            if then_use:
                models.switch(kube, name)
                for _ in range(90):
                    if kube.litellm_ready():
                        break
                    time.sleep(2)
                tps, secs = models.speed_test(name)
                kube.save_speed(name, tps)
                msg += f" Every use case now uses it: {tps} tok/s (first answer {secs} s incl. loading)."
            st.session_state.done = msg
        except Exception as e:
            st.session_state.error = f"Download failed: {e}"
        st.rerun()

st.divider()
st.caption("From a terminal: `.\\infra\\scripts\\platform.ps1 model use <name>` (every use case) or "
           "`make model M=<name>`. After a change, `make e2e` shows what still works.")
