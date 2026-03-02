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
- title: BBC News — Front Page
- category: news
- tags: bbc, uk, headlines

## euronews-news
- url: https://www.euronews.com/rss?format=mrss&level=theme&name=news
- title: Euronews — News
- category: news
- tags: euronews, europe, mrss

## euronews-nocomment
- url: https://www.euronews.com/rss?format=mrss&level=program&name=nocomment
- title: Euronews — No Comment
- category: news
- tags: euronews, video

## euronews-sport
- url: https://euronews.com/rss?format=mrss&level=theme&name=sport
- title: Euronews — Sport
- category: news
- tags: euronews, sport

## euronews-green
- url: https://www.euronews.com/rss?format=mrss&level=vertical&name=green
- title: Euronews — Green
- category: news
- tags: euronews, environment

## aljazeera-all
- url: https://www.aljazeera.com/xml/rss/all.xml
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
- title: NOVA — PBS
- category: news
- tags: pbs, nova, science, video

## ted-talks-video
- url: http://feeds.feedburner.com/TEDTalks_video
- title: TED Talks Daily (Video)
- category: news
- tags: ted, video, talks
