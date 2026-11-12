"""Calibrated multimodal category-score fusion for SavedAgain."""

from __future__ import annotations

from dataclasses import asdict, dataclass


OUTER_WEIGHTS = {"text": 0.50, "visual": 0.20, "exemplar": 0.20, "fallback": 0.10}
TEXT_WEIGHTS = {"caption": 0.40, "transcript": 0.35, "ocr": 0.25}
HIGH_SCORE = 0.72
HIGH_MARGIN = 0.15
MEDIUM_SCORE = 0.55
MEDIUM_MARGIN = 0.08
VERSION = "fusion-v1"


@dataclass(frozen=True)
class FusionResult:
    category: str
    score: float
    margin: float
    confidence: str
    auto_file: bool
    alternatives: list[dict]
    evidence: list[str]
    explanation: str
    version: str = VERSION

    def as_dict(self) -> dict:
        return asdict(self)


def _clean(scores: dict | None) -> dict[str, float]:
    return {
        str(category): max(0.0, min(1.0, float(score)))
        for category, score in (scores or {}).items()
        if score is not None
    }


def _weighted(parts: dict[str, dict[str, float]], weights: dict[str, float]) -> dict[str, float]:
    available = {name: _clean(parts.get(name)) for name in weights}
    available = {name: scores for name, scores in available.items() if scores}
    if not available:
        return {}
    total_weight = sum(weights[name] for name in available)
    categories = {category for scores in available.values() for category in scores}
    return {
        category: sum(
            (weights[name] / total_weight) * scores.get(category, 0.0)
            for name, scores in available.items()
        )
        for category in categories
    }


def fuse_category_scores(
    *,
    caption: dict | None = None,
    transcript: dict | None = None,
    ocr: dict | None = None,
    visual: dict | None = None,
    exemplar: dict | None = None,
    fallback: dict | None = None,
    collection_confirmed: bool = False,
) -> FusionResult:
    """Fuse normalized category scores and apply SavedAgain's review gates.

    Missing modalities are renormalized. High confidence additionally requires
    two independent evidence types, a confirmed exemplar, or collection evidence.
    """

    text = _weighted(
        {"caption": caption or {}, "transcript": transcript or {}, "ocr": ocr or {}},
        TEXT_WEIGHTS,
    )
    modalities = {
        "text": text,
        "visual": _clean(visual),
        "exemplar": _clean(exemplar),
        "fallback": _clean(fallback),
    }
    combined = _weighted(modalities, OUTER_WEIGHTS)
    evidence = [name for name, scores in modalities.items() if scores]
    if not combined:
        return FusionResult(
            category="review",
            score=0.0,
            margin=0.0,
            confidence="low",
            auto_file=False,
            alternatives=[],
            evidence=[],
            explanation="No analysis evidence was available; keep this save in Needs review.",
        )

    ranked = sorted(combined.items(), key=lambda pair: (-pair[1], pair[0]))
    category, score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = score - runner_up
    independent = len(evidence) >= 2 or collection_confirmed or bool(modalities["exemplar"])
    if score >= HIGH_SCORE and margin >= HIGH_MARGIN and independent:
        confidence, auto_file = "high", True
    elif score >= MEDIUM_SCORE and margin >= MEDIUM_MARGIN:
        confidence, auto_file = "medium", False
    else:
        confidence, auto_file = "low", False

    shown = [{"category": name, "score": round(value, 4)} for name, value in ranked[1:4]]
    explanation = (
        f"{category} scored {score:.2f} with a {margin:.2f} margin using "
        f"{', '.join(evidence) or 'no'} evidence."
    )
    if confidence == "high" and not auto_file:
        explanation += " It remains reviewable because independent evidence is missing."
    return FusionResult(
        category=category,
        score=round(score, 6),
        margin=round(margin, 6),
        confidence=confidence,
        auto_file=auto_file,
        alternatives=shown,
        evidence=evidence,
        explanation=explanation,
    )
