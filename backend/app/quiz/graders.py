"""Graders for Objective and Rubric-graded questions per QUIZ_ASSESSMENT.md §4."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.adapters.llm import get_llm_adapter

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


class ObjectiveGrader:
    """Deterministic grading for objective question types."""

    @staticmethod
    def grade_mcq(user_answer: Any, correct_answer: Any, marks: float = 1.0) -> tuple[float, bool]:
        """Grades single-choice MCQ."""
        # Convert both to string or integer if possible
        if str(user_answer).strip().lower() == str(correct_answer).strip().lower():
            return marks, True
        return 0.0, False

    @staticmethod
    def grade_multi_select(
        user_answer: Any, correct_answer: Any, marks: float = 1.0
    ) -> tuple[float, bool]:
        u_list = user_answer if isinstance(user_answer, list) else [user_answer]
        c_list = correct_answer if isinstance(correct_answer, list) else [correct_answer]
        user_set = {str(x).strip().lower() for x in u_list}
        correct_set = {str(x).strip().lower() for x in c_list}

        if user_set == correct_set:
            return marks, True
        # Partial credit: proportion of correct choices minus incorrect
        intersection = user_set.intersection(correct_set)
        if len(intersection) > 0 and len(user_set) <= len(correct_set) + 1:
            partial = round(marks * (len(intersection) / len(correct_set)), 2)
            return max(0.0, partial), False
        return 0.0, False

    @staticmethod
    def grade_true_false(
        user_answer: Any, correct_answer: Any, marks: float = 1.0
    ) -> tuple[float, bool]:
        """Grades true/false statements."""
        u_val = str(user_answer).strip().lower() in ("true", "t", "1", "yes")
        c_val = str(correct_answer).strip().lower() in ("true", "t", "1", "yes")
        if u_val == c_val:
            return marks, True
        return 0.0, False

    @staticmethod
    def grade_fill_blank(
        user_answer: Any, correct_answer: Any, marks: float = 1.0
    ) -> tuple[float, bool]:
        """Grades fill-in-the-blank with normalized text comparison and synonym list."""
        u_str = re.sub(r"[^\w\s]", "", str(user_answer).strip().lower())
        accepted = []
        if isinstance(correct_answer, list):
            accepted = [re.sub(r"[^\w\s]", "", str(a).strip().lower()) for a in correct_answer]
        else:
            accepted = [re.sub(r"[^\w\s]", "", str(correct_answer).strip().lower())]

        if any(u_str == acc for acc in accepted if acc):
            return marks, True
        return 0.0, False

    @staticmethod
    def grade_numeric(
        user_answer: Any,
        correct_answer: Any,
        tolerance: float = 0.05,
        marks: float = 1.0,
    ) -> tuple[float, bool]:
        """Grades numeric calculation with relative tolerance."""
        try:
            # Extract first number from strings
            u_match = re.search(r"[-+]?(?:\d*\.\d+|\d+)", str(user_answer))
            c_match = re.search(r"[-+]?(?:\d*\.\d+|\d+)", str(correct_answer))
            if not u_match or not c_match:
                return 0.0, False
            u_num = float(u_match.group())
            c_num = float(c_match.group())

            allowed_delta = max(0.01, abs(c_num) * tolerance)
            if abs(u_num - c_num) <= allowed_delta:
                return marks, True
            return 0.0, False
        except Exception:
            return 0.0, False


class RubricGrader:
    """Grades short and long answers against a rubric of cited key points."""

    def __init__(self) -> None:
        self.llm = get_llm_adapter()
        rubric_path = PROMPTS_DIR / "rubric_grader_v1.txt"
        if not rubric_path.exists():
            rubric_path = Path("backend/app/generation/prompts/rubric_grader_v1.txt")
        self.prompt_template = rubric_path.read_text(encoding="utf-8")

    async def grade(
        self,
        question_stem: str,
        user_answer: str,
        rubric: list[dict[str, Any]],
        total_marks: float,
    ) -> tuple[float, bool, dict[str, Any], bool]:
        """Grades student answer deterministically from LLM point statuses.

        Returns: (earned_score, is_full_marks, evaluation_dict, needs_review)
        """
        if not user_answer or not user_answer.strip():
            return 0.0, False, {"points": [], "comment": "Empty answer"}, False

        if not rubric:
            # Fallback if no rubric exists
            return total_marks, True, {"points": []}, False

        rubric_text = json.dumps(rubric, indent=2)
        prompt = (
            f"{self.prompt_template}\n\n"
            f"QUESTION:\n{question_stem}\n\n"
            f"RUBRIC KEY POINTS:\n{rubric_text}\n\n"
            f"STUDENT ANSWER:\n{user_answer}"
        )

        try:
            resp = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600,
            )
            text = resp.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            try:
                data = json.loads(text)
                points_evaluated = data.get("points", [])
                needs_review = bool(data.get("needs_review", False))
            except Exception:
                # Deterministic fallback when LLM response is not valid JSON
                points_evaluated = []
                u_clean = user_answer.lower()
                stopwords = ("mentions", "which", "about", "their", "where", "there")
                for pt in rubric:
                    desc = pt.get("description", "").lower()
                    words = [w for w in re.findall(r"\b\w{4,}\b", desc) if w not in stopwords]
                    matches = sum(1 for w in words if w in u_clean)
                    ratio = (matches / len(words)) if words else 0.0
                    if ratio >= 0.35:
                        status = "covered"
                    elif ratio >= 0.15:
                        status = "partial"
                    else:
                        status = "missing"
                    points_evaluated.append({"id": pt.get("id"), "status": status})
                needs_review = False
                data = {
                    "points": points_evaluated,
                    "comment": "Deterministic rubric evaluation fallback",
                }

            # Deterministic calculation: score is derived ONLY by rule
            total_earned = 0.0
            total_rubric_marks = sum(p.get("marks", 1.0) for p in rubric) or 1.0

            status_map = {p.get("id"): p.get("status", "missing") for p in points_evaluated}

            for pt in rubric:
                pt_id = pt.get("id")
                pt_marks = float(pt.get("marks", 1.0))
                status = status_map.get(pt_id, "missing").lower()
                if status == "covered":
                    total_earned += pt_marks * 1.0
                elif status == "partial":
                    total_earned += pt_marks * 0.5
                else:
                    total_earned += 0.0

            # Scale to question total_marks if needed
            final_score = round(total_marks * (total_earned / total_rubric_marks), 2)
            is_correct = final_score >= (total_marks * 0.85)

            return final_score, is_correct, data, needs_review

        except Exception as e:
            logger.warning("Rubric grading fallback due to exception: %s", e)
            # Default to partial marks with needs_review flag
            fallback_score = round(total_marks * 0.5, 2)
            return fallback_score, False, {"points": [], "error": str(e)}, True
