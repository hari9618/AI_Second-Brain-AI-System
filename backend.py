"""
=============================================================
  SECOND BRAIN - BACKEND (backend.py)
  Stack : FastAPI + LangChain + ChromaDB + Google Gemini 2.5 Flash
  Run   : uvicorn backend:app --reload --port 8000
=============================================================
"""

import os
import uuid
import time
import asyncio
import logging
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters  import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
import chromadb
from chromadb.config import Settings

# ── Silence ChromaDB telemetry spam ──────────────────────────────────────────
logging.getLogger("chromadb").setLevel(logging.ERROR)

# ── 1. ENV ────────────────────────────────────────────────────────────────────
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise RuntimeError(
        "\n[ERROR] GOOGLE_API_KEY not found!\n"
        "Create a .env file and add: GOOGLE_API_KEY=your_key_here\n"
        "Get free key: https://aistudio.google.com/app/apikey\n"
    )

# ── 2. FOLDERS ────────────────────────────────────────────────────────────────
UPLOAD_DIR = Path("uploads")
CHROMA_DIR = "chroma_db"
UPLOAD_DIR.mkdir(exist_ok=True)

# ── 3. APP ────────────────────────────────────────────────────────────────────
app = FastAPI(title="Second Brain API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 4. CHROMADB (telemetry OFF) ───────────────────────────────────────────────
chroma_client = chromadb.PersistentClient(
    path=CHROMA_DIR,
    settings=Settings(anonymized_telemetry=False)
)

# ── 5. EMBEDDINGS — increased timeout to 180s ─────────────────────────────────
embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=GOOGLE_API_KEY,
    transport="rest",
    request_options={"timeout": 180},   # ← was 120, now 180
)

# ── 6. LLM — Gemini 2.5 Flash ─────────────────────────────────────────────────
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    google_api_key=GOOGLE_API_KEY,
    temperature=0.3,
    transport="rest",
    request_options={"timeout": 180},   # ← was 120, now 180
    convert_system_message_to_human=True,
)

# ── 7. SPLITTER ───────────────────────────────────────────────────────────────
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100,
)

# ── 8. PROMPT ─────────────────────────────────────────────────────────────────
SECOND_BRAIN_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are a Second Brain AI assistant with access to the user's
personal knowledge base of notes, PDFs, and research documents.

Rules:
- Answer ONLY using the context below
- Connect ideas across different documents when relevant
- Use bullet points for clarity
- If answer not found say: "I could not find this in your knowledge base."

KNOWLEDGE BASE:
{context}

QUESTION: {question}

ANSWER:"""
)

# ── 9. HELPERS ────────────────────────────────────────────────────────────────
def get_vectorstore() -> Chroma:
    return Chroma(
        client=chroma_client,
        embedding_function=embeddings,
        collection_name="second_brain",
    )

def load_document(file_path: str, filename: str) -> list:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return PyPDFLoader(file_path).load()
    elif ext in [".txt", ".md"]:
        return TextLoader(file_path, encoding="utf-8").load()
    else:
        raise ValueError(f"Unsupported type '{ext}'. Use .pdf .txt or .md")

def embed_in_batches(vectorstore, chunks, batch_size=10, retries=3, delay=5):
    """
    Embed chunks in small batches to avoid hitting API timeout on large files.
    Each batch is retried up to `retries` times before raising.
    """
    total = len(chunks)
    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        for attempt in range(retries):
            try:
                vectorstore.add_documents(batch)
                print(f"[Embed] Batch {i//batch_size + 1} done ({i+len(batch)}/{total} chunks)")
                break
            except Exception as e:
                if attempt < retries - 1:
                    print(f"[Retry {attempt+1}/{retries}] batch {i//batch_size+1} — retrying in {delay}s... ({e})")
                    time.sleep(delay)
                else:
                    raise RuntimeError(
                        f"Embedding failed on batch {i//batch_size+1} after {retries} attempts: {e}"
                    )

# ── 10. MODELS ────────────────────────────────────────────────────────────────
class QuestionRequest(BaseModel):
    question: str

class AnswerResponse(BaseModel):
    answer: str
    sources: List[str]

class DocumentsResponse(BaseModel):
    total_chunks: int
    files: List[str]

# ── 11. ROUTES ────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "running", "message": "Second Brain API is alive!"}


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    FIX: Runs the heavy embedding work in a thread pool so the
    async event loop is never blocked. Streamlit timeout is no longer hit.
    """
    allowed = [".pdf", ".txt", ".md"]
    ext = Path(file.filename).suffix.lower()

    if ext not in allowed:
        raise HTTPException(400, f"'{ext}' not supported. Use: {allowed}")

    # Save file
    file_id = str(uuid.uuid4())[:8]
    save_path = UPLOAD_DIR / f"{file_id}_{file.filename}"
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    # Load + chunk (in thread so PDF parsing doesn't block loop)
    try:
        docs = await asyncio.to_thread(load_document, str(save_path), file.filename)
        chunks = text_splitter.split_documents(docs)
    except Exception as e:
        raise HTTPException(500, f"Could not read file: {str(e)}")

    if not chunks:
        raise HTTPException(400, "File is empty or unreadable.")

    # Tag metadata
    for chunk in chunks:
        chunk.metadata["source_file"] = file.filename
        chunk.metadata["file_id"] = file_id

    # Embed + store in background thread — avoids blocking & timeout
    try:
        vectorstore = get_vectorstore()
        await asyncio.to_thread(embed_in_batches, vectorstore, chunks)
    except Exception as e:
        raise HTTPException(500, f"Embedding failed: {str(e)}")

    return {
        "success": True,
        "filename": file.filename,
        "chunks_stored": len(chunks),
        "message": f"'{file.filename}' added to your Second Brain!"
    }


@app.post("/ask", response_model=AnswerResponse)
async def ask_question(request: QuestionRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty.")

    vectorstore = get_vectorstore()

    try:
        count = vectorstore._collection.count()
    except Exception:
        count = 0

    if count == 0:
        raise HTTPException(404, "Knowledge base is empty. Upload documents first!")

    try:
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vectorstore.as_retriever(search_kwargs={"k": 4}),
            chain_type_kwargs={"prompt": SECOND_BRAIN_PROMPT},
            return_source_documents=True,
        )
        # Run LLM call in thread to stay non-blocking
        result = await asyncio.to_thread(qa_chain.invoke, {"query": question})
    except Exception as e:
        raise HTTPException(500, f"AI query failed: {str(e)}")

    sources = list(set(
        doc.metadata.get("source_file", "Unknown")
        for doc in result.get("source_documents", [])
    ))

    return AnswerResponse(answer=result["result"], sources=sources)


@app.get("/docs-list", response_model=DocumentsResponse)
def list_documents():
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    total_chunks = collection.count()
    files = []

    if total_chunks > 0:
        all_meta = collection.get(include=["metadatas"])["metadatas"]
        files = list(set(m.get("source_file", "Unknown") for m in all_meta))

    return DocumentsResponse(total_chunks=total_chunks, files=files)


@app.delete("/reset")
def reset_knowledge_base():
    try:
        chroma_client.delete_collection("second_brain")
        return {"success": True, "message": "Knowledge base cleared!"}
    except Exception as e:
        raise HTTPException(500, f"Reset failed: {str(e)}")
