# Design decisions

Why the project is built the way it is, including the choices that did not pay off. Each entry says what was decided,
why, and what it costs. Numbers come from `backend/eval` (see its README) unless stated otherwise.

## 1. Two databases: Qdrant for vectors, PostgreSQL for everything else

**Decision.** Chunk vectors and their text live in Qdrant. Users, documents, conversations, resumes, quotas and metrics
live in PostgreSQL.

**Why.** Qdrant gives fast cosine search with payload filters (every query is filtered to the signed-in user's documents).
PostgreSQL gives transactions, constraints and migrations (Alembic) for the relational data. Both have free hosted tiers
(Qdrant Cloud, Neon or Supabase), which matters for a free-tier deployment.

**Cost.** Two systems to keep consistent. Deleting a document must remove its vectors too, and
`backend/scripts/clean_orphans.py` exists because that can drift. A single PostgreSQL with pgvector would be simpler to run
and was the main alternative; Qdrant won on filtered-search ergonomics and on keeping vector load off the relational database.

## 2. A three-step LangGraph pipeline: retrieve, generate, save

**Decision.** The question flow is a small LangGraph graph (`retrieve` then `generate` then `save_history`) streamed
through `astream_events`.

**Why.** The graph is not complicated, and a plain async function would work. LangGraph earns its place by emitting
events for each node and each model token, which is what the streaming endpoint turns into progress steps, sources and
tokens. It also leaves room to add a branch (for example a retry with a wider search) without rewriting the streaming.

**Cost.** An extra dependency and a heavier mental model for what is currently a straight line. The resume tailoring
pipeline (`services/resume/agents.py`) is where a graph is really needed: it loops between writing and scoring.

## 3. Server-Sent Events for streaming, not WebSockets

**Decision.** `POST /query` returns `text/event-stream`: `thinking`, `step`, `sources`, `chunk`, `done`, `error`.

**Why.** Answers flow one way, so SSE is enough. It works over plain HTTP through Vercel's rewrite and Render's proxy, and
needs no connection management. The browser reads it with `fetch` so the auth header can be sent (which `EventSource` cannot).

**Cost.** Long streams, such as resume tailoring, can hit proxy time limits when routed through Vercel. The README documents
calling Render directly in that case.

## 4. Models: Groq first, Gemini behind it, Claude optional in front

**Decision.** Without an Anthropic key the chain is Groq `gpt-oss-120b`, then `gpt-oss-20b`, then Gemini. With
`ANTHROPIC_API_KEY` set, Claude answers first and the same chain stays behind it. Embeddings are always
`gemini-embedding-001` (3072 dimensions).

**Why.** Free-tier rate limits are the main failure mode of a demo. A chain that falls through silently keeps the app
answering. Groq is fast and free enough for a portfolio project; Claude is a quality upgrade a deployer can switch on.

**Cost and a lesson.** Hard-coded model names expire. Google retired `gemini-2.5-flash` for new keys while this was being
built, so the Gemini fallback and the image features returned 404 for anyone with a new key. The chain now uses `gemini-3.5-flash`, retired
names are mapped to successors in one table (`RETIRED_MODELS`), and the answer-quality check in `backend/eval` makes a
broken model visible quickly.

## 5. Hybrid search and reranking are on, but the benchmark does not justify them yet

**Decision.** Retrieval is vector search, plus an exact-term leg for identifiers (`HYBRID_SEARCH_ENABLED`), plus a
lexical reranker (`RERANKING_ENABLED`), plus follow-up question rewriting.

**What was measured** (60 questions, 8 documents): the exact-term leg changed nothing, the lexical reranker slightly hurt
(Hit@5 93.3% to 90.0%, paraphrase MRR 1.00 to 0.85), and rewriting follow-up questions was the clear win (follow-up MRR
0.60 to 0.88). Details and caveats are in `backend/eval/README.md`.

**Why they stay on for now.** The benchmark corpus is small and prose-only. Exact-term search is aimed at identifiers,
error codes and file names, which are common in the code projects this app imports and absent from the benchmark. The
reranker is the weakest of the three, and turning it off (`RERANKING_ENABLED=false`) is the first thing to try if
paraphrased questions matter more than exact-phrase ones.

**Cost.** Each stage adds latency (about 1.0 s for plain search to 1.8 s for the full pipeline in the benchmark run).

## 6. A PostgreSQL job queue for ingestion, not Redis or Celery

**Decision.** Uploads are registered immediately and the file bytes are stored with a row in `ingestion_jobs`. A background
worker claims rows with `UPDATE ... FOR UPDATE SKIP LOCKED`, and jobs left `running` by a restart are re-queued.

**Why.** The free tier has no room for a broker or a second process, and PostgreSQL is already there. Storing the bytes
with the job means a restart (which a free instance does constantly) loses nothing, and the upload request returns in
moments instead of holding a connection through embedding.

**Cost.** Throughput is one worker's worth, and large files sit in the database until processed.

## 7. In-process rate limiting

**Decision.** Login, signup and edit limits use a small sliding-window limiter held in memory
(`utils/rate_limit.py`). Per-user daily quotas (questions, uploads, resume runs) are counted in PostgreSQL.

**Why.** Deployment is a single instance, so shared state would be extra infrastructure for no benefit. The quotas that
protect the model budget are the ones that must survive a restart, and those are in the database.

**Cost.** The in-memory limits reset when the server restarts, and they would not work across several instances. Moving
them to Redis or PostgreSQL is the change to make before scaling out. This is listed in `SECURITY.md`.

## 8. Treating retrieved text as hostile

**Decision.** Documents are untrusted input. The system prompt says retrieved text is data, never instructions, and the
browser refuses to load remote images from an answer until the user clicks.

**Why.** A document is attacker-controlled text that goes straight into the prompt. The most damaging realistic attack is a
document that makes the model emit a Markdown image whose URL carries the conversation.

**What was measured.** Prompting alone is not enough: with the original prompt the model passed 4 of 8 adversarial cases
and printed its whole system prompt; the hardened prompt passes 6 or 7 of 8, and two cases still fail some of the time.
That is why the UI defence exists independently of the model, and why the assistant has no tools to misuse. See the
Guardrails section of `backend/eval/README.md`.

## 9. No keep-warm pings

**Decision.** Nothing calls the Render backend on a schedule: no cron job, no GitHub Action, and the frontend only polls
`/health` while the server is cold-starting.

**Why.** Render's free plan has a monthly hour allowance, and a keep-warm ping spends all of it. The cost is a 40 to 60
second cold start after 15 idle minutes, which the UI explains with a banner and a timer. CI runs on GitHub's runners and
never touches Render.

## 10. One generated contract between backend and frontend

**Decision.** `lib/api-client/schema.d.ts` is generated from the FastAPI OpenAPI schema (`npm run gen:api`), and CI fails if
the committed file differs from what the backend produces.

**Why.** The file had gone stale after the first commit (7 of 44 endpoints) because nothing forced it to stay current. A
failing check is the cheapest way to keep it honest.

**Cost.** The hand-written client in `lib/api/` does not use the generated types yet. Moving it onto them is the follow-up
that makes the check pay off fully.
