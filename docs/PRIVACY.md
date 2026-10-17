# StudyMind — Privacy, Security & Data Protection Architecture

This document outlines the data protection architecture, regulatory compliance (GDPR and India's DPDP Act 2023), and strict tenant isolation principles enforced across **StudyMind**.

---

## 1. Core Principles

1. **Strict Multi-Tenancy & Zero Data Leakage**: A student's study materials, questions, notes, and quiz results must never be visible, searchable, or accessible by any other user.
2. **Zero Outside Knowledge**: Generated responses must strictly originate from retrieved user-uploaded study material. Outside knowledge is rejected, and unverified claims are dropped.
3. **Right to Be Forgotten**: Immediate, irrevocable, and cascading deletion of all physical files, vector embeddings, database records, and cached items upon request.
4. **Untrusted Data Fencing**: All document text is treated as potentially untrusted user content and isolated using XML fencing to prevent prompt injection and data exfiltration.

---

## 2. Multi-Tenant Isolation Enforcement

Isolation is guaranteed at every architectural layer:

### Database Layer (PostgreSQL)
- Every query to `documents`, `chunks`, `conversations`, `messages`, `study_items`, `topics`, and `quizzes` includes an explicit `user_id` or `workspace.user_id` filter.
- Verified in `backend/tests/test_user_isolation.py` and `backend/tests/test_phase7b_quiz_engine.py`.

### Vector Store Layer (Qdrant)
- Vector searches include a mandatory payload filter:
  ```python
  Filter(
      must=[
          FieldCondition(key="user_id", match=MatchValue(value=user_id)),
          FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)),
      ]
  )
  ```
- Even with vector distance overlap, cross-tenant similarity hits are completely filtered at search time by the Qdrant engine.

### Caching Layer
- Cache keys for retrieval queries are prefixed with SHA-256 hashes of `user_id` and `workspace_id`.
- Clearing a workspace immediately invalidates all associated cached answers.

---

## 3. GDPR & DPDP Right to Erasure (Complete Data Purge)

StudyMind provides three cascading purge endpoints complying with Article 17 of GDPR and Section 12 of the DPDP Act 2023:

### 1. Document Purge (`DELETE /api/v1/documents/{id}`)
- Removes the document record from the database.
- Cascades and deletes all child `pages` and `chunks`.
- Deletes physical storage objects (PDF, extracted images) from MinIO/S3 or disk.
- Removes all vector embeddings from Qdrant matching `document_id`.
- Retires or deletes any derived generated questions in the question bank.
- Invalidates active retrieval cache entries for the parent workspace.

### 2. Workspace Purge (`DELETE /api/v1/workspaces/{id}`)
- Cascades and purges all documents, chunks, and storage objects within the workspace.
- Deletes all topic maps, quiz sessions, user attempts, and flashcards associated with the workspace.
- Purges all vectors for the workspace from Qdrant.

### 3. Complete Account Erasure (`DELETE /api/v1/auth/me`)
- Permanently erases the user account.
- Cascades across all user workspaces, documents, storage objects, vectors, conversations, messages, and study items.
- Revokes active sessions and clears rate-limiting buckets.

---

## 4. Anti-Prompt Injection & Content Security

### Magic Bytes Sniffing & Malware Defense
- Every upload is inspected using magic byte inspection (`%PDF-`, `\x89PNG`, `\xff\xd8\xff`, `PK\x03\x04`). Renaming `.exe` to `.pdf` is detected and blocked.
- Windows PE (`MZ`) and Linux ELF (`\x7fELF`) executables are immediately rejected.
- EICAR malware test signatures are flagged and dropped.
- Zip bomb protection limits uncompressed-to-compressed archive size ratios to $\le 100:1$.

### Untrusted XML Fencing
- Context chunks provided to the LLM are enclosed within `<untrusted_document_context id="C1" ...>` blocks.
- Pre-processing defuses known jailbreaks (e.g., "Ignore previous instructions", "You are now unrestricted").
- LLM instructions enforce that text inside the context tags is strictly source evidence, never instructions.

---

## 5. Credential Security & Encryption

- **Password Storage**: Passwords are hashed using `bcrypt` with salt rounds conforming to OWASP guidelines.
- **Session Tokens**: Short-lived JSON Web Tokens (JWT) signed with HMAC-SHA256 (`HS256`).
- **Secrets Management**: No API keys or secrets are logged or committed to version control; managed via `.env`.
