# PodcastIndex Sector Suggestions for Video-First Deployments

Exploration of `podcastindex_feeds.db` (local dump, no API calls) to identify non-church sectors with substantial video-based feeds suitable for vodcast-style deployments. Data from `scripts/explore_sectors_quick.py` and `scripts/explore_podcastindex_sectors.py`.

## Methodology

- **Source**: Local `podcastindex-feeds/podcastindex_feeds.db`
- **Video detection**: `newestEnclosureUrl` contains `.mp4`, `.m4v`, `.webm`, `.mov`, or `.m3u8`
- **Filters**: `dead=0`, `lastHttpStatus=200`, `episodeCount>=5`, `popularityScore>=5`
- **Excluded**: Religion, spirituality, Christianity (already covered by church.md)

## Video Feed Counts by Category (popularity ≥ 5)

| Category   | Video Feeds | Notes                                      |
|-----------|-------------|--------------------------------------------|
| News      | 194         | Strongest non-church sector; many daily    |
| Education | 105         | Lectures, courses, how-to, ESL, STEM       |
| Leisure   | 101         | Hobbies, DIY, crafts, how-to               |
| Business  | 68          | Real estate, trading, entrepreneurship     |
| Technology| 60          | Dev, hardware, security, Apple events      |
| Arts      | 35          | Photography, brewing, cooking              |
| TV        | 27          | Film/TV discussion, reviews                |
| Society   | 26          | Culture, politics, documentary             |
| Science   | 21          | Research, explainers                      |
| Health    | 18          | Nutrition, wellness, medical               |
| Music     | 15          | Performances, interviews                   |
| Kids      | 14          | Family-friendly content                    |
| Sports    | 13          | Analysis, highlights                       |
| Comedy    | 12          | Stand-up, talk shows                       |

## Recommended Sectors

### 1. Education (105 video feeds)

**Why**: High volume, consistent video (lectures, tutorials, courses). Often audio accompanies video.

**Sample feeds** (verified in DB):
- Adafruit Industries (1000+ eps)
- Paul's Security Weekly (Video) (1000+ eps)
- English ESL (999 eps)
- HVAC Know It All Podcast (556 eps)
- Limitless Mindset (Videos) (451 eps)
- 3D Printing Projects (362 eps)
- Python on Hardware (307 eps)
- VOA Learning English - Everyday Grammar Video (250 eps)

**Sub-niches**: STEM, language learning, trades (HVAC, 3D printing), professional development.

### 2. News (194 video feeds)

**Why**: Largest video sector. Many major outlets (BBC, AP, etc.) publish video podcasts. Daily cadence.

**Caveat**: `feeds/news-podcastindex-candidates.md` shows many are audio-only; validate enclosure type before adding. The 194 count includes both video-only and mixed.

**Sub-niches**: Daily headlines, politics, business news, international.

### 3. Leisure / How-To (101 video feeds)

**Why**: Niche but engaged. DIY, crafts, hobbies, cooking, photography. Strong visual component.

**Sample feeds**:
- Basic Brewing Video (385 eps)
- The Art of Photography (381 eps)
- Behind the Shot - Video (200 eps)
- Start Cooking (60 eps)
- PHOTOGRAPHY 101 (62 eps)

**Sub-niches**: Photography, crafts, cooking, brewing, home improvement.

### 4. Business (68 video feeds)

**Why**: Professional audience, monetization potential. Mix of interviews, tutorials, real estate.

**Sample feeds**:
- Learn To Trade Stocks and Options (100 eps)
- New Media Show (Video) (300 eps)
- Handmade & Beyond Podcast (405 eps)
- SuperToast [Video] (500 eps)
- Pass the Real Estate Exam with PrepAgent (91 eps)

**Sub-niches**: Investing, real estate, entrepreneurship, marketing.

### 5. Technology (60 video feeds)

**Why**: Tech audience expects video. Conferences, demos, hardware.

**Sample feeds**:
- Microsoft Mechanics Podcast (100 eps)
- Apple Events (video) (65 eps)
- #heiseshow (SD-Video) (396 eps)
- Geek News Central Podcast (Video) (38 eps)

**Sub-niches**: Dev tools, security, hardware, Apple/Google events.

### 6. Health & Wellness (18 video feeds)

**Why**: High intent. Nutrition, fitness, mental health. Often visual (exercises, cooking).

**Sample feeds**:
- NutritionFacts.org Video Podcast (100 eps)
- Bulletproof Video (96 eps)
- Obesity Research and Prevention (Video) (100 eps)
- Eczema Kids - Natural Eczema Solutions (220 eps)

**Sub-niches**: Nutrition, fitness, medical education, wellness.

### 7. Arts / Creative (35 video feeds)

**Why**: Visual medium. Photography, film, brewing, cooking.

**Sub-niches**: Photography, film/TV, crafts, food & drink.

### 8. Kids & Family (14 video feeds)

**Why**: Niche but underserved. Parents seek safe, curated video.

**Caveat**: Smaller pool; may need manual curation for quality/appropriateness.

### 9. Science (21 video feeds)

**Why**: Explainers, research outreach. Often benefits from visuals.

**Sub-niches**: Physics, biology, general science education.

## Lower-Priority Sectors

- **Comedy** (12): Often audio-first; video may be repurposed.
- **Sports** (13): Highlights and analysis; rights/licensing considerations.
- **Music** (15): Performances; licensing varies.
- **TV** (27): Film/TV discussion; overlaps with Arts.

## Next Steps

1. **Query candidates**: Use `scripts/explore_podcastindex_sectors.py` or `scripts/explore_sectors_quick.py` to generate candidate lists per sector.
2. **Validate enclosures**: Run a validation pass (like `validate_church_candidates.py`) to confirm video enclosures and filter audio-only.
3. **Create feeds files**: Add `feeds/education.md`, `feeds/news.md`, etc., mirroring `church.md` structure.
4. **Curate**: Manual review for quality, dead feeds, and niche fit.

## Helpers

- `scripts/explore_sectors_quick.py` — Fast category + sample queries
- `scripts/explore_podcastindex_sectors.py` — Full sector exploration (slower)
- `scripts/podcast-transcription-miner/query_church_feeds.py` — Template for sector-specific query scripts (adapt for education, business, etc.)
- `scripts/podcast-transcription-miner/validate_church_candidates.py` — Template for enclosure validation (adapt for other sectors)
