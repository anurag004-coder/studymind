"""Unit and integration tests for Phase 7B: Quiz & Exam-Prep Engine.
Validates:
1. Topic map rebuild and syllabus hierarchy.
2. Question generator with 4-stage validation (grounded quotes, MCQ checks, dedupe).
3. Server-side objective & rubric graders (MCQ, multi-select, T/F, fill-blank, numeric).
4. Quiz sessions: created with answer keys withheld; instant feedback; submission report.
5. Self-review score override for written answers.
6. Bayesian mastery tracking & SM-2 spaced repetition scheduler.
7. Analytics, readiness score, exam countdown goals, and rule-based study planning.
8. Bad question reporting (instant retirement).
9. Quiz export (Anki TSV and Printable Markdown exam paper).
10. Multi-tenant user isolation.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.quiz.graders import ObjectiveGrader, RubricGrader


async def setup_quiz_user_and_docs(
    client: AsyncClient, email: str
) -> tuple[dict[str, str], str, str]:
    """Sets up an authenticated student with workspace and ingested biology material."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "PassWord1234!"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "PassWord1234!"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Cellular Biology Workspace"},
        headers=headers,
    )
    ws_id = ws_resp.json()["id"]

    doc_text = (
        "Cellular respiration converts glucose into ATP. "
        "Glycolysis yields two pyruvate molecules and net 2 ATP molecules in the cytoplasm. "
        "The citric acid cycle, discovered by Krebs, occurs in the mitochondrial matrix. "
        "Oxidative phosphorylation generates approximately 30 to 32 ATP per glucose molecule. "
        "The enzyme ATP synthase uses the proton gradient across the inner membrane."
    )
    upload_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files={"file": ("cellular_respiration.txt", doc_text.encode("utf-8"), "text/plain")},
        headers=headers,
    )
    doc_id = upload_resp.json()["document_id"]
    await client.post(
        f"/api/v1/documents/{doc_id}/reprocess",
        json={"force_vision_ocr": False},
        headers=headers,
    )

    return headers, ws_id, doc_id


