# API Spec (REST, JSON, prefix `/api/v1`)

Auth: `Authorization: Bearer <JWT>`. All resources are scoped to the authenticated user.

## Auth
- `POST /auth/register` {email, password} → 201
- `POST /auth/login` → {access_token}
- `GET /auth/me`

## Workspaces
- `GET /workspaces` · `POST /workspaces` {name} · `DELETE /workspaces/{id}` (cascades)

## Documents
- `POST /workspaces/{wid}/documents` multipart `file` → `{document_id, status:"queued"}`
- `GET /workspaces/{wid}/documents` → list with `status`, `pages`, `ocr_quality`
- `GET /documents/{id}` → metadata + per-stage progress
- `GET /documents/{id}/events` (SSE) → ingestion progress
- `GET /documents/{id}/pages/{n}/image` → page render
- `GET /documents/{id}/file` → original (signed URL)
- `DELETE /documents/{id}` → purge file, chunks, vectors
- `POST /documents/{id}/reprocess` {force_vision_ocr: bool}

## Chat
- `POST /workspaces/{wid}/conversations` {scope:{document_ids?:[...]}}
- `POST /conversations/{cid}/messages` {question, strict_mode?:bool} → streamed (SSE) events:
  `retrieval`, `token`, `verification`, `final`
- Final payload:
```json
{
  "message_id": "...",
  "abstained": false,
  "confidence": "high",
  "answer": [{"text": "…", "citations": [1,2]}],
  "citations": [{"n":1,"document_id":"…","page":12,"quote":"…","bbox":[x0,y0,x1,y1],"chunk_id":"…"}],
  "dropped_claims": 0,
  "missing_info": null,
  "suggestions": []
}
```
- `GET /conversations/{cid}/messages`
- `POST /messages/{id}/feedback` {rating: up|down, reason?: wrong|not_in_source|incomplete|other, comment?}

## Study tools
- `POST /workspaces/{wid}/study/summary` {document_ids, length}
- `POST /workspaces/{wid}/study/flashcards` {document_ids, count, topic?}
- `POST /workspaces/{wid}/study/quiz` {document_ids, count, difficulty, topic?}
- `GET /workspaces/{wid}/study/items`

## Ops
- `GET /health` · `GET /metrics`
- Error format: `{ "error": {"code": "...", "message": "..."} }`
- Rate limit: 60 req/min/user (configurable); upload limit per `MAX_UPLOAD_MB`.

## Quiz & Exam-Prep endpoints
See `QUIZ_ASSESSMENT.md` §8 (topics, quizzes, answers, submit, analytics, review/due, exam-goals, question report, export). Answer keys/rubrics are never returned before submission.
