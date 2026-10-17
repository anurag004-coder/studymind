"""Mastery tracking, Spaced Repetition (SM-2/FSRS), and Exam Planning per QUIZ_ASSESSMENT.md §5."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.quiz import ReviewSchedule, Topic, TopicMastery


class MasteryService:
    """Calculates student mastery, updates spaced repetition schedules, and plans study."""

    @staticmethod
    async def update_topic_mastery(
        user_id: str,
        topic_id: str | None,
        score: float,
        max_score: float,
        difficulty: int,
        db: AsyncSession,
    ) -> float:
        """Updates user's mastery level for a topic using Bayesian/EMA update.

        Returns updated mastery (0.0 to 1.0).
        """
        if not topic_id or max_score <= 0:
            return 0.0

        stmt = select(TopicMastery).where(
            TopicMastery.user_id == user_id,
            TopicMastery.topic_id == topic_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()

        ratio = max(0.0, min(1.0, score / max_score))
        # Weight by difficulty: harder question gives slightly higher weight
        diff_weight = 0.8 + (difficulty * 0.1)  # 0.9 to 1.3
        weighted_ratio = max(0.0, min(1.0, ratio * diff_weight))

        alpha = 0.25  # Learning rate

        if not row:
            new_mastery = round(weighted_ratio, 3)
            row = TopicMastery(
                user_id=user_id,
                topic_id=topic_id,
                mastery=new_mastery,
                attempts_count=1,
                last_attempt_at=datetime.now(timezone.utc),
            )
            db.add(row)
        else:
            old_mastery = row.mastery
            new_mastery = round(old_mastery * (1 - alpha) + weighted_ratio * alpha, 3)
            row.mastery = max(0.0, min(1.0, new_mastery))
            row.attempts_count += 1
            row.last_attempt_at = datetime.now(timezone.utc)

        await db.flush()
        return row.mastery

    @staticmethod
    async def update_review_schedule(
        user_id: str,
        question_id: str,
        quality: int,  # 0-5 SM-2 grade (0=fail, 5=perfect)
        db: AsyncSession,
    ) -> ReviewSchedule:
        """Updates spaced repetition schedule using standard SuperMemo-2 (SM-2) algorithm."""
        stmt = select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == question_id,
        )
        schedule = (await db.execute(stmt)).scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if not schedule:
            schedule = ReviewSchedule(
                user_id=user_id,
                question_id=question_id,
                due_at=now,
                stability=1.0,
                ease=2.5,
                lapses=0,
                last_result="new",
            )
            db.add(schedule)

        ease = schedule.ease
        lapses = schedule.lapses
        stability = schedule.stability

        if quality < 3:
            # Lapse
            interval_days = 1
            lapses += 1
            stability = max(1.0, stability * 0.8)
            last_result = "lapse"
        else:
            # Success: update ease
            # EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
            delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
            ease = max(1.3, ease + delta)

            if schedule.last_result == "lapse" or schedule.last_result == "new":
                interval_days = 1
            elif stability <= 1.5:
                interval_days = 6
            else:
                interval_days = max(1, round(stability * ease))

            stability = max(1.0, float(interval_days))
            last_result = "correct"

        schedule.due_at = now + timedelta(days=interval_days)
        schedule.ease = round(ease, 3)
        schedule.lapses = lapses
        schedule.stability = round(stability, 2)
        schedule.last_result = last_result

        await db.flush()
        return schedule

    @staticmethod
    async def compute_readiness(
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> tuple[float, str, int]:
        """Calculates syllabus coverage-weighted readiness score (0-100%) and confidence level."""
        stmt = select(Topic).where(Topic.workspace_id == workspace_id)
        topics = (await db.execute(stmt)).scalars().all()
        if not topics:
            return 0.0, "low", 0

        total_weight = 0
        weighted_sum = 0.0
        total_attempts = 0

        for t in topics:
            c_count = len(json.loads(t.chunk_ids)) if t.chunk_ids else 1
            weight = max(1, c_count)

            m_stmt = select(TopicMastery).where(
                TopicMastery.user_id == user_id,
                TopicMastery.topic_id == t.id,
            )
            mastery_row = (await db.execute(m_stmt)).scalar_one_or_none()
            if mastery_row:
                weighted_sum += mastery_row.mastery * weight
                total_attempts += mastery_row.attempts_count
            total_weight += weight

        readiness_pct = round((weighted_sum / total_weight) * 100.0, 1) if total_weight > 0 else 0.0

        if total_attempts >= 20:
            confidence = "high"
        elif total_attempts >= 8:
            confidence = "medium"
        else:
            confidence = "low"

        return readiness_pct, confidence, total_attempts

    @staticmethod
    def generate_study_plan(
        exam_name: str,
        exam_date: datetime,
        topics: list[Topic],
        mastery_map: dict[str, float],
        target_score: float,
    ) -> list[dict[str, Any]]:
        """Generates a deterministic rule-based daily study schedule leading up to exam date."""
        now = datetime.now(timezone.utc)
        target_dt = exam_date
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=timezone.utc)
        days_remaining = max(1, (target_dt - now).days)

        # Sort topics by lowest mastery first
        sorted_topics = sorted(topics, key=lambda t: (mastery_map.get(t.id, 0.0), t.name))
        schedule = []
        horizon = min(14, days_remaining)

        if not sorted_topics:
            for i in range(horizon):
                day_num = i + 1
                sched_date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
                schedule.append(
                    {
                        "day_number": day_num,
                        "date": sched_date,
                        "focus_topic": "General Syllabus",
                        "recommended_action": f"Comprehensive review and study session {day_num}",
                        "estimated_time_minutes": 25,
                    }
                )
            return schedule

        topic_count = len(sorted_topics)
        for i in range(horizon):
            day_num = i + 1
            sched_date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
            focus_topic = sorted_topics[i % topic_count]
            m_val = mastery_map.get(focus_topic.id, 0.0)

            if m_val < 0.5:
                action = f"Intensive concept review and 15-question drill on '{focus_topic.name}'"
                est_time = 30
            elif m_val < 0.8:
                action = f"Practice mock quiz & weak-point reinforcement on '{focus_topic.name}'"
                est_time = 20
            else:
                action = f"Spaced review & rapid flashcard test on '{focus_topic.name}'"
                est_time = 15

            schedule.append(
                {
                    "day_number": day_num,
                    "date": sched_date,
                    "focus_topic": focus_topic.name,
                    "recommended_action": action,
                    "estimated_time_minutes": est_time,
                }
            )

        return schedule
