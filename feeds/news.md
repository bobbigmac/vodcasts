# Site
- id: vodcasts-news
- title: VODcasts News
- subtitle: News & video feeds
- description: Global news, science, and video feeds from BBC, Euronews, Al Jazeera, DW, PBS, TED.
- base_path: /
- og_image_path: assets/images/og-promo.jpg

# Defaults
- min_hours_between_checks: 2
- request_timeout_seconds: 25
- user_agent: actual-plays/vodcasts (+https://github.com/)

# Feeds

## bbc-world-service-global-news-podcast
- url: https://podcasts.files.bbci.co.uk/p02nq0gn.rss
- title: BBC World Service — Global News Podcast
- category: news
- tags: bbc, world, headlines, daily, audio

## npr-up-first
- url: https://feeds.npr.org/510318/podcast.xml
- title: NPR — Up First
- category: news
- tags: npr, us, morning, daily, audio

## reuters-world-news
- url: https://feeds.megaphone.fm/reutersworldnews
- title: Reuters — Reuters World News
- category: news
- tags: reuters, world, headlines, daily, audio

## the-economist-the-intelligence
- url: https://rss.acast.com/theintelligencepodcast
- title: The Economist — The Intelligence
- category: news
- tags: economist, world, analysis, daily, audio

## wsj-the-journal
- url: https://video-api.wsj.com/podcast/rss/wsj/the-journal
- title: The Wall Street Journal — The Journal.
- category: news
- tags: wsj, business, markets, daily, audio

## cspan-ceasefire
- url: https://feeds.megaphone.fm/CSPAN8750886650
- title: C-SPAN — Ceasefire
- category: news
- tags: cspan, politics, interviews, longform, audio

## bbc-news-front-page
- url: http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/front_page/rss.xml
- disabled: media_probe: no supported enclosures in feed (cache) (checked 2026-03-04)
- title: BBC News — Front Page
- category: news
- tags: bbc, uk, headlines

## euronews-news
- url: https://www.euronews.com/rss?format=mrss&level=theme&name=news
- disabled: media_probe: no supported enclosures in feed (cache) (checked 2026-03-04)
- title: Euronews — News
- category: news
- tags: euronews, europe, mrss

## euronews-nocomment
- url: https://www.euronews.com/rss?format=mrss&level=program&name=nocomment
- disabled: media_probe: no supported enclosures in feed (cache) (checked 2026-03-04)
- title: Euronews — No Comment
- category: news
- tags: euronews, video

## euronews-sport
- url: https://euronews.com/rss?format=mrss&level=theme&name=sport
- disabled: media_probe: no supported enclosures in feed (cache) (checked 2026-03-04)
- title: Euronews — Sport
- category: news
- tags: euronews, sport

## euronews-green
- url: https://www.euronews.com/rss?format=mrss&level=vertical&name=green
- disabled: media_probe: no supported enclosures in feed (cache) (checked 2026-03-04)
- title: Euronews — Green
- category: news
- tags: euronews, environment

## aljazeera-all
- url: https://www.aljazeera.com/xml/rss/all.xml
- disabled: media_probe: no supported enclosures in feed (cache) (checked 2026-03-04)
- title: Al Jazeera — All
- category: news
- tags: aljazeera, middle-east, global

## pbs-nova-video
- url: http://feeds.pbs.org/pbs/wgbh/nova-video
- disabled: media_probe: enclosure probe failed (3 sampled) (cache) (checked 2026-03-04)
- title: NOVA — PBS
- category: science
- tags: pbs, nova, science, video

## ted-talks-video
- url: http://feeds.feedburner.com/TEDTalks_video
- disabled: Redundant, hd should be widely enough available
- title: TED Talks Daily (Video)
- category: lectures
- tags: ted, video, talks

## ted-talks-hd
- url: https://feeds.feedburner.com/TedtalksHD
- title: TED Talks Daily (HD)
- category: lectures
- tags: ted, video, hd

## science-friday-video
- url: https://www.sciencefriday.com/feed/podcast/podcast-video/
- title: Science Friday Videos
- category: science
- tags: science, pbs, video

## uctv-science-video
- url: https://podcast.uctv.tv/uctv_video_science.rss
- title: UCTV Science (Video)
- category: lectures
- tags: science, uctv, university-california, video

## tech-news-weekly-video
- url: https://feeds.twit.tv/tnw_video_hd.xml
- title: Tech News Weekly (Video)
- category: news
- tags: tech, twit, video

## geek-news-central-video
- url: https://geeknewscentral.com/feed/video/
- title: Geek News Central (Video)
- category: news
- tags: tech, geek, video

## vox-today-explained
- url: https://feeds.megaphone.fm/VMP5705694065
- title: Vox — Today, Explained
- category: news
- tags: vox, explainers, current-affairs, daily, audio

## the-rest-is-politics
- url: https://feeds.megaphone.fm/GLT9190936013
- title: Goalhanger — The Rest Is Politics
- category: news
- tags: politics, analysis, interviews, audio

## intelligence-squared
- url: https://feeds.megaphone.fm/NSR6363847171
- title: Intelligence Squared
- category: lectures
- tags: debates, interviews, ideas, longform, audio

## jpl-podcasts
- url: https://www.jpl.nasa.gov/feeds/podcasts/
- title: NASA Jet Propulsion Laboratory (JPL) — Podcasts
- category: science
- tags: nasa, jpl, space, science, audio, video

## gresham-college-lectures
- url: https://feeds.buzzsprout.com/1904814.rss
- title: Gresham College — Lectures
- category: lectures
- tags: lectures, education, public-lectures, uk, audio