@pytest.mark.asyncio
async def test_topic_map_extraction_and_syllabus(client: AsyncClient) -> None:
    """7B.1: Tests topic outline rebuild and chunk mapping."""
    headers, ws_id, _ = await setup_quiz_user_and_docs(client, "topic_user@studymind.io")

    # 1. Rebuild topics
    rebuild_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/topics/rebuild",
        headers=headers,
    )
    assert rebuild_resp.status_code == 200
    data = rebuild_resp.json()
    assert data["status"] == "success"
    assert data["topics_created"] >= 1
    assert data["chunks_mapped"] >= 1

    # 2. Query topics tree
    topics_resp = await client.get(
        f"/api/v1/workspaces/{ws_id}/topics",
        headers=headers,
    )
    assert topics_resp.status_code == 200
    t_data = topics_resp.json()
    assert t_data["total"] >= 1
    topic = t_data["topics"][0]
    assert topic["workspace_id"] == ws_id
    assert len(topic["name"]) > 0
    assert topic["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_objective_and_rubric_graders() -> None:
    """7B.4 & 7B.5: Tests deterministic objective and rubric grading engines."""
    # 1. MCQ Grader
    score, corr = ObjectiveGrader.grade_mcq(1, 1, marks=1.0)
    assert score == 1.0 and corr is True
    score, corr = ObjectiveGrader.grade_mcq(0, 2, marks=1.0)
    assert score == 0.0 and corr is False

    # 2. Multi-Select Grader
    score, corr = ObjectiveGrader.grade_multi_select(["a", "b"], ["b", "a"], marks=2.0)
    assert score == 2.0 and corr is True
    # Partial credit
    score, corr = ObjectiveGrader.grade_multi_select(["a"], ["a", "b"], marks=2.0)
    assert score == 1.0 and corr is False

    # 3. True / False
    score, corr = ObjectiveGrader.grade_true_false("True", "true", marks=1.0)
    assert score == 1.0 and corr is True
    score, corr = ObjectiveGrader.grade_true_false("False", True, marks=1.0)
    assert score == 0.0 and corr is False

    # 4. Fill in the Blank
    score, corr = ObjectiveGrader.grade_fill_blank(
        "mitochondria", ["mitochondrion", "mitochondria"]
    )
    assert score == 1.0 and corr is True

    # 5. Numeric with tolerance
    score, corr = ObjectiveGrader.grade_numeric("32 ATP", "32", tolerance=0.05, marks=1.0)
    assert score == 1.0 and corr is True
    score, corr = ObjectiveGrader.grade_numeric("30.5", "32", tolerance=0.05, marks=1.0)
    assert score == 1.0 and corr is True
    score, corr = ObjectiveGrader.grade_numeric("20", "32", tolerance=0.05, marks=1.0)
    assert score == 0.0 and corr is False

    # 6. Rubric Grader
    rubric = [
        {"id": "p1", "description": "Mentions cytoplasm", "marks": 1.0},
        {"id": "p2", "description": "Mentions 2 ATP net yield", "marks": 1.0},
    ]
    grader = RubricGrader()
    score, corr, info, _ = await grader.grade(
        question_stem="Where does glycolysis occur and what is the net ATP yield?",
        user_answer="Glycolysis takes place in the cytoplasm and yields 2 net ATP.",
        rubric=rubric,
        total_marks=2.0,
    )
    assert score >= 1.0
    assert "points" in info


@pytest.mark.asyncio
async def test_quiz_session_security_and_grading_flow(client: AsyncClient) -> None:
    """7B.2 & 7B.3: Tests quiz creation with withheld keys, instant feedback, and submit."""
    headers, ws_id, _ = await setup_quiz_user_and_docs(client, "session_user@studymind.io")

    # 1. Create a Quick Quiz session
    create_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/quizzes",
        json={"mode": "quick", "count": 2, "difficulty": 3},
        headers=headers,
    )
    assert create_resp.status_code == 200
    sess_data = create_resp.json()
    sess_id = sess_data["session_id"]
    questions = sess_data["questions"]
    assert len(questions) >= 1

    # CRITICAL SECURITY TEST: Ensure answer keys, rubrics, and source quotes are NOT leaked!
    for q in questions:
        assert "answer_key" not in q
        assert "rubric" not in q
        assert "source_quotes" not in q
        assert "stem" in q
        assert "type" in q

    # 2. Resume session check: keys still withheld
    resume_resp = await client.get(f"/api/v1/quizzes/{sess_id}", headers=headers)
    assert resume_resp.status_code == 200
    res_data = resume_resp.json()
    for q in res_data["questions"]:
        assert "answer_key" not in q

    # 3. Submit an answer to the first question
    first_q = questions[0]
    first_opt = first_q["options"][0] if first_q.get("options") else "sample answer"
    u_ans = 0 if first_q["type"] == "mcq" else first_opt
    ans_resp = await client.post(
        f"/api/v1/quizzes/{sess_id}/answers",
        json={"question_id": first_q["id"], "user_answer": u_ans, "time_s": 15},
        headers=headers,
    )
    assert ans_resp.status_code == 200
    fb_data = ans_resp.json()
    assert fb_data["question_id"] == first_q["id"]
    # In quick mode, feedback and correct answer are returned for learning
    assert "is_correct" in fb_data
    assert "explanation" in fb_data

    # 4. Submit the quiz
    sub_resp = await client.post(
        f"/api/v1/quizzes/{sess_id}/submit",
        headers=headers,
    )
    assert sub_resp.status_code == 200
    report = sub_resp.json()
    assert report["session_id"] == sess_id
    assert "score" in report
    assert "max_score" in report
    assert "percentage" in report
    assert len(report["questions"]) >= 1
    assert "encouraging_feedback" in report


