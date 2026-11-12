"""Conservative, evidence-based first-pass organization.

The classifier scores multiple independent signals instead of letting the first
keyword win. Broad words such as "AI", "content", or "recipe" are deliberately
weaker than task-specific phrases.
"""
from collections import Counter
import re

CATEGORIES = {
    'filmmaking': ('AI & Filmmaking', 'filmmaking.webp', '#d6a20b'),
    'marketing': ('Marketing', 'marketing.webp', '#a42d21'),
    'food': ('Food', 'food.webp', '#154c37'),
    'technology': ('AI & Technology', 'technology.webp', '#35604c'),
    'places': ('Places & Experiences', 'places.webp', '#aa422e'),
    'learning': ('Learning & Ideas', 'learning.webp', '#96751d'),
    'wellbeing': ('Fitness & Wellbeing', 'wellbeing.webp', '#245c4c'),
    'style': ('Style & Everyday', 'style.webp', '#aa422e'),
    'entertainment': ('Cinema & Culture', 'entertainment.webp', '#94731a'),
    'career': ('Career & Work', 'career.webp', '#245c4c'),
    'review': ('Needs review', 'review.webp', '#7f7562'),
}

# (category, subcategory, evidence pattern, weight). Five is a strong direct
# signal, three is useful context, and one or two is intentionally broad.
RULES = [
 ('food','High protein',r'high[ ._-]?protein|\b\d+\s*(?:g|grams)\s*(?:of\s*)?protein',6),
 ('food','Recipes',r'\bingredients?\b|fried rice|\bchicken\b|pancake|pasta|\bcook(?:ing|ed)?\b|meal prep|\bbreakfast\b|\bdinner\b|paneer|cuisine',5),
 ('food','Recipes',r'\bfoodie\b|easy.{0,24}delicious|\bbiryani\b|\bcurry\b|\bsandwich\b|\bomelette\b|\bdessert\b|\bmomos?\b|\bsalad\b',5),
 ('food','Recipes',r'\bhalwa\b|\bkhichdi\b|\bdosa\b|\bchutney\b|\btikka\b|\brajma\b|\bparatha\b|\bchole\b',6),
 ('food','Recipes',r'\brecipe\b',2),
 ('marketing','Meta ads',r'meta ads|facebook ads|metaad|facebookad|andromeda|ad account|ad set|ad campaign|performance[ ._-]?marketing|paid ads|media[ ._-]?buying|\broas\b|cost per lead',6),
 ('marketing','Hooks & copy',r'copywriting|ad writing|\bhooks?\b|tagline|\bheadline\b|cold email|email outreach|follow[ ._-]?up emails|lead generation',5),
 ('marketing','Creative strategy',r'brand campaign|advertis(?:e|ing|ement)|creative strateg|content strateg|content funnel|sales funnel|\btofu\b|consumer insight|creative concepts|ad budget|call to action|audience.{0,80}(?:message|pain|offer)',5),
 ('marketing','Creative strategy',r'\bmarketing\b|\bbranding\b|social[ ._-]?media[ ._-]?(?:strateg|growth|workflow|manager|marketing)|content growth|viral content|content[ ._-]?creation|sales call',3),
 ('marketing','Research & insights',r'market research|audience research|consumer research|customer insight|research findings',5),
 ('marketing','SEO & discovery',r'\bseo\b|search engine optimi|keyword research|search visibility|website traffic',5),
 ('filmmaking','Editing',r'\bedit(?:ing|or|ors)?\b|premiere|davinci|after effects|rough cut|match cut|colou?r grad|historical footage|moving image archive|motion[ ._-]?design|motion graphic|kinetic caption',6),
 ('filmmaking','Writing',r'screenplay|screenwriting|scriptwriting|storyboard|write.{0,24}(?:film|script)|writing.{0,24}(?:film|script)|story ladder',6),
 ('filmmaking','Writing',r'\bstorytelling\b',3),
 ('filmmaking','Video generation',r'seedance|higgsfield|kling|\bveo\b|\bsora\b|ai[ ._-]?film|ai[ ._-]?video|generat\w*.{0,18}video|video.{0,18}generat\w*|openmontage|video studio|cinematic.{0,24}\bai\b',7),
 ('filmmaking','Video generation',r'youtube automation.{0,100}(?:video|script|thumbnail)|video (?:creation|production|publishing) (?:pipeline|workflow)|scriptwriting.{0,100}thumbnail.{0,100}audio',8),
 ('filmmaking','Cinematography',r'cinematograph|filmmak|\bcamera\b|lighting setup|film.{0,18}\bshot\b|\bshot\b.{0,18}film|sam raimi|film school|\blens\b|\bdirector\b|\bdop\b',6),
 ('filmmaking','Sound',r'sound design|foley|audio edit|voice[ ._-]?over|music production|film.{0,18}sound',6),
 ('filmmaking','Image generation',r'midjourney|image generation|imagegen|nano[ ._-]?banana|stable diffusion|image.{0,18}prompt|prompt.{0,18}image|ai[ ._-]?generated image|photoshop',6),
 ('filmmaking','Acting & casting',r'\bcasting\b|\bacting\b|actingtips|audition|theatre|theater|अभिनय',6),
 ('filmmaking','Festivals & opportunities',r'film.{0,24}submissions|call for entries|short[ ._-]?film[ ._-]?festival|film festivals?',6),
 ('technology','AI tools',r'claude|chatgpt|\bllm\b|\bmcp\b|ai tools|ai engineer|ai agent|artificial intelligence|openai|gemini|perplexity|agentspace',5),
 ('technology','AI tools',r'\bai\b|aitools?|\bgpt\b|hailuoai',1),
 ('technology','Web & design',r'web[ ._-]?design|website|frontend|front[ ._-]?end|ui[ ._-]?ux|figma|shadcn|vercel|\bcss\b|\breact\b|vibe[ ._-]?cod|web development',6),
 ('technology','Software & resources',r'github|open[ ._-]?source|\bsoftware\b|\bcoding\b|programming|repository|\brepos?\b|\bpython\b|\blinux\b|\bwindows\b|\bplugins?\b|workflow automation',5),
 ('technology','Software & resources',r'\bexcel\b|\bblender\b|web[ ._-]?scraping|\bscraping\b|automation tool',5),
 ('places','Travel',r'\btravel\b|itinerary|destination|backpack|weekend.{0,12}trip|visit.{0,18}(?:place|city)|getaway|\btrek\b|\bhiking\b',5),
 ('places','Restaurants & places',r'\brestaurant\b|\bcaf[eé]\b|places to|things to do|places in|must[ ._-]?visit|hidden gem',5),
 ('wellbeing','Movement',r'workout|wrestling|\bbjj\b|martial art|exercise|mobility|strength training|\bgym\b|\byoga\b|\bfitness\b|jiu[ ._-]?jitsu',6),
 ('wellbeing','Movement',r'\bboxing\b|\bmma\b|grappling|self[ ._-]?defen[cs]e|martialarts|ground tactics|pekititirsiakali|tirsia kali|bouldering|climbing|stretching|foot arching|tenouchi|commando training',5),
 ('wellbeing','Wellbeing',r'mental health|therapy|anxiety|meditat|\bsleep\b|wellbeing|wellness|self[ ._-]?care',6),
 ('style','Style & clothing',r'fashion|scarf|balaclava|outfit|clothing|wardrobe|styling|dress.{0,18}tips',6),
 ('style','Everyday techniques',r'life[ ._-]?hack|fingertips|magic trick|organis\w*.{0,18}home|cleaning.{0,18}hack|\bdiy\b',5),
 ('career','Career & workplace',r'\bresign|employment|employee[ ._-]?right|epfo|job search|job interview|hiring|\bresume\b|\bcv\b|\bcareer\b|workplace',7),
 ('career','Career & workplace',r'internship|intership|\bfresher\b|\bjobs?\b|certification|networkai|network with|interview requests?|linkedin profile',6),
 ('learning','Business & ideas',r'entrepreneur|startup|founder|business model|pricing|\bmarkup\b|\bmargin\b|business lessons',6),
 ('learning','Learning & reading',r'\bbooks?\b|\breading\b|philosophy|psychology|\blearning\b|\bhistory\b|education|\bcourse\b|\bscience\b',5),
 ('learning','Everyday reference',r'\blaw\b|\bfraud\b|\bscam\b|mathematical|klein bottle',6),
 ('entertainment','Film recommendations',r'(?:movies?|films?|thrillers?|series).{0,100}(?:recommend|must watch|watchlist|streaming)|featured movies|hidden gem movie|prime video|lionsgate play|jiohotstar',12),
 ('entertainment','Indian culture',r'indian culture|india.{0,120}(?:languages|celebrat|heritage|tradition)|folk legend',8),
 ('entertainment','Cinema & culture',r'\bcinema\b|bollywood|film festival|\bmovie\b|film poster|\bactor\b|\bactress\b|\bpoetry\b|\bpoem\b|shayari|\bsong\b|\bmusic\b|pyaasa|amitabh|guru dutt|prasoon|piyush',5),
 ('entertainment','Humour & inspiration',r'comedy|funny|\bmeme\b|humou?r|laughter|dreamcore|interesting|corporate|trendingreels',4),
 ('entertainment','Poetry & words',r'शायरी|कविता|ग़ज़ल|गजल|नज़्म|नज्म|गुलज़ार|गुलजार|मोहब्बत|\bpoetry\b|\bpoet\b|gulzar|\burdu\b|sher[ ._-]?o[ ._-]?shayari',7),
 ('entertainment','Cinema & culture',r'netflix|prime video|\banime\b|dragonball|jagjitsingh|folk legend|\bsinging\b|\bfestival\b|reshma',5),
 ('entertainment','Humour & inspiration',r'relatable|relationship|couplegoals|mindset|inspiration|positive mindset|fun content|\bpov:|trailerparkboys',3),
 ('entertainment','Games & recreation',r'assetto corsa|no hesi|\bgaming\b|video game|card trick|magic trick',6),
]


