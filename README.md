<div align="center">

# 🚀 Production RAG Agent

### Enterprise-Grade Retrieval-Augmented Generation (RAG) Platform

Build AI-powered knowledge assistants capable of ingesting, indexing, retrieving, and reasoning over your documents using **Google Gemini**, **LangGraph**, **FastAPI**, **Next.js 15**, **PostgreSQL**, and **Qdrant**.

<p align="center">
  <a href="https://productionragagent.vercel.app"><strong>🌐 Live Web App</strong></a> •
  <a href="https://production-rag-agent.onrender.com/docs"><strong>📖 API Swagger Docs</strong></a> •
  <a href="https://production-rag-agent.onrender.com/health"><strong>🩺 Health Endpoint</strong></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Next.js-15-black?logo=next.js" alt="Next.js 15" />
  <img src="https://img.shields.io/badge/FastAPI-Production-009688?logo=fastapi" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue?logo=python" alt="Python" />
  <img src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript" alt="TypeScript" />
  <img src="https://img.shields.io/badge/Docker-Containerized-2496ED?logo=docker" alt="Docker" />
  <img src="https://img.shields.io/badge/PostgreSQL-Neon%20%2F%20Supabase-336791?logo=postgresql" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Qdrant-Vector%20Database-DC2626?logo=qdrant" alt="Qdrant" />
  <img src="https://img.shields.io/badge/Google-Gemini%202.5-orange?logo=google" alt="Google Gemini" />
</p>

</div>

---

## 🌐 Live Production Deployments

