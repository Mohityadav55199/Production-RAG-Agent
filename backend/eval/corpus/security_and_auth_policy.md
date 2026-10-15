# Security and Authentication Policy

## Authentication Protocol
The API employs stateless JSON Web Tokens (JWT) using the HS256 algorithm:
- Access tokens expire strictly after 168 hours (7 days, configured via `JWT_EXPIRE_HOURS = 24 * 7`).
- Secrets are sourced from `JWT_SECRET`. In production on Render, secrets are generated automatically and retained across container restarts.
- Password hashes are computed using bcrypt with salt rounds configured to resist brute-force dictionary attacks.

## Role-Based Access Control (RBAC)
User permissions are divided into two distinct levels:
1. **Standard Users**: Can upload personal documents, manage private collections, view their own document assets, and run RAG queries within their authorized tenant scope.
2. **Administrators**: Configured through `ADMIN_EMAIL` and `ADMIN_PASSWORD`. Admin credentials are seeded on startup. Admins have access to the `/admin/users` endpoints, audit logs, system performance metrics, and the network topology diagnostic check.

## Reverse Proxy and IP Rate Limiting
To prevent distributed abuse without penalizing corporate networks behind NAT gateways, the application resolves client IP addresses using strict proxy hop verification:
- `TRUSTED_PROXY_HOPS = 1` directs the backend to inspect the client address from Render's load balancer.
- When traffic routes through Vercel and Cloudflare, `CLIENT_IP_HEADER` is set to `cf-connecting-ip`. Because Cloudflare guarantees this header cannot be forged by external clients, it reliably identifies the visitor.
- `FRONTEND_FORWARDS_CLIENT_IP = true` instructs the system to read the visitor IP from forwarded headers when proxied by trusted Next.js edge handlers.
- The system enforces a flood rate limit of 60 requests per minute per IP address on authenticated routes, and 10 attempts per minute on `/auth/login`.

## Document Data Isolation
All chunks stored in Qdrant carry a `document_id` and optional `user_id` in their vector payload. Multi-tenant queries apply Qdrant match filters before ANN computation, guaranteeing that users cannot retrieve embeddings belonging to other organizations or unshared workspaces.
