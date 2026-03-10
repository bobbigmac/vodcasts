# Segments and Answers — Spec

## Context

See `site/assets/transcripts`, where we have a lot of transcripts/subtitles that map to slugs/episodes from feeds in our sources (`feeds/church.md`, and others, as some files share references).

## Goal

A basic way of searching the transcripts for "answers" — essentially turning our vtt/srt dataset into a searchable dataset where given a "reddit question" (things like "How can I handle myself better in stressful situations?" or "I struggle to forgive someone who I trusted", or even longer form — we'll use some longform examples to test), we use a hybrid algorithmic+LLM approach.

## Approach

### Algorithmic layer

1. Create a fulltext index (ignoring low value words, strongly favouring words around christian/human/heart & soul issues of culture, spirit, religion, faith, relationships, etc) that maps to timestamps.
2. When querying about a topic, a helper script should be able to query the index (stored in the cache, like all our other stuff, so it can be regenerated if needed, even tho it will mostly be used locally) for topics related to a free text input.
3. Use something like Compromise or other NLP tech to find intros and breaks and ads and such too, and build a kinda "segment" index that based off the content can identify sermons that answer complex questions, with a probability based approach.

### LLM layer

- An LLM (you) will then use the helper to look for candidate responses when given the raw text of a question from reddit.
- The LLM should be able to use the helper to get enough options for files to check in detail.

## Outputs

- You might also find it useful to generate a debug file for each transcript that forms a chapters list, that our site can import aside from just the transcript, and the user can use for nav/skipping, and our system can use for like sermon-only playback.
- Our site supports rendering both chapters and transcripts, so we want to automate the chapters production, including tagging obvious ad-segments by confidence.

## Implementation

- Put it inside `./scripts/answer-engine`, referencing the transcripts from their assets location.
- There are various python libs that might help with this, which you may install, but don't import a full LLM — it will only be used interactively from my IDE, the LLM part will not be deployed.
- Concentrate on making the helper useful to the LLM by supporting different types of query against our dataset, pluggable like a "tool" that is basically helping the LLM query our large data source for segments based off what it decides is important about its queries.

## Documentation

- Document this addition and purpose/use-case to `README.md` and `AGENTS.md` (where the answers tool's usage should be described).
