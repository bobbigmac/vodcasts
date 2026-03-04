# Site
- id: vodcasts-news
- title: VODcasts News
- subtitle: News & video feeds
- description: Global news, science, and video feeds from BBC, Euronews, Al Jazeera, DW, PBS, TED.
- base_path: /

# Defaults
- min_hours_between_checks: 2
- request_timeout_seconds: 25
- user_agent: actual-plays/vodcasts (+https://github.com/)

# Feeds

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

## dw-persian-all
- url: http://rss.dw-world.de/xml/rss-per-all_volltext
- title: Deutsche Welle — Persian (All)
- category: news
- tags: dw, persian, germany

## pbs-nova-video
- url: http://feeds.pbs.org/pbs/wgbh/nova-video
- disabled: media_probe: enclosure probe failed (3 sampled) (cache) (checked 2026-03-04)
- title: NOVA — PBS
- category: news
- tags: pbs, nova, science, video

## ted-talks-video
- url: http://feeds.feedburner.com/TEDTalks_video
- disabled: Redundant, hd should be widely enough available
- title: TED Talks Daily (Video)
- category: news
- tags: ted, video, talks

## ted-talks-hd
- url: https://feeds.feedburner.com/TedtalksHD
- title: TED Talks Daily (HD)
- category: news
- tags: ted, video, hd

## science-friday-video
- url: https://www.sciencefriday.com/feed/podcast/podcast-video/
- title: Science Friday Videos
- category: news
- tags: science, pbs, video

## uctv-science-video
- url: https://podcast.uctv.tv/uctv_video_science.rss
- title: UCTV Science (Video)
- category: news
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

