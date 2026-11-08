# Security

## Reporting a vulnerability

Please report security problems privately through GitHub: **Security tab → Report a vulnerability** on this repository.
Do not open a public issue for anything that could be exploited. Include what you found, how to reproduce it and, if you
can, which file is involved. This is a personal project, so there is no guaranteed response time, but reports are read
and fixed as soon as possible.

Only the `main` branch is maintained.

## What the project does to stay safe

### Accounts and sessions
- Passwords are hashed with bcrypt (cost 12); only the first 72 bytes count, so longer passwords are rejected rather than
  silently truncated.
- Sessions are signed JWTs. `JWT_SECRET` must be set in production; without it a random secret is generated and everyone
  is logged out on each restart.
- Wrong passwords are capped per account (12 per 15 minutes). A signed device token marks your usual browser, so someone
  guessing your password elsewhere cannot lock you out of it.
- There is a single administrator, set through `ADMIN_EMAIL` and `ADMIN_PASSWORD`. Registering that address through the
  sign-up form never grants admin rights, and `ALLOW_SIGNUP=false` closes registration.
- Documents, conversations and resumes are scoped to the signed-in user.

### Uploads and parsing
- File size limit (`MAX_UPLOAD_SIZE_MB`) and a maximum number of files per upload.
- The file type is checked from the file's signature, not only its extension.
- Images must be real raster images of a sane size (decompression bombs are rejected), SVG is refused, and every image is
  re-encoded on the server so metadata and embedded payloads are dropped. Image questions are never stored.
- Uploads are deduplicated by SHA-256 hash.

### Prompt injection
- Retrieved text is marked as untrusted data in the system prompt, and the rule not to reveal the prompt is stated
  twice. This is **measured, not assumed**: `backend/eval/guardrails.py` runs 8 adversarial cases against the real model.
  The original prompt passed 4 of 8 (the model printed its whole system prompt and repeated a tracking image); the
  current prompt passes 6 or 7 of 8. Two cases, a document that says to add a link and one that says to change the
  answering style, still succeed some of the time. **Prompting alone cannot make a model ignore text it has read.**
- So the damage a successful injection can do is limited by design: the assistant has no tools and takes no actions,
  every query only sees the signed-in user's own documents, and the browser never loads a remote image from an answer
  until the user clicks (covered by tests in `components/ui/safe-markdown.test.tsx`).
- Images in AI answers are never fetched automatically. A hostile document could otherwise tell the model to place the
  conversation in an image address and have the browser send it out. The answer shows where the image comes from and the
  user clicks **Load image** to opt in.
- Resume tailoring only uses facts from the user's own library; code strips any skill, employer, project or number the
  library does not support.

### Abuse and availability
- Per-user quotas and rate limits (images per hour, resume generations per day, edits per hour).
- The real client address is resolved from a header the proxy always overwrites (`CLIENT_IP_HEADER`), so limits cannot be
  dodged by forging `X-Forwarded-For`. **Settings → Network check** shows the detected address.
- CORS is restricted to the deployed frontend through `CORS_ORIGINS`.

### Supply chain and secrets
- Backend dependencies are pinned in `requirements.lock`; Dependabot proposes updates weekly.
- CI runs `pip-audit` and `npm audit` on every push (report only, so an advisory with no fix does not block work).
- Secrets live in environment variables (`.env` is git-ignored; `render.yaml` marks keys as `sync: false`). If a key may
  have leaked, create a new one, update it on Render, then delete the old one.

## Known limitations

- Prompt injection can still change what an answer says (for example add a link). Links in answers open only when clicked,
  in a new tab with no referrer, and nothing happens automatically.
- Email addresses are verified only when email sending is configured; until then the address is not proof of identity.
- The Render free tier is a single instance with an in-memory rate limiter, so limits reset when the server restarts.
- This is a learning and portfolio project, not an audited product. Do not upload documents you cannot afford to lose or
  leak.
