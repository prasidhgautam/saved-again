import pytest

from backend.classify import analyze


@pytest.mark.parametrize(
    ('caption', 'category', 'subcategory'),
    [
        ('Roasted chicken recipe. Ingredients: chicken, garlic and potatoes.', 'food', 'Recipes'),
        ('A screenplay recipe to make characters dimensional: let them say one thing and do another.', 'filmmaking', 'Writing'),
        ('Improve Meta ads ROAS by testing new creative hooks.', 'marketing', 'Meta ads'),
        ('Three suspense thriller movies you must watch on Prime Video.', 'entertainment', 'Film recommendations'),
        ('Five must-visit hidden gem cafes in Jaipur.', 'places', 'Restaurants & places'),
        ('Generate cinematic video with Veo and Seedance using image prompts.', 'filmmaking', 'Video generation'),
        ('Build a Python coding agent with Claude and an MCP server.', 'technology', 'AI tools'),
        ('Improve your resume and LinkedIn profile to get more job interview requests.', 'career', 'Career & workplace'),
        ('Margin and markup are different pricing concepts for founders.', 'learning', 'Business & ideas'),
        ('India holds many languages, traditions, songs and ways of celebrating.', 'entertainment', 'Indian culture'),
    ],
)
def test_primary_category_uses_intent_not_incidental_words(caption, category, subcategory):
    result = analyze({'id': 'Synthetic001', 'caption': caption})
    assert (result['category'], result['subcategory']) == (category, subcategory)
    assert result['classification_confidence'] in {'medium', 'high'}


def test_ambiguous_engagement_caption_stays_in_review():
    result = analyze({'id': 'Synthetic002', 'caption': 'Comment link and follow for more.'})
    assert result['category'] == 'review'
    assert result['classification_confidence'] == 'low'


def test_meaningful_collection_can_rescue_generic_caption():
    result = analyze({
        'id': 'Synthetic003',
        'caption': 'Photo by Example on November 1, 2026.',
        'collections': ['Film festivals'],
    })
    assert (result['category'], result['subcategory']) == ('filmmaking', 'Festivals & opportunities')


def test_weak_secondary_signal_does_not_create_noisy_cross_filing():
    result = analyze({
        'id': 'Synthetic004',
        'caption': 'A screenplay recipe for writing stronger film characters.',
    })
    assert result['categories'][0] == {'category': 'filmmaking', 'subcategory': 'Writing'}
    assert {'category': 'food', 'subcategory': 'Recipes'} not in result['categories']
