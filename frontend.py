"""
=============================================================
  SECOND BRAIN - FRONTEND (frontend.py)
  Stack : Streamlit
  Run   : streamlit run frontend.py
  Note  : Make sure backend.py is running on port 8000 first
=============================================================
"""

import streamlit as st
import requests
import json

# ── CONFIG ───────────────────────────────────────────────────────────────────
BACKEND_URL = "http://localhost:8000"

st.set_page_config(
    page_title="Second Brain AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── CUSTOM CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0f0f0f; }
    .stApp { background-color: #0f0f0f; color: #e0e0e0; }
    .brain-title {
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(135deg, #6c63ff, #48cae4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 0.2rem;
    }
    .brain-subtitle {
        text-align: center;
        color: #888;
        font-size: 0.95rem;
        margin-bottom: 2rem;
    }
    .answer-box {
        background: #1a1a2e;
        border-left: 4px solid #6c63ff;
        border-radius: 8px;
        padding: 1.2rem 1.5rem;
        color: #e0e0e0;
        font-size: 0.97rem;
        line-height: 1.7;
        margin-top: 1rem;
    }
    .source-tag {
        display: inline-block;
        background: #2d2d44;
        border: 1px solid #6c63ff44;
        border-radius: 20px;
        padding: 3px 12px;
        font-size: 0.8rem;
        color: #a9a9d9;
        margin: 3px;
    }
    .stat-card {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #2a2a4a;
    }
    .upload-success {
        background: #0d2b1d;
        border-left: 4px solid #2ecc71;
        border-radius: 6px;
        padding: 0.8rem 1rem;
        color: #2ecc71;
        margin-top: 0.5rem;
    }
    .upload-error {
        background: #2b0d0d;
        border-left: 4px solid #e74c3c;
        border-radius: 6px;
        padding: 0.8rem 1rem;
        color: #e74c3c;
        margin-top: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)


# ── SESSION STATE ─────────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "uploaded_files" not in st.session_state:
    st.session_state.uploaded_files = []


# ── HELPER: API CALLS ─────────────────────────────────────────────────────────
def check_backend():
    try:
        r = requests.get(f"{BACKEND_URL}/", timeout=3)
        return r.status_code == 200
    except:
        return False

def upload_file_to_backend(file):
    try:
        files = {"file": (file.name, file.getvalue(), file.type)}
        r = requests.post(f"{BACKEND_URL}/upload", files=files, timeout=30)
        return r.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

def ask_backend(question: str):
    try:
        r = requests.post(
            f"{BACKEND_URL}/ask",
            json={"question": question},
            timeout=60
        )
        if r.status_code == 200:
            return r.json()
        else:
            return {"error": r.json().get("detail", "Something went wrong.")}
    except Exception as e:
        return {"error": str(e)}

def get_docs_list():
    try:
        r = requests.get(f"{BACKEND_URL}/docs-list", timeout=5)
        return r.json()
    except:
        return {"total_chunks": 0, "files": []}

def reset_knowledge_base():
    try:
        r = requests.delete(f"{BACKEND_URL}/reset", timeout=10)
        return r.json()
    except Exception as e:
        return {"success": False, "message": str(e)}


# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🧠 Second Brain")
    st.markdown("---")

    # Backend status
    backend_ok = check_backend()
    if backend_ok:
        st.success("✅ Backend Connected")
    else:
        st.error("❌ Backend Offline\nRun: `uvicorn backend:app --reload`")
        st.stop()

    st.markdown("### 📁 Upload Documents")
    st.caption("Supports: PDF, TXT, MD")

    uploaded = st.file_uploader(
        "Choose a file",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    if st.button("⬆️ Upload to Brain", use_container_width=True):
        if uploaded:
            for file in uploaded:
                with st.spinner(f"Processing {file.name}..."):
                    result = upload_file_to_backend(file)
                    if result.get("success"):
                        st.markdown(
                            f'<div class="upload-success">✅ <b>{file.name}</b><br>'
                            f'{result.get("chunks_stored", 0)} chunks stored</div>',
                            unsafe_allow_html=True
                        )
                        if file.name not in st.session_state.uploaded_files:
                            st.session_state.uploaded_files.append(file.name)
                    else:
                        st.markdown(
                            f'<div class="upload-error">❌ {result.get("message", "Upload failed")}</div>',
                            unsafe_allow_html=True
                        )
        else:
            st.warning("Please select a file first.")

    st.markdown("---")

    # Knowledge base stats
    st.markdown("### 📊 Knowledge Base")
    kb = get_docs_list()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Chunks", kb.get("total_chunks", 0))
    with col2:
        st.metric("Files", len(kb.get("files", [])))

    if kb.get("files"):
        st.markdown("**Stored files:**")
        for fname in kb["files"]:
            st.markdown(f"• `{fname}`")

    st.markdown("---")

    # Reset button
    if st.button("🗑️ Clear Knowledge Base", use_container_width=True, type="secondary"):
        result = reset_knowledge_base()
        if result.get("success"):
            st.session_state.uploaded_files = []
            st.session_state.chat_history = []
            st.success("Knowledge base cleared!")
            st.rerun()


# ── MAIN AREA ─────────────────────────────────────────────────────────────────
st.markdown('<div class="brain-title">🧠 Second Brain AI</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="brain-subtitle">Upload your notes, PDFs & research. Ask anything. AI connects the dots.</div>',
    unsafe_allow_html=True
)

# Show chat history
for chat in st.session_state.chat_history:
    with st.chat_message("user"):
        st.write(chat["question"])
    with st.chat_message("assistant", avatar="🧠"):
        st.markdown(f'<div class="answer-box">{chat["answer"]}</div>', unsafe_allow_html=True)
        if chat.get("sources"):
            st.markdown("**Sources used:**")
            source_html = " ".join(
                f'<span class="source-tag">📄 {s}</span>'
                for s in chat["sources"]
            )
            st.markdown(source_html, unsafe_allow_html=True)

# Input box
question = st.chat_input("Ask your Second Brain anything...")

if question:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant", avatar="🧠"):
        with st.spinner("Thinking..."):
            result = ask_backend(question)

        if "error" in result:
            st.error(f"❌ {result['error']}")
        else:
            answer  = result.get("answer", "No answer found.")
            sources = result.get("sources", [])

            st.markdown(f'<div class="answer-box">{answer}</div>', unsafe_allow_html=True)

            if sources:
                st.markdown("**Sources used:**")
                source_html = " ".join(
                    f'<span class="source-tag">📄 {s}</span>'
                    for s in sources
                )
                st.markdown(source_html, unsafe_allow_html=True)

            # Save to chat history
            st.session_state.chat_history.append({
                "question": question,
                "answer": answer,
                "sources": sources
            })

# Empty state
if not st.session_state.chat_history:
    st.markdown("""
    <div style='text-align:center; padding: 3rem; color: #555;'>
        <div style='font-size: 3rem;'>🧠</div>
        <div style='font-size: 1.1rem; margin-top: 1rem;'>Your Second Brain is ready.</div>
        <div style='font-size: 0.9rem; margin-top: 0.5rem;'>
            Upload documents from the sidebar, then ask your first question.
        </div>
        <br>
        <div style='color: #6c63ff; font-size: 0.85rem;'>
            Try: "How are statistics used in machine learning?"<br>
            Or: "What is the connection between SQL and data science?"
        </div>
    </div>
    """, unsafe_allow_html=True)
