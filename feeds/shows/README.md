# Show filters (JSON)

One file per feed: `feeds/shows/<feed-slug>.json`. Auto-loaded when the feed slug matches.

Format: `{ "leftovers_title": "...", "leftovers_title_full": "...", "leftovers_description": "...", "shows": [...] }`

Each show: `title` (in-context), `title_full` (out-of-context, e.g. "Macworld from Apple"), `description` (short).

Filter types: `title_contains`, `title_contains_any` (values: [...]), `title_regex`, `title_prefix`, `title_suffix`, `description_contains`.

Episodes matching a show's filter go to that show (first match wins). Unmatched go to leftovers. No "all episodes" filter.
