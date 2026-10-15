# Rate Limiting, Usage Quotas, and Backoff Policies

This document specifies the rate limiting, tenant quota tiers, and backpressure policies enforced across the API gateway and RAG service layers.

## Multi-Tier Rate Limiting Architecture

The system uses a two-tier rate limiting strategy implemented via token bucket algorithms backed by Redis and memory fallbacks:

1. **IP-Level Sliding Window**:
   - Every unauthenticated client is bounded by an IP sliding window of **60 requests per minute**.
   - Burst allowance permits up to **10 requests within a 2-second burst window**.
   - If the limit is exceeded, the server responds with HTTP **429 Too Many Requests** accompanied by a `Retry-After: <seconds>` header.

2. **User-Key Tiered Daily Quotas**:
   - **Community / Free Tier**:
     - Maximum 50 query requests per day.
     - Maximum 5 document uploads per day (max 10MB per file).
     - Single document maximum size: 50MB.
   - **Pro Tier**:
     - Maximum 500 query requests per day.
     - Maximum 50 document uploads per day.
     - Access to multi-agent resume tailoring and parallel comparison panels.
   - **Enterprise Tier**:
     - Custom quota limits (default 5,000 query requests per day).
     - Dedicated Qdrant collection partitions.
     - Unlimited document uploads up to organizational storage cap.

## Leaky Bucket Algorithm Implementation

The leaky bucket algorithm is computed using Redis atomic Lua scripts:
- Key format: `rate_limit:{user_id or ip}:{endpoint}:{minute_timestamp}`.
- Expire TTL is set to **120 seconds** to ensure automatic cleanup of expired buckets.
- When Redis is temporarily unreachable, the gateway falls back to an in-memory `collections.OrderedDict` LRU cache storing the last 10,000 active client IP hashes.

## LLM Provider Quota Management & Backoff

To prevent cascading provider outages when downstream APIs hit TPM (Tokens Per Minute) or RPM (Requests Per Minute) ceilings:
- **Exponential Backoff**: Jittered exponential backoff with an initial delay of **500ms**, multiplier of **2.0**, and maximum delay of **8.0s**.
- **Retry Budget**: At most **3 retries** per request before escalating to the fallback provider chain (`ChatGroq` -> `ChatGoogleGenerativeAI`).
- **Circuit Breaker**: If a provider fails 5 consecutive requests within 30 seconds, the circuit opens for **60 seconds**, routing all subsequent queries directly to the secondary provider without waiting for timeouts.
