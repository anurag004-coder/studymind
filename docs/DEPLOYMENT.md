# StudyMind — Production Deployment Guide

This guide covers deployment procedures for **StudyMind** in containerized environments (Docker Compose, Kubernetes) and cloud app platforms (Render, Fly.io, AWS).

---

## 1. System Architecture

StudyMind comprises the following services:

```text
               +-----------------------------------+
               |       Reverse Proxy (Nginx/Caddy)  |
               +-----------------+-----------------+
                                 |
           +---------------------+---------------------+
           |                                           |
+----------v----------+                     +----------v----------+
|  FastAPI Backend    |                     |  Frontend Client    |
|  (Port 8000)        |                     |  (Port 3000 / Static|
+----+--------+-------+                     +---------------------+
     |        |
     |        +-------------------+--------------------+
     |                            |                    |
+----v-------+             +------v-----+       +------v------+
| PostgreSQL |             |   Redis    |       |   Qdrant    |
| (Database) |             |  (Broker)  |       | (Vector DB) |
+------------+             +------+-----+       +-------------+
                                  |
                           +------v-------+     +-------------+
                           | Celery Worker|---->| MinIO / S3  |
                           | (Ingestion)  |     | (Storage)   |
                           +--------------+     +-------------+
```

---

## 2. Docker Compose Deployment (Recommended for On-Prem / Single VM)

### Prerequisites
- Docker Engine 24.0+ and Docker Compose v2.20+
- Host with at least 4 GB RAM and 2 vCPUs
- Git

### Quickstart
1. Clone the repository and navigate into the root directory:
   ```bash
   git clone <repo-url> studymind
   cd studymind
   ```

2. Copy the example environment file and configure secrets:
   ```bash
   cp .env.example .env
   ```
   *Important*: Update `JWT_SECRET`, database passwords, MinIO access keys, and add your `GEMINI_API_KEY` (or OpenAI/Claude/Ollama key).

3. Build and launch all services:
   ```bash
   docker compose up -d --build
   ```

4. Verify health and status:
   ```bash
   docker compose ps
   curl http://localhost:8000/health
   ```

5. Access the application:
   - Frontend UI: `http://localhost:3000` (or `http://localhost:8000/app`)
   - Interactive API Docs: `http://localhost:8000/docs`
   - Metrics Endpoint: `http://localhost:8000/metrics`

---

## 3. Environment Variables Reference

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `ENVIRONMENT` | Deployment mode | `production` (or `development`) |
| `DATABASE_URL` | Async PostgreSQL connection string | `postgresql+asyncpg://postgres:postgres@postgres:5432/studymind` |
| `REDIS_URL` | Redis URL for Celery and rate limiting | `redis://redis:6379/0` |
| `QDRANT_URL` | Qdrant vector database URL | `http://qdrant:6333` |
| `STORAGE_ADAPTER` | Storage backend (`s3` or `local`) | `s3` |
| `S3_ENDPOINT_URL` | S3 / MinIO API endpoint | `http://minio:9000` |
| `S3_BUCKET_NAME` | Storage bucket name | `studymind-documents` |
| `S3_ACCESS_KEY` | Storage access key | `minioadmin` |
| `S3_SECRET_KEY` | Storage secret key | `minioadmin` |
| `JWT_SECRET` | 32+ character random secret for JWT | *Generate a secure secret* |
| `JWT_ALGORITHM` | Encryption algorithm | `HS256` |
| `LLM_PROVIDER` | LLM adapter (`gemini`, `openai`, `anthropic`, `ollama`) | `gemini` |
| `GEMINI_API_KEY` | API key if using Google Gemini | `AIza...` |
| `EMBEDDING_PROVIDER` | Embedding adapter (`bge_m3`, `mock`, `openai`) | `bge_m3` |
| `RATE_LIMIT_PER_MINUTE` | Max requests per minute per user | `60` |
| `MAX_FILE_SIZE_BYTES` | Max upload size (bytes) | `52428800` (50 MB) |
| `MAX_ZIP_RATIO` | Max zip bomb decompression ratio | `100.0` |
| `OBSERVABILITY_PROVIDER` | Tracing adapter (`local` or `langfuse`) | `local` |

---

## 4. Database Migrations

Database tables are managed with Alembic. When deploying updates or running in CI:

```bash
# Apply all pending database migrations
docker compose exec api alembic upgrade head

# Create a new migration revision (during development)
docker compose exec api alembic revision --autogenerate -m "description"
```

---

## 5. Reverse Proxy & SSL Configuration (Caddy Example)

Use Caddy for automatic HTTPS and HTTP/2:

```caddyfile
studymind.yourdomain.com {
    encode gzip zstd

    # Backend API and static routes
    reverse_proxy api:8000 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    # Frontend dev server (if hosted separately)
    handle /app* {
        reverse_proxy frontend:3000
    }
}
```

---

## 6. Observability & Monitoring

- **Liveness & Readiness Probes**:
  - Kubernetes / Docker liveness: `GET /health` (exempt from rate limits)
  - Detailed component health: `GET /api/v1/health`
- **Prometheus / System Metrics**:
  - `GET /metrics` provides cache hit rates, active users, total documents, and uptime stats.
- **Traces & Spans**:
  - Configured via `OBSERVABILITY_PROVIDER=langfuse` or `local`.
  - In local mode, query recent spans with `GET /traces`.

---

## 7. Backup and Disaster Recovery

1. **PostgreSQL Backup**:
   ```bash
   docker compose exec -t postgres pg_dump -U postgres studymind > backup_$(date +%F).sql
   ```
2. **MinIO Storage Backup**:
   Sync bucket contents using `rclone` or AWS CLI:
   ```bash
   aws --endpoint-url http://localhost:9000 s3 sync s3://studymind-documents ./backup_storage/
   ```
3. **Qdrant Vector Snapshots**:
   ```bash
   curl -X POST "http://localhost:6333/collections/documents_v1/snapshots"
   ```
