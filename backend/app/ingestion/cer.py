"""Character Error Rate (CER) calculation for OCR evaluation per EVALUATION.md §2."""

from rapidfuzz.distance import Levenshtein


def calculate_cer(reference: str, hypothesis: str) -> float:
    """Calculates Character Error Rate:
    (Substitutions + Deletions + Insertions) / len(reference).
    """
    ref_norm = reference.strip()
    hyp_norm = hypothesis.strip()
    if not ref_norm:
        return 0.0 if not hyp_norm else 1.0

    edit_dist = Levenshtein.distance(ref_norm, hyp_norm)
    return float(edit_dist / len(ref_norm))


def calculate_wer(reference: str, hypothesis: str) -> float:
    """Calculates Word Error Rate using token-level edit distance."""
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    edit_dist = Levenshtein.distance(ref_words, hyp_words)
    return float(edit_dist / len(ref_words))
