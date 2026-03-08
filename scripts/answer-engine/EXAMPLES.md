# Answer Engine Examples

These are real `query answer` runs against the current church corpus on March 8, 2026, using:

```text
VOD_ANSWER_LLM_PROVIDER=openai
VOD_ANSWER_OPENAI_MODEL=gpt-4o-mini
--answers 1 --review-candidates 1 --per-query-limit 4 --candidates 80
```

The goal here is to show the current live shape of the answers, not a cleaned-up ideal.

## 1. Fear / instability

**Question**

```text
How do I deal with fear when life feels unstable?
```

**Suggested reply**

```text
When you're feeling overwhelmed by fear and instability, remember that your mind may be focused on negative thoughts and past failures. Try to shift your perspective by recalling the times when you felt supported or experienced something miraculous. It's okay to acknowledge your doubts without letting them define your reality. Reach out to God regularly with your feelings, allowing space for trust to grow gradually.
```

**Watch**

```text
/eric-walsh-sermons/2026-02-17-eric-walsh-the-prayer-shift-for-2026-1kzkh9/#t=705
```

**Grounding quote**

```text
He starts to throw you that stuff because in your doubt and your fear, you are looking to find a way to regain pleasure
```

**Tags**

```text
fear, faith, resilience
```

## 2. Prayer when you do not know what to say

**Question**

```text
I want to pray but I don't even know what to say
```

**Suggested reply**

```text
When you feel lost on what to say in prayer, remember that it’s okay to be honest with God. Just express your real feelings and struggles. You don’t have to have it all figured out; simply bring your authentic self to Him, and trust that He hears you.
```

**Watch**

```text
/calvary-chapel-fort-lauderdale/2026-01-18-week-three-ask-1kzwl6/#t=1980
```

**Grounding quote**

```text
so this is a place where God answers prayer
```

**Tags**

```text
prayer, authenticity, faith
```

## 3. God feels silent

**Question**

```text
I've been praying for a long time and God feels silent
```

**Suggested reply**

```text
If you're feeling like God is silent, remember that prayer can be more relational and alive than just a private practice. It might help to explore new ways to pray or share this struggle with others. Don't worry about the silence; keep bringing your feelings to God honestly as you keep seeking Him.
```

**Watch**

```text
/connexus-church/2026-03-01-how-to-pray-with-someone-without-it-being-awkward-vijay-krish-1cz24n/#t=258
```

**Grounding quote**

```text
so kind of praying on my own is just sort of difficult
```

**Tags**

```text
prayer, faith, connection
```

## 4. Comparison / misery

**Question**

```text
I keep comparing myself to other people and it's making me miserable
```

**Suggested reply**

```text
Instead of comparing yourself to others, focus on embracing your unique journey and limits. Remember that God's love is present within your struggles and limits, and by submitting to them, you can truly come alive. Everyone has their own challenges, so celebrate your own gifts and your path rather than measuring it against someone else's.
```

**Watch**

```text
/bridgetown/2026-03-02-the-good-news-about-our-bodies-chronic-illness-disability-10g2du/#t=2083
```

**Grounding quote**

```text
Luke 14, Jesus says, whoever does not carry their cross and follow me cannot be my disciple
```

**Tags**

```text
self-acceptance, faith, personal growth
```

## 5. Chronic illness / disability

**Question**

```text
How should I think about chronic illness or disability as a Christian?
```

**Suggested reply**

```text
Chronic illness or disability can indeed lead to anger and deep questions, but remember, it's in these struggles that you may find a profound closeness to God. He understands your pain and walks with you through it. Embrace the journey of knowing yourself and God better during this time, and bring your honest feelings to Him.
```

**Watch**

```text
/bridgetown/2026-03-02-the-good-news-about-our-bodies-chronic-illness-disability-10g2du/#t=2820
```

**Grounding quote**

```text
at the height of his suffering, Job still displays trust in God that prophetically points to that day to Jesus
```

**Tags**

```text
faith, chronic illness, spiritual growth
```

## What This Shows Right Now

- The recommendation tone is much closer to the live-site goal: it reads more like advice to a person than analysis of a transcript.
- Retrieval is still stronger than quote-picking. The quote is sometimes weaker or more oblique than the recommendation.
- The engine can still land on an indirectly relevant section rather than the sharpest possible one, especially for comparison-style questions.
- Prayer, fear, suffering, and explicitly named struggles are still the strongest categories.
