from backend.fusion import fuse_category_scores


def test_high_confidence_requires_score_margin_and_independent_evidence():
    result = fuse_category_scores(
        caption={"food": .94, "learning": .1},
        visual={"food": .89, "learning": .15},
        fallback={"food": .8},
    )
    assert result.category == "food"
    assert result.confidence == "high"
    assert result.auto_file is True
    assert result.margin >= .15


def test_single_modality_never_auto_files_without_confirmation():
    result = fuse_category_scores(caption={"technology": .99, "marketing": .01})
    assert result.category == "technology"
    assert result.auto_file is False
    assert result.confidence == "medium"


def test_missing_evidence_stays_in_review():
    result = fuse_category_scores()
    assert result.category == "review"
    assert result.confidence == "low"
    assert result.auto_file is False
