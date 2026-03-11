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

const STYLE_PACKS = [
  {
    name: 'ember',
    colors: ['#f97316', '#fb7185', '#facc15'],
    panel: 'rgba(15, 23, 42, 0.76)',
    panelBorder: 'rgba(251, 113, 133, 0.26)',
    topGradient: 'linear-gradient(180deg, rgba(12,16,30,0.20) 0%, rgba(12,16,30,0.06) 22%, rgba(12,16,30,0.66) 66%, rgba(12,16,30,0.96) 100%)',
    accentGlow: 'radial-gradient(circle at 14% 12%, rgba(249,115,22,0.34) 0%, transparent 32%)',
    quoteFont: '"Georgia", "Palatino Linotype", serif',
    labelFont: '"Trebuchet MS", "Segoe UI", sans-serif',
  },
  {
    name: 'harbor',
    colors: ['#38bdf8', '#14b8a6', '#a3e635'],
    panel: 'rgba(3, 15, 24, 0.76)',
    panelBorder: 'rgba(56, 189, 248, 0.22)',
    topGradient: 'linear-gradient(180deg, rgba(3,15,24,0.24) 0%, rgba(3,15,24,0.10) 20%, rgba(3,15,24,0.64) 68%, rgba(3,15,24,0.95) 100%)',
    accentGlow: 'radial-gradient(circle at 82% 14%, rgba(20,184,166,0.28) 0%, transparent 30%)',
    quoteFont: '"Book Antiqua", "Georgia", serif',
    labelFont: '"Franklin Gothic Medium", "Trebuchet MS", sans-serif',
  },
  {
    name: 'linen',
    colors: ['#f59e0b', '#eab308', '#f87171'],
    panel: 'rgba(28, 18, 8, 0.72)',
    panelBorder: 'rgba(245, 158, 11, 0.24)',
    topGradient: 'linear-gradient(180deg, rgba(24,18,10,0.12) 0%, rgba(24,18,10,0.04) 16%, rgba(24,18,10,0.58) 62%, rgba(24,18,10,0.93) 100%)',
    accentGlow: 'radial-gradient(circle at 16% 80%, rgba(234,179,8,0.24) 0%, transparent 28%)',
    quoteFont: '"Cambria", "Georgia", serif',
    labelFont: '"Gill Sans", "Trebuchet MS", sans-serif',
  },
];

const fpsOrDefault = (manifest) => Math.max(12, Number(manifest?.fps) || 30);

const frameCount = (seconds, fps) => Math.max(1, Math.round(Number(seconds || 0) * fps));

