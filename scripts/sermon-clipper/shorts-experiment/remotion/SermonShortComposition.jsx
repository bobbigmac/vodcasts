import React from 'react';
import {
  AbsoluteFill,
  Audio,
  interpolate,
  OffthreadVideo,
  Sequence,
  Series,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const palette = ['#f97316', '#14b8a6', '#fb7185', '#38bdf8', '#facc15', '#4ade80'];

const fpsOrDefault = (manifest) => Math.max(12, Number(manifest?.fps) || 30);

const frameCount = (seconds, fps) => Math.max(1, Math.round(Number(seconds || 0) * fps));

const decoratorList = (decorators) =>
  String(decorators || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .slice(0, 3);

const endCardFrames = (manifest) => Math.max(18, Math.round(fpsOrDefault(manifest) * 1.0));

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

const AccentBar = ({color}) => (
  <div
    style={{
      position: 'absolute',
      left: 0,
      top: '14%',
      bottom: '18%',
      width: 14,
      borderRadius: 999,
      background: color,
      boxShadow: `0 0 40px ${color}`,
      opacity: 0.9,
    }}
  />
);

const ThemePill = ({theme, index}) => {
  const color = palette[index % palette.length];
  return (
    <div
      style={{
        alignSelf: 'flex-start',
        background: 'rgba(10,15,26,0.66)',
        border: `2px solid ${color}`,
        borderRadius: 999,
        color: '#f8fafc',
        fontSize: 30,
        fontWeight: 700,
        letterSpacing: 1.2,
        padding: '12px 22px',
        textTransform: 'uppercase',
        backdropFilter: 'blur(16px)',
      }}
    >
      {theme}
    </div>
  );
};

const ClipCard = ({clip, theme, index, intro}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const color = palette[index % palette.length];
  const lift = spring({fps: 30, frame, config: {damping: 200}});
  const fadeOut = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const introOpacity = interpolate(frame, [0, 10, 28, 42], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const videoScale = interpolate(frame, [0, durationInFrames], [1.08, 1.0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const decorators = decoratorList(clip.decorators);

  return (
    <AbsoluteFill style={{backgroundColor: '#05070b', opacity: fadeOut}}>
      <OffthreadVideo
        src={staticFile(clip.path)}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          filter: 'blur(42px) saturate(0.8) brightness(0.5)',
          transform: 'scale(1.16)',
          opacity: 0.7,
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
      {clip.audio_path ? <Audio src={staticFile(clip.audio_path)} /> : null}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(180deg, rgba(3,7,18,0.16) 0%, rgba(3,7,18,0.05) 30%, rgba(3,7,18,0.65) 72%, rgba(2,6,23,0.92) 100%)',
        }}
      />
      <AbsoluteFill style={{padding: '80px 54px 64px 54px', display: 'flex', flexDirection: 'column'}}>
        <AccentBar color={color} />
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          <ThemePill theme={theme} index={index} />
          <div
            style={{
              color: '#cbd5e1',
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: 1.4,
              textTransform: 'uppercase',
            }}
          >
            Take {index + 1}
          </div>
        </div>

        {intro ? (
          <div
            style={{
              marginTop: 26,
              maxWidth: '82%',
              alignSelf: 'flex-start',
              background: 'rgba(8,12,22,0.66)',
              borderRadius: 28,
              padding: '20px 24px',
              border: `1px solid ${color}`,
              boxShadow: '0 18px 55px rgba(0,0,0,0.26)',
              opacity: introOpacity,
            }}
          >
            <div style={{color: '#f8fafc', fontSize: 46, fontWeight: 800, lineHeight: 1.05}}>{intro}</div>
          </div>
        ) : null}

        <div style={{flex: 1}} />

        <div
          style={{
            transform: `translateY(${Math.round((1 - lift) * 42)}px)`,
            opacity: lift,
          }}
        >
          <div
            style={{
              background: 'rgba(8,12,22,0.72)',
              borderRadius: 34,
              padding: '28px 30px',
              boxShadow: '0 24px 80px rgba(0,0,0,0.35)',
              border: '1px solid rgba(255,255,255,0.08)',
              maxWidth: '94%',
            }}
          >
            <div
              style={{
                color: '#f8fafc',
                fontSize: 56,
                lineHeight: 1.02,
                fontWeight: 900,
                marginBottom: 16,
                textWrap: 'balance',
              }}
            >
              {clip.quote}
            </div>
            <div
              style={{
                color: '#bfdbfe',
                fontSize: 28,
                lineHeight: 1.2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: 1.1,
              }}
            >
              {clip.context}
            </div>
            {decorators.length ? (
              <div style={{display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 18}}>
                {decorators.map((decorator, i) => (
                  <div
                    key={decorator + i}
                    style={{
                      background: i === 0 ? color : 'rgba(148,163,184,0.18)',
                      color: i === 0 ? '#111827' : '#e2e8f0',
                      borderRadius: 999,
                      padding: '8px 14px',
                      fontSize: 22,
                      fontWeight: 800,
                      textTransform: 'uppercase',
                      letterSpacing: 0.8,
                    }}
                  >
                    {decorator}
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          <div
            style={{
              marginTop: 18,
              color: '#e2e8f0',
              fontSize: 24,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: 1.1,
            }}
          >
            {clip.feed_title}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const OutroCard = ({theme, outro}) => {
  const frame = useCurrentFrame();
  const enter = spring({fps: 30, frame, config: {damping: 160}});
  return (
    <AbsoluteFill
      style={{
        background:
          'radial-gradient(circle at 70% 10%, rgba(56,189,248,0.22), transparent 30%), linear-gradient(180deg, #020617 0%, #0f172a 100%)',
        padding: '100px 68px',
        justifyContent: 'space-between',
      }}
    >
      <div
        style={{
          alignSelf: 'flex-start',
          background: 'rgba(15,23,42,0.72)',
          border: '2px solid rgba(56,189,248,0.45)',
          color: '#f8fafc',
          borderRadius: 999,
          padding: '12px 22px',
          fontSize: 30,
          fontWeight: 800,
          letterSpacing: 1.2,
          textTransform: 'uppercase',
        }}
      >
        {theme}
      </div>
      <div
        style={{
          transform: `translateY(${Math.round((1 - enter) * 48)}px)`,
          opacity: enter,
        }}
      >
        <div style={{color: '#f8fafc', fontSize: 86, lineHeight: 0.98, fontWeight: 900, textWrap: 'balance'}}>
          {outro}
        </div>
        <div style={{marginTop: 28, color: '#7dd3fc', fontSize: 30, fontWeight: 700}}>
          prays.be
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const SermonShortComposition = ({manifest}) => {
  const clips = manifest?.clips ?? [];
  return (
    <AbsoluteFill style={{backgroundColor: '#020617'}}>
      <Series>
        {clips.map((clip, index) => (
          <Series.Sequence
            key={clip.path + index}
            durationInFrames={frameCount(clip.duration_sec, fpsOrDefault(manifest))}
          >
            <ClipCard
              clip={clip}
              theme={String(manifest?.theme || 'sermon short')}
              index={index}
              intro={index === 0 ? String(manifest?.intro || '') : ''}
            />
          </Series.Sequence>
        ))}
        <Series.Sequence durationInFrames={endCardFrames(manifest)}>
          <OutroCard
            theme={String(manifest?.theme || 'sermon short')}
            outro={String(manifest?.outro || 'Full sermons for the longer version.')}
          />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
