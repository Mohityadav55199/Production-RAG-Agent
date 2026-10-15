# Deployment and DevOps Guide

## Infrastructure Architecture
The application infrastructure is hosted across managed cloud providers:
- **Backend Service**: Deployed on Render as a Dockerized web service (`./backend/Dockerfile`) running Python 3.12 with Uvicorn.
- **Frontend Web UI**: Deployed on Vercel (`https://productionragagent.vercel.app`) using Next.js 15 with App Router.
- **Relational Database**: Neon Serverless PostgreSQL providing auto-scaling compute and high-availability storage.
- **Vector Database**: Qdrant Cloud cluster in `us-east-1` with 3072-dimensional vector collections and cosine distance indexing.

## Cross-Origin Resource Sharing (CORS)
For production security, the FastAPI backend restricts browser cross-origin requests:
- In `render.yaml`, `CORS_ORIGINS` is configured to `["https://productionragagent.vercel.app"]`.
- Wildcard origins `["*"]` are strictly prohibited in production because `allow_credentials=True` is enabled for cookie-based and Authorization-header sessions.
- In local development, `CORS_ORIGINS` defaults to `["http://localhost:3000", "http://127.0.0.1:3000"]`.

## Health Check and Monitoring
The service exposes two primary health probes for load balancers and container orchestrators:
1. `GET /health`: Returns basic service liveness and version information (`{"status": "ok", "version": "0.1.0"}`).
2. `GET /health/detailed`: Actively pings PostgreSQL via a synchronous connection pool and executes a heartbeat query against the Qdrant cluster to ensure all persistence layers are operational.

## Resource Constraints and Scaling
- The free Render web service tier operates with 512 MB RAM and 0.1 CPU cores.
- To prevent Out-Of-Memory (OOM) crashes during heavy PDF image decompression, `IMAGE_MAX_PIXELS` is capped at 25,000,000 pixels.
- File uploads are constrained to `MAX_UPLOAD_SIZE_MB = 50` and a maximum of 10 files per simultaneous batch upload.