def normalize(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def _rank_topics(caption, collections):
    scores = Counter()
    topic_scores = Counter()
    first_seen = {}
    for source, boost in ((caption, 0), (' '.join(collections or []), 2)):
        lower = normalize(source).lower()
        if not lower:
            continue
        for index, (category, subcategory, pattern, weight) in enumerate(RULES):
            if re.search(pattern, lower):
                value = weight + boost
                scores[category] += value
                topic_scores[(category, subcategory)] += value
                first_seen.setdefault((category, subcategory), index)
    if not scores or max(scores.values()) < 3:
        return [('review', 'Unsorted')], 'low'
    ranked_categories = sorted(
        scores,
        key=lambda category: (
            -scores[category],
            -max(v for (c, _), v in topic_scores.items() if c == category),
            min(first_seen[key] for key in first_seen if key[0] == category),
        ),
    )
    primary_category = ranked_categories[0]
    primary_topic = min(
        (key for key in topic_scores if key[0] == primary_category),
        key=lambda key: (-topic_scores[key], first_seen[key]),
    )
    ranked_topics = sorted(topic_scores, key=lambda key: (-topic_scores[key], first_seen[key]))
    pairs = [primary_topic]
    for topic in ranked_topics:
        if topic in pairs or topic_scores[topic] < 5:
            continue
        if topic[0] == primary_category or scores[topic[0]] >= 5:
            pairs.append(topic)
        if len(pairs) == 4:
            break
    runner_up = scores[ranked_categories[1]] if len(ranked_categories) > 1 else 0
    confidence = 'high' if scores[primary_category] >= 6 and scores[primary_category] - runner_up >= 2 else 'medium'
    return pairs, confidence


def analyze(record):
    caption = normalize(record.get('caption',''))
    lower = caption.lower()
    generic = not caption or bool(re.match(r'^(?:photo by |photo shared by |this may contain|this contains|clip$)',lower))
    pairs, confidence = _rank_topics('' if generic else caption, record.get('collections', []))
    primary, sub = pairs[0]
    sentences = re.split(r'(?<=[.!?])\s+|\n+', record.get('caption',''))
    useful = [normalize(s) for s in sentences if len(normalize(s))>15 and not re.match(r'^(?:comment|follow|save this|dm |tag |credit|copyright|disclaimer|#|💬|🔖)',normalize(s),re.I)]
    title = (useful[0] if useful else caption).split('#')[0].strip(' .:-–—👇🚨📌💡')
    title = re.sub(r'@[\w.]+','',title).strip()
    if len(title)>82: title=title[:79].rsplit(' ',1)[0]+'…'
    if generic or len(title)<4 or (not useful and re.match(r'^(?:comment|follow|save this|dm |tag )',title,re.I)):
        title = 'Saved '+('carousel' if record.get('media_type')=='carousel' else 'post')+' · '+record['id']
    summary = ' '.join(useful[:2]) if useful and not generic else 'The available caption does not explain this save. Open the original post for context.'
    summary = re.split(r'Copyright Disclaimer|Copyright disclaimer|#',summary)[0].strip()
    if len(summary)>350: summary=summary[:347].rsplit(' ',1)[0]+'…'
    uses = {
      'filmmaking': 'Revisit when planning a film, writing a scene, or working on an edit.',
      'marketing': 'Revisit before planning your next campaign or creative brief.',
      'food': 'Keep handy when planning a meal or trying a new recipe.',
      'technology': 'Revisit when choosing tools or building your next project.',
      'places': 'Revisit when planning a trip or looking for somewhere to go.',
      'wellbeing': 'Revisit when planning a routine you would like to try.',
      'style': 'Keep handy for a styling idea or practical technique you want to try.',
      'career': 'Revisit when preparing for a career or workplace conversation.',
      'learning': 'Revisit when exploring a new idea or planning what to learn.',
      'entertainment': 'Return when you want a film, cultural reference, or a little inspiration.',
      'review': 'Open the original when you want to remember what caught your eye.',
    }
    hashtags = re.findall(r'#([\w]+)',caption)
    tags = list(dict.fromkeys([CATEGORIES[primary][0],sub]+hashtags))[:12]
    return {'title':title,'summary':summary,'use_when':uses[primary], 'category':primary,
            'subcategory':sub,'categories':[{'category':c,'subcategory':s} for c,s in pairs],
            'tags':tags,'evidence':'caption' if not generic else 'thumbnail',
            'classification_confidence':confidence,
            'organization_status':'needs_review' if primary=='review' else 'organized'}
