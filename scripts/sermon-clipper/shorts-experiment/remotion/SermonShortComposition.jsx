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

const transitionFrames = (manifest) => frameCount(Number(manifest?.transition_sec) || 0.35, fpsOrDefault(manifest));

const endCardFrames = (manifest) => Math.max(30, Math.round(fpsOrDefault(manifest) * 1.25));

export const calculateShortMetadata = ({props}) => {
  const manifest = props?.manifest ?? {};
  const fps = fpsOrDefault(manifest);
  const clips = manifest.clips || [];
  const clipFrames = clips.reduce((sum, clip) => sum + frameCount(clip.duration_sec, fps), 0);
  const transitionTotal = Math.max(0, clips.length - 1) * transitionFrames(manifest);
  return {
    fps,
    width: Math.max(360, Number(manifest.width) || 1080),
    height: Math.max(640, Number(manifest.height) || 1920),
    durationInFrames: Math.max(clipFrames + transitionTotal + endCardFrames(manifest), fps * 4),
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

const ClipCard = ({clip, theme, index, totalClips, intro}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const color = palette[index % palette.length];
  const lift = spring({fps, frame, config: {damping: 200}});
  const introOpacity = interpolate(frame, [0, 8, 24, 40], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fadeOut = interpolate(frame, [durationInFrames - 8, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const videoScale = interpolate(frame, [0, durationInFrames], [1.05, 1.0], {
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
          transform: 'scale(1.18)',
          opacity: 0.78,
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
            'linear-gradient(180deg, rgba(2,6,23,0.24) 0%, rgba(2,6,23,0.10) 18%, rgba(2,6,23,0.50) 58%, rgba(2,6,23,0.92) 100%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(circle at 18% 14%, ${color}22 0%, transparent 28%)`,
        }}
      />

      <AbsoluteFill style={{padding: '58px 54px 80px 54px', display: 'flex', flexDirection: 'column'}}>
        <ThemePill theme={theme} color={color} />
        <ProgressRail index={index} total={totalClips} color={color} />

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: 18,
            color: '#cbd5e1',
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: 1.1,
            textTransform: 'uppercase',
            gap: 20,
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
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 14,
                marginTop: 18,
                alignItems: 'center',
              }}
            >
              {clip.speaker_label ? (
                <div
                  style={{
                    background: color,
                    color: '#111827',
                    borderRadius: 999,
                    padding: '8px 14px',
                    fontSize: 20,
                    fontWeight: 900,
                    letterSpacing: 0.7,
                    textTransform: 'uppercase',
                  }}
                >
                  {clip.speaker_label}
                </div>
              ) : null}
              {decorators.map((decorator, decoratorIndex) => (
                <div
                  key={`${decorator}-${decoratorIndex}`}
                  style={{
                    background: 'rgba(148,163,184,0.16)',
                    color: '#e2e8f0',
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
    </AbsoluteFill>
  );
};

const TransitionCard = ({theme, index, clip}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const color = palette[index % palette.length];
  const opacity = interpolate(frame, [0, 3, durationInFrames - 3, durationInFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const shift = interpolate(frame, [0, durationInFrames], [32, -20], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const decorator = decoratorList(clip.decorators)[0] || clip.context || theme;
  return (
    <AbsoluteFill
      style={{
        opacity,
        background:
          `radial-gradient(circle at 20% 20%, ${color}40 0%, transparent 26%), linear-gradient(180deg, #020617 0%, #0f172a 100%)`,
        justifyContent: 'center',
        padding: '0 70px',
      }}
    >
      <div
        style={{
          transform: `translateY(${Math.round(shift)}px)`,
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
        }}
      >
        <div
          style={{
            color: color,
            fontSize: 26,
            fontWeight: 900,
            letterSpacing: 1.3,
            textTransform: 'uppercase',
          }}
        >
          {theme}
        </div>
        <div
          style={{
            color: '#f8fafc',
            fontSize: 74,
            fontWeight: 950,
            lineHeight: 0.94,
            textWrap: 'balance',
          }}
        >
          {decorator}
        </div>
      </div>
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
  const bumperFrames = transitionFrames(manifest);
  return (
    <AbsoluteFill style={{backgroundColor: '#020617'}}>
      <Series>
        {clips.map((clip, index) => (
          <React.Fragment key={`${clip.path}-${index}`}>
            <Series.Sequence durationInFrames={frameCount(clip.duration_sec, fpsOrDefault(manifest))}>
              <ClipCard
                clip={clip}
                theme={theme}
                index={index}
                totalClips={clips.length}
                intro={index === 0 ? String(manifest?.intro || '') : ''}
              />
            </Series.Sequence>
            {index < clips.length - 1 ? (
              <Series.Sequence durationInFrames={bumperFrames}>
                <TransitionCard theme={theme} index={index + 1} clip={clip} />
              </Series.Sequence>
            ) : null}
          </React.Fragment>
        ))}
        <Series.Sequence durationInFrames={endCardFrames(manifest)}>
          <OutroCard theme={theme} outro={outro} />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