| Component | Platform | URL | Status |
|---|---|---|---|
| **Frontend UI** | Vercel | [https://productionragagent.vercel.app](https://productionragagent.vercel.app) | 🟢 Live |
| **Backend API** | Render | [https://production-rag-agent.onrender.com](https://production-rag-agent.onrender.com) | 🟢 Live |
| **API Docs** | Swagger | [https://production-rag-agent.onrender.com/docs](https://production-rag-agent.onrender.com/docs) | 🟢 Live |
| **Health API** | FastAPI | [https://production-rag-agent.onrender.com/health](https://production-rag-agent.onrender.com/health) | 🟢 Live |

---

## 📖 Overview

**Production RAG Agent** is a full-stack, enterprise-ready Retrieval-Augmented Generation (RAG) platform designed to build intelligent AI assistants over private documents and enterprise knowledge bases.

Instead of hallucinating or relying solely on training data, the application performs multi-stage semantic vector search over uploaded documents, constructs grounded context using **LangGraph**, and generates streaming responses with exact source citations powered by **Google Gemini**.

The project incorporates production engineering best practices including:
- Multi-format parsing (PDF, DOCX, PPTX, XLSX, TXT, Markdown)
- Resilient batch embedding with exponential backoff & jitter
- Deterministic chunk hashing & deduplication
- Crash recovery & pipeline resume
- Async SQLAlchemy with Neon / Supabase connection pooling
- Cloud Qdrant vector index management

---

## 🏗 Architecture

```
                      User (Browser)
                            │
                            ▼
           Next.js 15 Frontend (Vercel / Port 3000)
                            │
                  /api/* Proxy Rewrite
                            │
                            ▼
            FastAPI Backend (Render / Port 8000)
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
 Google Gemini         PostgreSQL            Qdrant
(LLM & Embeddings)  (Metadata & Chat)    (Vector Search)
                    (Neon / Supabase)    (Qdrant Cloud)
                            │
                            ▼
                      LangGraph RAG
```

---

## ⭐ Key Features

### 📂 Multi-Format Document Ingestion
- Upload and index **PDF**, **DOCX**, **PPTX**, **XLSX**, **CSV**, **TXT**, and **Markdown**.
- Automatic file validation, sha256 hash deduplication, and document status lifecycle tracking (`pending` → `parsing` → `chunking` → `embedding` → `indexing` → `completed`).

### 🧠 Adaptive Semantic Chunking
- Recursive chunk splitting with configurable sizes and overlap.
- Deterministic chunk IDs to prevent duplicate embeddings.
- Automatic resume capability for interrupted or failed indexing runs.

### 🤖 LangGraph Context Construction & Gemini Reasoning
- Multi-step reasoning pipeline built with LangGraph.
- Uses `gemini-2.5-flash` for low-latency, high-accuracy reasoning.
- High-dimensional vector representations with `models/gemini-embedding-001` (3072 dimensions).

### 💬 Real-Time Streaming AI Chat
- Server-Sent Events (SSE) token streaming for responsive UX.
- Rich Markdown rendering, syntax-highlighted code blocks, and one-click copy.
- Inline source citations and relevance scores.

### 📊 Real-Time Health & Storage Dashboard
- Live dependency status checks for FastAPI, Google Gemini, PostgreSQL, and Qdrant.
- Real-time document count, chunk count, and storage utilization metrics.

---

## ⚙ Technology Stack

- **Frontend**: Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS, Lucide Icons
- **Backend**: FastAPI, LangGraph, LangChain, Pydantic v2, SQLAlchemy 2.0 (Async)
- **Vector Database**: Qdrant (Qdrant Cloud / Docker)
- **Relational Database**: PostgreSQL (Neon Serverless / Supabase / Local)
- **AI Models**: Google Gemini 2.5 Flash & Gemini Text Embedding 001
- **Deployment**: Render (Docker Backend), Vercel (Next.js Frontend)

---

## 🚀 Quick Start (Local Development)

### 1. Clone Repository

```bash
git clone https://github.com/Mohityadav55199/Production-RAG-Agent.git
cd Production-RAG-Agent
```

### 2. Configure Backend Environment

Create `backend/.env` (copy from `backend/.env.example`):

```ini
# Google Gemini
GOOGLE_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_DIMENSION=3072

# PostgreSQL (Neon, Supabase, or Local)
DATABASE_URL=postgresql://user:password@ep-xyz.neon.tech/neondb?sslmode=require

# Qdrant (Qdrant Cloud or Local)
QDRANT_URL=https://your-cluster.us-east-1.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=your_qdrant_api_key
QDRANT_COLLECTION=documents
```

### 3. Run Entire Stack with Docker Compose (Recommended)

Start the entire system (**Next.js Frontend + FastAPI Backend + Qdrant Vector DB + PostgreSQL**) with a single command from the project root:

```bash
docker compose up --build
```

- **Frontend Web UI**: `http://localhost:3000`
- **FastAPI Backend API**: `http://localhost:8000`
- **Swagger Documentation**: `http://localhost:8000/docs`
- **Qdrant Vector Database**: `http://localhost:6333`
- **PostgreSQL**: `localhost:5432`

---

### 4. Or Run Services Manually (Without Docker)

#### Run Backend:
```bash
cd backend
python -m venv .venv

# On Windows:
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

#### Run Frontend:
```bash
# In the project root directory
npm install
npm run dev
```

---

## ☁ Cloud Deployment Guide

### Part 1: Deploy Backend on Render (Docker)
1. Log in to [Render Dashboard](https://dashboard.render.com/) → **New +** → **Web Service**.
2. Connect your repository: `Mohityadav55199/Production-RAG-Agent`.
3. Configure settings:
   - **Root Directory**: `backend`
   - **Runtime**: `Docker`
4. Add Environment Variables:
   - `GOOGLE_API_KEY`: Your Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
   - `DATABASE_URL`: Your PostgreSQL URL from [Neon](https://neon.tech) or [Supabase](https://supabase.com)
   - `QDRANT_URL`: Your cluster URL from [Qdrant Cloud](https://cloud.qdrant.io)
   - `QDRANT_API_KEY`: Your Qdrant Cloud API key
   - `GROQ_API_KEY`: Your Groq key (the LLM used for chat and the resume agents)
   - `JWT_SECRET`: **Required.** A long random string that signs login tokens
     (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Without it everyone is logged out on every restart.
   - `ADMIN_EMAIL` and `ADMIN_PASSWORD`: **Set both.** At startup this account is created (or its password is reset to
     this value) and is the **only administrator**. It is also a normal user with its own documents, and it adopts any
     data that existed before accounts were added. Registering the admin's address through the sign-up form never
     grants admin rights (email addresses aren't verified), and an email with no password is ignored. Without these two,
     the first account to register becomes the admin, so register yours straight away.
   - `TRUSTED_PROXY_HOPS` (`1`) and optionally `CLIENT_IP_HEADER`: how to find the real client address behind proxies.
     This only feeds abuse limits; password guessing is capped per account regardless. After deploying, log in as the
     admin, open **Settings → Network check** and compare "Detected client IP" with your real public IP. If it shows a
     proxy address, raise `TRUSTED_PROXY_HOPS` or set `CLIENT_IP_HEADER` (for example `cf-connecting-ip`) to a header your
     proxy always overwrites.
   - Optional: `ALLOW_SIGNUP` (`false` closes registration), `GITHUB_TOKEN` (private repos), `RESUME_DAILY_LIMIT`.
5. Click **Create Web Service**. Your backend will be live at `https://production-rag-agent.onrender.com`.
6. Log in with the admin account. Once you've signed in, you can remove `ADMIN_PASSWORD` from the environment: the
   admin flag stays on the account (setting it again later resets the password to that value).

**Login lockout:** wrong guesses against one account are capped (12 per 15 minutes). The browser you normally use is
remembered with a signed device token, so someone guessing your password elsewhere can't lock you out of it.

**Images in answers:** images in an AI answer are never fetched automatically, because a hostile document could make
the model embed your conversation in an image address. The answer shows where the image comes from and loads it when
you click **Load image**.

> **Free-tier note:** Render's free instances sleep when idle, so the first request after a pause can take up to a
> minute (the app shows "Waking up the server…"). Long streams (resume tailoring takes 1–3 minutes) can hit proxy
> time limits when routed through Vercel's `/api` rewrite; if you see that, set `NEXT_PUBLIC_API_URL` on Vercel to the
> Render URL so the browser calls the backend directly, and set the backend's `CORS_ORIGINS` to your Vercel domain.

### Part 2: Deploy Frontend on Vercel
1. Log in to [Vercel](https://vercel.com/new) and import `Mohityadav55199/Production-RAG-Agent`.
2. Framework Preset: **Next.js** (Root Directory: `./`).
3. Add Environment Variable:
   - `BACKEND_URL`: `https://production-rag-agent.onrender.com` *(your Render backend URL)*
4. Click **Deploy**.

---

## 🧪 Testing

CI (`.github/workflows/ci.yml`) runs the backend tests, and the frontend type check, lint and build on every push.

```bash
# Backend (from backend/). The API tests need a PostgreSQL database whose NAME CONTAINS "test":
# the schema is wiped at the start of the run.
docker run -d --name ragtest -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=ragtest -p 5433:5432 postgres:16
pip install -c requirements.lock -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:5433/ragtest pytest

# Frontend (from the repo root)
npm run typecheck && npm run lint && npm run build
```

Without `TEST_DATABASE_URL` the API tests are skipped and the rest run. The PDF-compile tests need `pdflatex`
(they run inside the Docker image). Older ad-hoc scripts that talk to a running server live in
`backend/scripts/manual_tests/`.

Backend dependencies are pinned in `backend/requirements.lock` (used by the Docker build). To upgrade, install
`requirements.txt` in a clean `python:3.12-slim` container and run `pip freeze > requirements.lock`.

---

## 📂 Project Structure

```
Production-RAG-Agent/
├── app/                        # Next.js 15 App Router pages
│   ├── chat/                   # AI Chat interface
│   ├── collections/            # Knowledge collections
│   ├── dashboard/              # Metrics & health status
│   ├── documents/              # Document management & uploads
│   └── page.tsx                # Homepage redirect
├── backend/                    # FastAPI Backend
│   ├── app/
│   │   ├── api/                # REST endpoints (/health, /upload, /query, etc.)
│   │   ├── db/                 # PostgreSQL & Qdrant models and connections
│   │   ├── schemas/            # Pydantic data schemas
│   │   ├── services/           # Ingestion, embedding, chunking, & LangGraph RAG
│   │   └── config.py           # Environment settings & URL sanitization
│   ├── Dockerfile              # Multi-stage production container
│   ├── requirements.txt        # Python dependencies
│   └── docker-compose.yml      # Local dev stack
├── components/                 # Reusable React UI components
├── lib/                        # Client API hooks & utils
├── render.yaml                 # 1-Click Render blueprint
├── vercel.json                 # Vercel configuration
└── README.md
```

---

## 📄 License

This project is licensed under the **MIT License**.