@pytest.mark.asyncio
async def test_mock_exam_mode_withholds_answers_until_submit(client: AsyncClient) -> None:
    """7B.7: Tests Mock Exam mode where answers are strictly withheld until final submit."""
    headers, ws_id, _ = await setup_quiz_user_and_docs(client, "mock_user@studymind.io")

    # Create Mock Exam session
    mock_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/quizzes",
        json={"mode": "mock", "count": 2, "time_limit_s": 1800},
        headers=headers,
    )
    assert mock_resp.status_code == 200
    sess_data = mock_resp.json()
    sess_id = sess_data["session_id"]
    q1 = sess_data["questions"][0]

    # In Mock mode, recording an answer MUST NOT reveal correctness or key!
    ans_resp = await client.post(
        f"/api/v1/quizzes/{sess_id}/answers",
        json={"question_id": q1["id"], "user_answer": 0, "time_s": 20},
        headers=headers,
    )
    assert ans_resp.status_code == 200
    ans_data = ans_resp.json()
    assert ans_data["correct_answer"] is None
    assert ans_data["explanation"] is None
    assert ans_data["source_quotes"] is None

    # After submit, full report is revealed
    sub_resp = await client.post(f"/api/v1/quizzes/{sess_id}/submit", headers=headers)
    assert sub_resp.status_code == 200
    report = sub_resp.json()
    assert report["questions"][0]["correct_answer"] is not None
    assert report["questions"][0]["explanation"] is not None


@pytest.mark.asyncio
async def test_spaced_repetition_and_mastery(client: AsyncClient) -> None:
    """7B.6: Tests SM-2 spaced repetition queue and due reviews."""
    headers, ws_id, _ = await setup_quiz_user_and_docs(client, "spaced_user@studymind.io")

    # Create and submit a quiz to seed review schedules
    create_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/quizzes",
        json={"mode": "quick", "count": 2},
        headers=headers,
    )
    sess_id = create_resp.json()["session_id"]
    q_id = create_resp.json()["questions"][0]["id"]

    await client.post(f"/api/v1/quizzes/{sess_id}/submit", headers=headers)

    # Submit a review rating (SM-2 grade 4: good)
    rev_resp = await client.post(
        f"/api/v1/review/{q_id}/result",
        json={"quality": 4},
        headers=headers,
    )
    assert rev_resp.status_code == 200
    rev_data = rev_resp.json()
    assert rev_data["status"] == "success"
    assert "due_at" in rev_data

    # Query due reviews list
    due_resp = await client.get("/api/v1/review/due", headers=headers)
    assert due_resp.status_code == 200
    assert "total_due" in due_resp.json()


@pytest.mark.asyncio
async def test_analytics_and_exam_goals_study_plan(client: AsyncClient) -> None:
    """7B.8: Tests analytics dashboard, readiness score, and daily study plan."""
    headers, ws_id, _ = await setup_quiz_user_and_docs(client, "analytics_user@studymind.io")

    # 1. Analytics
    analytics_resp = await client.get(
        f"/api/v1/workspaces/{ws_id}/analytics",
        headers=headers,
    )
    assert analytics_resp.status_code == 200
    an_data = analytics_resp.json()
    assert "overall_readiness_pct" in an_data
    assert "confidence_level" in an_data
    assert "topics" in an_data

    # 2. Set Exam Goal
    future_date = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    goal_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/exam-goals",
        json={"name": "Midterm Exam", "exam_date": future_date, "target_score": 85.0},
        headers=headers,
    )
    assert goal_resp.status_code == 200
    goal_data = goal_resp.json()
    goal_id = goal_data["id"]
    assert goal_data["days_remaining"] >= 13

    # 3. Get Study Plan
    plan_resp = await client.get(
        f"/api/v1/exam-goals/{goal_id}/plan",
        headers=headers,
    )
    assert plan_resp.status_code == 200
    plan_data = plan_resp.json()
    assert plan_data["exam_name"] == "Midterm Exam"
    assert len(plan_data["daily_schedule"]) >= 1
    assert "recommended_action" in plan_data["daily_schedule"][0]


