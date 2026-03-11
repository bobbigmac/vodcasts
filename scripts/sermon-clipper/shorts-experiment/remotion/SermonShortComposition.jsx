import React from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  Series,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const palette = ['#f97316', '#14b8a6', '#38bdf8', '#facc15', '#fb7185', '#4ade80'];

const fpsOrDefault = (manifest) => Math.max(12, Number(manifest?.fps) || 30);

const frameCount = (seconds, fps) => Math.max(1, Math.round(Number(seconds || 0) * fps));

const decoratorList = (decorators) =>
  String(decorators || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .slice(0, 3);

const endCardFrames = (manifest) => Math.max(24, Math.round(fpsOrDefault(manifest) * 1.15));

export const calculateShortMetadata = ({props}) => {
  const manifest = props?.manifest ?? {};
  const fps = fpsOrDefault(manifest);
  const clipFrames = (manifest.clips || []).reduce(
    (sum, clip) => sum + frameCount(clip.duration_sec, fps),
    0
  );
  return {
    fps,
    width: Math.max(360, Number(manifest.width) || 1080),
    height: Math.max(640, Number(manifest.height) || 1920),
    durationInFrames: Math.max(clipFrames + endCardFrames(manifest), fps * 4),
  };
};

const ThemePill = ({theme, color}) => (
  <div
    style={{
      alignSelf: 'flex-start',
      background: 'rgba(8,12,22,0.74)',
      border: `2px solid ${color}`,
      borderRadius: 999,
      color: '#f8fafc',
      fontSize: 28,
      fontWeight: 800,
      letterSpacing: 1.4,
      padding: '12px 20px',
      textTransform: 'uppercase',
      boxShadow: `0 0 40px ${color}30`,
      backdropFilter: 'blur(16px)',
    }}
  >
    {theme}
  </div>
);

const ProgressRail = ({index, total, color}) => (
  <div style={{display: 'flex', gap: 10, marginTop: 20}}>
    {Array.from({length: total}).map((_, itemIndex) => (
      <div
        key={itemIndex}
        style={{
          height: 8,
          flex: 1,
          borderRadius: 999,
          background: itemIndex <= index ? color : 'rgba(226,232,240,0.16)',
          opacity: itemIndex === index ? 1 : 0.72,
        }}
      />
    ))}
  </div>
);

const findCaption = (captions, frame, fps) => {
  return (captions || []).find((caption) => {
    const start = Math.floor((Number(caption.start_sec) || 0) * fps);
    const end = Math.ceil((Number(caption.end_sec) || 0) * fps);
    return frame >= start && frame < Math.max(start + 1, end);
  });
};

const CaptionStrip = ({captions, color}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const activeCaption = findCaption(captions, frame, fps);
  if (!activeCaption?.text) {
    return null;
  }
  return (
    <div
      style={{
        position: 'absolute',
        left: 54,
        right: 54,
        bottom: 54,
        display: 'flex',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          maxWidth: '100%',
          background: 'rgba(2,6,23,0.9)',
          border: `2px solid ${color}`,
          borderRadius: 30,
          boxShadow: '0 18px 60px rgba(0,0,0,0.45)',
          color: '#f8fafc',
          fontSize: 34,
          fontWeight: 800,
          lineHeight: 1.15,
          padding: '20px 26px',
          textAlign: 'center',
          textWrap: 'balance',
        }}
      >
        {activeCaption.text}
      </div>
    </div>
  );
};

const ClipCard = ({clip, theme, index, totalClips, intro}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const color = palette[index % palette.length];
  const lift = spring({fps, frame, config: {damping: 200}});
  const introOpacity = interpolate(frame, [0, 8, 24, 40], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fadeOut = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const videoScale = interpolate(frame, [0, durationInFrames], [1.08, 1.0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const decorators = decoratorList(clip.decorators);

  return (
    <AbsoluteFill style={{backgroundColor: '#020617', opacity: fadeOut}}>
      <OffthreadVideo
        src={staticFile(clip.path)}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          filter: 'blur(46px) saturate(0.85) brightness(0.42)',
          transform: 'scale(1.2)',
          opacity: 0.8,
        }}
      />
      <OffthreadVideo
        src={staticFile(clip.path)}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          transform: `scale(${videoScale})`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(180deg, rgba(2,6,23,0.24) 0%, rgba(2,6,23,0.10) 18%, rgba(2,6,23,0.52) 58%, rgba(2,6,23,0.92) 100%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(circle at 18% 14%, ${color}22 0%, transparent 28%)`,
        }}
      />

      <AbsoluteFill style={{padding: '58px 54px 160px 54px', display: 'flex', flexDirection: 'column'}}>
        <ThemePill theme={theme} color={color} />
        <ProgressRail index={index} total={totalClips} color={color} />

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: 18,
            color: '#cbd5e1',
            fontSize: 24,
            fontWeight: 700,
            letterSpacing: 1.1,
            textTransform: 'uppercase',
          }}
        >
          <div>{clip.feed_title}</div>
          <div>
            {index + 1}/{totalClips}
          </div>
        </div>

        {intro ? (
          <div
            style={{
              marginTop: 28,
              maxWidth: '86%',
              alignSelf: 'flex-start',
              background: 'rgba(8,12,22,0.74)',
              borderRadius: 30,
              padding: '18px 24px',
              border: `2px solid ${color}`,
              boxShadow: '0 22px 60px rgba(0,0,0,0.28)',
              opacity: introOpacity,
            }}
          >
            <div style={{color: '#f8fafc', fontSize: 48, fontWeight: 900, lineHeight: 1.02}}>{intro}</div>
          </div>
        ) : null}

        <div style={{flex: 1}} />

        <div
          style={{
            transform: `translateY(${Math.round((1 - lift) * 40)}px)`,
            opacity: lift,
          }}
        >
          <div
            style={{
              background: 'rgba(8,12,22,0.76)',
              borderRadius: 36,
              padding: '28px 30px',
              border: '1px solid rgba(255,255,255,0.08)',
              boxShadow: '0 22px 80px rgba(0,0,0,0.4)',
            }}
          >
            {clip.context ? (
              <div
                style={{
                  color: color,
                  fontSize: 24,
                  fontWeight: 900,
                  letterSpacing: 1.2,
                  marginBottom: 12,
                  textTransform: 'uppercase',
                }}
              >
                {clip.context}
              </div>
            ) : null}
            <div
              style={{
                color: '#f8fafc',
                fontSize: 58,
                lineHeight: 1.02,
                fontWeight: 950,
                textWrap: 'balance',
              }}
            >
              {clip.quote}
            </div>
            {decorators.length ? (
              <div style={{display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 18}}>
                {decorators.map((decorator, decoratorIndex) => (
                  <div
                    key={`${decorator}-${decoratorIndex}`}
                    style={{
                      background: decoratorIndex === 0 ? color : 'rgba(148,163,184,0.16)',
                      color: decoratorIndex === 0 ? '#111827' : '#e2e8f0',
                      borderRadius: 999,
                      padding: '8px 14px',
                      fontSize: 20,
                      fontWeight: 900,
                      letterSpacing: 0.7,
                      textTransform: 'uppercase',
                    }}
                  >
                    {decorator}
                  </div>
                ))}
              </div>
            ) : null}
            {clip.episode_title ? (
              <div
                style={{
                  marginTop: 16,
                  color: '#cbd5e1',
                  fontSize: 22,
                  fontWeight: 600,
                  lineHeight: 1.2,
                }}
              >
                {clip.episode_title}
              </div>
            ) : null}
          </div>
        </div>
      </AbsoluteFill>
      <CaptionStrip captions={clip.captions} color={color} />
    </AbsoluteFill>
  );
};

const OutroCard = ({theme, outro}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({fps, frame, config: {damping: 170}});
  return (
    <AbsoluteFill
      style={{
        background:
          'radial-gradient(circle at 75% 12%, rgba(56,189,248,0.22), transparent 30%), linear-gradient(180deg, #020617 0%, #0f172a 100%)',
        padding: '100px 68px',
        justifyContent: 'space-between',
      }}
    >
      <ThemePill theme={theme} color="#38bdf8" />
      <div
        style={{
          transform: `translateY(${Math.round((1 - enter) * 48)}px)`,
          opacity: enter,
        }}
      >
        <div style={{color: '#f8fafc', fontSize: 88, lineHeight: 0.98, fontWeight: 950, textWrap: 'balance'}}>
          {outro}
        </div>
        <div style={{marginTop: 26, color: '#7dd3fc', fontSize: 28, fontWeight: 700}}>
          prays.be
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const SermonShortComposition = ({manifest}) => {
  const clips = manifest?.clips ?? [];
  const theme = String(manifest?.theme || 'sermon short');
  const outro = String(manifest?.outro || 'Full sermons hold the longer context.');
  return (
    <AbsoluteFill style={{backgroundColor: '#020617'}}>
      <Series>
        {clips.map((clip, index) => (
          <Series.Sequence
            key={`${clip.path}-${index}`}
            durationInFrames={frameCount(clip.duration_sec, fpsOrDefault(manifest))}
          >
            <ClipCard
              clip={clip}
              theme={theme}
              index={index}
              totalClips={clips.length}
              intro={index === 0 ? String(manifest?.intro || '') : ''}
            />
          </Series.Sequence>
        ))}
        <Series.Sequence durationInFrames={endCardFrames(manifest)}>
          <OutroCard theme={theme} outro={outro} />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
