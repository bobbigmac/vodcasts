# Site
- id: vodcasts-dev
- title: VODcasts (Dev)
- subtitle: Static vodcast browser
- description: Small feed set for fast local dev.
- base_path: /
- favicons_path: assets/images/prays-be-favicons
- og_image_path: assets/images/og-promo.png

# Defaults
- min_hours_between_checks: 0
- request_timeout_seconds: 25
- user_agent: actual-plays/vodcasts (+https://github.com/)
- include: news.md

# Feeds

## eaglebrook
- url: https://www.eaglebrookchurch.com/mediafiles/eagle-brook-church-videocast.xml
- title: Eagle Brook Church (videocast)
- category: church

## twit_twit
- url: https://feeds.twit.tv/twit_video_hd.xml
- title: This Week in Tech
- category: twit

## geek-news-central-podcast-video
- url: https://geeknewscentral.com/feed/video/
- title: Geek News Central Podcast (Video)
- category: vodcast

## podcasting-tech
- url: https://feeds.captivate.fm/podcasting-tech/
- title: Podcasting Tech
- category: vodcast

## a-couple-of-rad-techs
- url: https://feeds.captivate.fm/a-couple-of-rad-techs/
- title: A Couple of Rad Techs Podcast
- category: vodcast

## apple-events
- url: https://applehosted.podcasts.apple.com/apple_keynotes/apple_keynotes.xml
- title: Apple Events (video)
- category: vodcast

## mbw-video
- url: https://feeds.twit.tv/mbw_video_hd.xml
- title: MacBreak Weekly (Video)
- category: twit

## ipad-video
- url: https://feeds.twit.tv/ipad_video_hd.xml
- title: iOS Today (Video)
- category: twit

## twig-video
- url: https://feeds.twit.tv/twig_video_hd.xml
- title: Intelligent Machines (Video)
- category: twit

## ww-video
- url: https://feeds.twit.tv/ww_video_hd.xml
- title: Windows Weekly (Video)
- category: twit

## sn-video
- url: https://feeds.twit.tv/sn_video_hd.xml
- title: Security Now (Video)
- category: twit

## twit-specials-video
- url: https://feeds.twit.tv/specials_video_hd.xml
- title: TWiT News (Video)
- category: twit

## twit-events-video
- url: https://feeds.twit.tv/events_video_hd.xml
- title: TWiT Events (Video)
- category: twit

## transcripted-ai-video
- url: https://transcripted.ai/api/rss/consolidated/video
- title: AI Podcast Summaries from Transcripted.ai (VIDEO)
- category: vodcast