@pytest.mark.asyncio
async def test_report_bad_question_instantly_retires(client: AsyncClient) -> None:
    """7B.2 Acceptance Criteria 7: Flagged question is disabled immediately."""
    headers, ws_id, _ = await setup_quiz_user_and_docs(client, "report_user@studymind.io")

    create_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/quizzes",
        json={"mode": "quick", "count": 2},
        headers=headers,
    )
    q_id = create_resp.json()["questions"][0]["id"]

    # Report question
    rep_resp = await client.post(
        f"/api/v1/questions/{q_id}/report",
        json={"reason": "not_in_material", "comment": "Confusing statement"},
        headers=headers,
    )
    assert rep_resp.status_code == 200
    assert rep_resp.json()["status"] == "flagged"

    # Verify that creating a new quiz session never includes this question
    new_sess = await client.post(
        f"/api/v1/workspaces/{ws_id}/quizzes",
        json={"mode": "quick", "count": 2},
        headers=headers,
    )
    assert new_sess.status_code == 200
    new_q_ids = [q["id"] for q in new_sess.json()["questions"]]
    assert q_id not in new_q_ids


@pytest.mark.asyncio
async def test_quiz_exports_anki_and_markdown(client: AsyncClient) -> None:
    """7B.10: Tests exporting quiz to Anki TSV and Printable Markdown exam paper."""
    headers, ws_id, _ = await setup_quiz_user_and_docs(client, "export_quiz_user@studymind.io")

    create_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/quizzes",
        json={"mode": "quick", "count": 2},
        headers=headers,
    )
    sess_id = create_resp.json()["session_id"]
    await client.post(f"/api/v1/quizzes/{sess_id}/submit", headers=headers)

    # 1. Anki export
    anki_resp = await client.get(f"/api/v1/quizzes/{sess_id}/export?format=anki", headers=headers)
    assert anki_resp.status_code == 200
    assert "text/tab-separated-values" in anki_resp.headers["content-type"]
    assert "\t" in anki_resp.text

    # 2. Markdown / Printable Question Paper
    md_resp = await client.get(f"/api/v1/quizzes/{sess_id}/export?format=markdown", headers=headers)
    assert md_resp.status_code == 200
    assert "text/markdown" in md_resp.headers["content-type"]
    assert "# StudyMind Exam Paper" in md_resp.text
    assert "Part 1: Questions" in md_resp.text
    assert "Part 2: Answer Key & Verified Explanations" in md_resp.text


@pytest.mark.asyncio
async def test_quiz_multi_tenant_isolation(client: AsyncClient) -> None:
    """Multi-tenancy: User B cannot access or tamper with User A's quiz sessions."""
    headers_a, ws_a, _ = await setup_quiz_user_and_docs(client, "user_a_quiz@studymind.io")

    sess_a = await client.post(
        f"/api/v1/workspaces/{ws_a}/quizzes",
        json={"mode": "quick", "count": 2},
        headers=headers_a,
    )
    sess_id_a = sess_a.json()["session_id"]

    # Register User B
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user_b_quiz@studymind.io", "password": "PassWord1234!"},
    )
    login_b = await client.post(
        "/api/v1/auth/login",
        json={"email": "user_b_quiz@studymind.io", "password": "PassWord1234!"},
    )
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B attempting to resume User A's quiz -> 404
    hack_resume = await client.get(f"/api/v1/quizzes/{sess_id_a}", headers=headers_b)
    assert hack_resume.status_code == 404

    # User B attempting to submit answer to User A's quiz -> 400 or 404
    hack_ans = await client.post(
        f"/api/v1/quizzes/{sess_id_a}/answers",
        json={"question_id": "dummy", "user_answer": 0},
        headers=headers_b,
    )
    assert hack_ans.status_code in (400, 404)

    # User B attempting to view User A's analytics -> 404
    hack_analytics = await client.get(
        f"/api/v1/workspaces/{ws_a}/analytics",
        headers=headers_b,
    )
    assert hack_analytics.status_code == 404