const decoratorList = (decorators) =>
  String(decorators || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .slice(0, 3);

const endCardFrames = (manifest) => Math.max(36, Math.round(fpsOrDefault(manifest) * 1.35));

const hashTheme = (theme) =>
  Array.from(String(theme || 'sermon short')).reduce((sum, char) => sum + char.charCodeAt(0), 0);

const stylePackForTheme = (manifest) => {
  const styles = STYLE_PACKS;
  const explicit = String(manifest?.style || '').trim().toLowerCase();
  const explicitPack = styles.find((item) => item.name === explicit);
  if (explicitPack) {
    return explicitPack;
  }
  return styles[hashTheme(manifest?.theme) % styles.length];
};

export const calculateShortMetadata = ({props}) => {
  const manifest = props?.manifest ?? {};
  const fps = fpsOrDefault(manifest);
  const clips = manifest.clips || [];
  const clipFrames = clips.reduce((sum, clip) => sum + frameCount(clip.duration_sec, fps), 0);
  return {
    fps,
    width: Math.max(360, Number(manifest.width) || 1080),
    height: Math.max(640, Number(manifest.height) || 1920),
    durationInFrames: Math.max(clipFrames + endCardFrames(manifest), fps * 4),
  };
};

const ThemePill = ({theme, color, pack}) => (
  <div
    style={{
      alignSelf: 'flex-start',
      background: 'rgba(8,12,22,0.72)',
      border: `2px solid ${color}`,
      borderRadius: 999,
      color: '#f8fafc',
      fontFamily: pack.labelFont,
      fontSize: 26,
      fontWeight: 800,
      letterSpacing: 1.6,
      padding: '12px 20px',
      textTransform: 'uppercase',
      boxShadow: `0 0 40px ${color}24`,
      backdropFilter: 'blur(16px)',
    }}
  >
    {theme}
  </div>
);

const ProgressRail = ({index, total, color}) => (
  <div style={{display: 'flex', gap: 10, marginTop: 18}}>
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

const CornerFrame = ({color}) => (
  <>
    <div
      style={{
        position: 'absolute',
        top: 42,
        right: 34,
        width: 180,
        height: 180,
        borderTop: `4px solid ${color}`,
        borderRight: `4px solid ${color}`,
        borderRadius: 28,
        opacity: 0.34,
      }}
    />
    <div
      style={{
        position: 'absolute',
        bottom: 42,
        left: 34,
        width: 180,
        height: 180,
        borderBottom: `4px solid ${color}`,
        borderLeft: `4px solid ${color}`,
        borderRadius: 28,
        opacity: 0.34,
      }}
    />
  </>
);

const ClipCard = ({clip, theme, index, totalClips, intro, pack}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const color = pack.colors[index % pack.colors.length];
  const lift = spring({fps, frame, config: {damping: 180}});
  const introOpacity = interpolate(frame, [0, 10, 28, 44], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fadeOut = interpolate(frame, [durationInFrames - 7, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const videoScale = interpolate(frame, [0, durationInFrames], [1.045, 1.0], {
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
          filter: 'blur(48px) saturate(0.88) brightness(0.42)',
          transform: 'scale(1.16)',
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
      <div style={{position: 'absolute', inset: 0, background: pack.topGradient}} />
      <div style={{position: 'absolute', inset: 0, background: pack.accentGlow}} />
      <CornerFrame color={color} />

      <AbsoluteFill style={{padding: '58px 54px 78px 54px', display: 'flex', flexDirection: 'column'}}>
        <ThemePill theme={theme} color={color} pack={pack} />
        <ProgressRail index={index} total={totalClips} color={color} />

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: 16,
            color: '#dbeafe',
            fontFamily: pack.labelFont,
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
              marginTop: 26,
              maxWidth: '82%',
              alignSelf: 'flex-start',
              background: 'rgba(8,12,22,0.72)',
              borderRadius: 30,
              padding: '18px 24px',
              border: `2px solid ${color}`,
              boxShadow: '0 22px 60px rgba(0,0,0,0.28)',
              opacity: introOpacity,
            }}
          >
            <div
              style={{
                color: '#f8fafc',
                fontFamily: pack.labelFont,
                fontSize: 46,
                fontWeight: 800,
                lineHeight: 1.02,
              }}
            >
              {intro}
            </div>
          </div>
        ) : null}

        <div style={{flex: 1}} />

        <div
          style={{
            transform: `translateY(${Math.round((1 - lift) * 34)}px)`,
            opacity: lift,
          }}
        >
          <div
            style={{
              background: pack.panel,
              borderRadius: 36,
              padding: '28px 30px',
              border: `1px solid ${pack.panelBorder}`,
              boxShadow: '0 22px 80px rgba(0,0,0,0.42)',
              backdropFilter: 'blur(20px)',
            }}
          >
            {clip.context ? (
              <div
                style={{
                  color: color,
                  fontFamily: pack.labelFont,
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
                fontFamily: pack.quoteFont,
                fontSize: 56,
                lineHeight: 1.01,
                fontWeight: 700,
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
                    color: '#0f172a',
                    borderRadius: 999,
                    padding: '8px 14px',
                    fontFamily: pack.labelFont,
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
                    background: 'rgba(226,232,240,0.12)',
                    color: '#e2e8f0',
                    borderRadius: 999,
                    padding: '8px 14px',
                    fontFamily: pack.labelFont,
                    fontSize: 20,
                    fontWeight: 800,
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
                  fontFamily: pack.labelFont,
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

const OutroCard = ({theme, outro, pack}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({fps, frame, config: {damping: 170}});
  const accent = pack.colors[1];
  return (
    <AbsoluteFill
      style={{
        background: `${pack.accentGlow}, linear-gradient(180deg, #020617 0%, #0f172a 100%)`,
        padding: '100px 68px',
        justifyContent: 'space-between',
      }}
    >
      <ThemePill theme={theme} color={accent} pack={pack} />
      <div
        style={{
          transform: `translateY(${Math.round((1 - enter) * 48)}px)`,
          opacity: enter,
        }}
      >
        <div
          style={{
            color: '#f8fafc',
            fontFamily: pack.quoteFont,
            fontSize: 84,
            lineHeight: 0.98,
            fontWeight: 700,
            textWrap: 'balance',
          }}
        >
          {outro}
        </div>
        <div
          style={{
            marginTop: 26,
            color: accent,
            fontFamily: pack.labelFont,
            fontSize: 28,
            fontWeight: 700,
            letterSpacing: 1.1,
            textTransform: 'uppercase',
          }}
        >
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
  const pack = stylePackForTheme(manifest);
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
              pack={pack}
            />
          </Series.Sequence>
        ))}
        <Series.Sequence durationInFrames={endCardFrames(manifest)}>
          <OutroCard theme={theme} outro={outro} pack={pack} />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
