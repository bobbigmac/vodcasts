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

const startCardFrames = (manifest) => {
  const intro = String(manifest?.intro || '').trim();
  const context = String(manifest?.opening_context || manifest?.metadata?.opening_context || '').trim();
  if (!intro && !context) {
    return 0;
  }
  return Math.max(34, Math.round(fpsOrDefault(manifest) * 1.45));
};

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

const baseScaleForFrame = (width, height) => Math.max(0.5, Math.min(width / 1080, height / 1920));

const px = (value, scale, min = 0) => Math.max(min, Math.round(value * scale));

export const calculateShortMetadata = ({props}) => {
  const manifest = props?.manifest ?? {};
  const fps = fpsOrDefault(manifest);
  const clips = manifest.clips || [];
  const clipFrames = clips.reduce((sum, clip) => sum + frameCount(clip.duration_sec, fps), 0);
  return {
    fps,
    width: Math.max(360, Number(manifest.width) || 1080),
    height: Math.max(640, Number(manifest.height) || 1920),
    durationInFrames: Math.max(startCardFrames(manifest) + clipFrames + endCardFrames(manifest), fps * 4),
  };
};

const ThemePill = ({theme, color, pack, scale}) => (
  <div
    style={{
      alignSelf: 'flex-start',
      background: 'rgba(8,12,22,0.72)',
      border: `${Math.max(1, px(2, scale))}px solid ${color}`,
      borderRadius: 999,
      color: '#f8fafc',
      fontFamily: pack.labelFont,
      fontSize: px(26, scale, 14),
      fontWeight: 800,
      letterSpacing: px(1.6, scale),
      padding: `${px(12, scale, 6)}px ${px(20, scale, 10)}px`,
      textTransform: 'uppercase',
      boxShadow: `0 0 40px ${color}24`,
      backdropFilter: 'blur(16px)',
    }}
  >
    {theme}
  </div>
);

const ProgressRail = ({index, total, color, scale}) => (
  <div style={{display: 'flex', gap: px(10, scale, 5), marginTop: px(18, scale, 10)}}>
    {Array.from({length: total}).map((_, itemIndex) => (
      <div
        key={itemIndex}
        style={{
          height: px(8, scale, 4),
          flex: 1,
          borderRadius: 999,
          background: itemIndex <= index ? color : 'rgba(226,232,240,0.16)',
          opacity: itemIndex === index ? 1 : 0.72,
        }}
      />
    ))}
  </div>
);

const CornerFrame = ({color, scale}) => (
  <>
    <div
      style={{
        position: 'absolute',
        top: px(42, scale, 20),
        right: px(34, scale, 16),
        width: px(180, scale, 90),
        height: px(180, scale, 90),
        borderTop: `${Math.max(1, px(4, scale))}px solid ${color}`,
        borderRight: `${Math.max(1, px(4, scale))}px solid ${color}`,
        borderRadius: px(28, scale, 14),
        opacity: 0.34,
      }}
    />
    <div
      style={{
        position: 'absolute',
        bottom: px(42, scale, 20),
        left: px(34, scale, 16),
        width: px(180, scale, 90),
        height: px(180, scale, 90),
        borderBottom: `${Math.max(1, px(4, scale))}px solid ${color}`,
        borderLeft: `${Math.max(1, px(4, scale))}px solid ${color}`,
        borderRadius: px(28, scale, 14),
        opacity: 0.34,
      }}
    />
  </>
);

const IntroCard = ({theme, intro, openingKicker, openingContext, structure, pack}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const scale = baseScaleForFrame(width, height);
  const enter = spring({fps, frame, config: {damping: 180}});
  const accent = pack.colors[0];
  const structureLabel = String(structure || '').replace(/-/g, ' ');

  return (
    <AbsoluteFill
      style={{
        background: `${pack.accentGlow}, linear-gradient(180deg, #020617 0%, #0f172a 100%)`,
        padding: `${px(94, scale, 40)}px ${px(66, scale, 28)}px`,
        justifyContent: 'space-between',
      }}
    >
      <div style={{display: 'flex', flexDirection: 'column', gap: px(16, scale, 8)}}>
        <ThemePill theme={theme} color={accent} pack={pack} scale={scale} />
        {openingKicker ? (
          <div
            style={{
              color: accent,
              fontFamily: pack.labelFont,
              fontSize: px(28, scale, 14),
              fontWeight: 900,
              letterSpacing: px(1.4, scale),
              textTransform: 'uppercase',
            }}
          >
            {openingKicker}
          </div>
        ) : null}
      </div>
      <div
        style={{
          transform: `translateY(${Math.round((1 - enter) * px(42, scale, 18))}px)`,
          opacity: enter,
        }}
      >
        <div
          style={{
            color: '#f8fafc',
            fontFamily: pack.quoteFont,
            fontSize: px(86, scale, 38),
            lineHeight: 0.96,
            fontWeight: 700,
            textWrap: 'balance',
          }}
        >
          {intro}
        </div>
        {openingContext ? (
          <div
            style={{
              marginTop: px(22, scale, 10),
              maxWidth: '88%',
              color: '#dbeafe',
              fontFamily: pack.labelFont,
              fontSize: px(30, scale, 15),
              lineHeight: 1.18,
              fontWeight: 600,
            }}
          >
            {openingContext}
          </div>
        ) : null}
      </div>
      <div
        style={{
          color: 'rgba(226,232,240,0.78)',
          fontFamily: pack.labelFont,
          fontSize: px(20, scale, 11),
          fontWeight: 800,
          letterSpacing: px(1.2, scale),
          textTransform: 'uppercase',
        }}
      >
        {structureLabel || 'curated reflection'}
      </div>
    </AbsoluteFill>
  );
};

const ClipCard = ({clip, theme, index, totalClips, pack}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps, width, height} = useVideoConfig();
  const scale = baseScaleForFrame(width, height);
  const color = pack.colors[index % pack.colors.length];
  const lift = spring({fps, frame, config: {damping: 180}});
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
      <CornerFrame color={color} scale={scale} />

      <AbsoluteFill
        style={{
          padding: `${px(58, scale, 28)}px ${px(54, scale, 26)}px ${px(78, scale, 38)}px ${px(54, scale, 26)}px`,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <ThemePill theme={theme} color={color} pack={pack} scale={scale} />
        <ProgressRail index={index} total={totalClips} color={color} scale={scale} />

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: px(16, scale, 8),
            color: '#dbeafe',
            fontFamily: pack.labelFont,
            fontSize: px(22, scale, 12),
            fontWeight: 700,
            letterSpacing: px(1.1, scale),
            textTransform: 'uppercase',
            gap: px(20, scale, 10),
          }}
        >
          <div>{clip.feed_title}</div>
          <div>
            {index + 1}/{totalClips}
          </div>
        </div>

        <div style={{flex: 1}} />

        <div
          style={{
            transform: `translateY(${Math.round((1 - lift) * px(34, scale, 16))}px)`,
            opacity: lift,
          }}
        >
          <div
            style={{
              background: pack.panel,
              borderRadius: px(36, scale, 18),
              padding: `${px(28, scale, 14)}px ${px(30, scale, 15)}px`,
              border: `${Math.max(1, px(1, scale))}px solid ${pack.panelBorder}`,
              boxShadow: '0 22px 80px rgba(0,0,0,0.42)',
              backdropFilter: 'blur(20px)',
            }}
          >
            {clip.context ? (
              <div
                style={{
                  color: color,
                  fontFamily: pack.labelFont,
                  fontSize: px(24, scale, 13),
                  fontWeight: 900,
                  letterSpacing: px(1.2, scale),
                  marginBottom: px(12, scale, 6),
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
                fontSize: px(56, scale, 26),
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
                gap: px(14, scale, 7),
                marginTop: px(18, scale, 10),
                alignItems: 'center',
              }}
            >
              {clip.speaker_label ? (
                <div
                  style={{
                    background: color,
                    color: '#0f172a',
                    borderRadius: 999,
                    padding: `${px(8, scale, 4)}px ${px(14, scale, 8)}px`,
                    fontFamily: pack.labelFont,
                    fontSize: px(20, scale, 11),
                    fontWeight: 900,
                    letterSpacing: px(0.7, scale),
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
                    padding: `${px(8, scale, 4)}px ${px(14, scale, 8)}px`,
                    fontFamily: pack.labelFont,
                    fontSize: px(20, scale, 11),
                    fontWeight: 800,
                    letterSpacing: px(0.7, scale),
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
                  marginTop: px(16, scale, 8),
                  color: '#cbd5e1',
                  fontFamily: pack.labelFont,
                  fontSize: px(22, scale, 12),
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

const OutroCard = ({theme, outro, closingLabel, reflectionPrompt, pack}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const scale = baseScaleForFrame(width, height);
  const enter = spring({fps, frame, config: {damping: 170}});
  const accent = pack.colors[1];
  return (
    <AbsoluteFill
      style={{
        background: `${pack.accentGlow}, linear-gradient(180deg, #020617 0%, #0f172a 100%)`,
        padding: `${px(100, scale, 42)}px ${px(68, scale, 28)}px`,
        justifyContent: 'space-between',
      }}
    >
      <ThemePill theme={theme} color={accent} pack={pack} scale={scale} />
      <div
        style={{
          transform: `translateY(${Math.round((1 - enter) * px(48, scale, 20))}px)`,
          opacity: enter,
        }}
      >
        <div
          style={{
            color: '#f8fafc',
            fontFamily: pack.quoteFont,
            fontSize: px(84, scale, 38),
            lineHeight: 0.98,
            fontWeight: 700,
            textWrap: 'balance',
          }}
        >
          {outro}
        </div>
        {reflectionPrompt ? (
          <div
            style={{
              marginTop: px(24, scale, 12),
              maxWidth: '88%',
              color: '#dbeafe',
              fontFamily: pack.labelFont,
              fontSize: px(28, scale, 14),
              lineHeight: 1.16,
              fontWeight: 600,
            }}
          >
            {reflectionPrompt}
          </div>
        ) : null}
        <div
          style={{
            marginTop: px(26, scale, 12),
            color: accent,
            fontFamily: pack.labelFont,
            fontSize: px(28, scale, 14),
            fontWeight: 700,
            letterSpacing: px(1.1, scale),
            textTransform: 'uppercase',
          }}
        >
          {closingLabel || 'prays.be'}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const SermonShortComposition = ({manifest}) => {
  const clips = manifest?.clips ?? [];
  const theme = String(manifest?.theme || 'sermon short');
  const outro = String(manifest?.outro || 'Full sermons hold the longer context.');
  const intro = String(manifest?.intro || '');
  const openingKicker = String(manifest?.opening_kicker || manifest?.metadata?.opening_kicker || '');
  const openingContext = String(manifest?.opening_context || manifest?.metadata?.opening_context || '');
  const closingLabel = String(manifest?.closing_label || manifest?.metadata?.closing_label || 'prays.be');
  const reflectionPrompt = String(manifest?.reflection_prompt || manifest?.metadata?.reflection_prompt || '');
  const structure = String(manifest?.structure || manifest?.metadata?.structure || '');
  const pack = stylePackForTheme(manifest);
  return (
    <AbsoluteFill style={{backgroundColor: '#020617'}}>
      <Series>
        {startCardFrames(manifest) > 0 ? (
          <Series.Sequence durationInFrames={startCardFrames(manifest)}>
            <IntroCard
              theme={theme}
              intro={intro}
              openingKicker={openingKicker}
              openingContext={openingContext}
              structure={structure}
              pack={pack}
            />
          </Series.Sequence>
        ) : null}
        {clips.map((clip, index) => (
          <Series.Sequence
            key={`${clip.path}-${index}`}
            durationInFrames={frameCount(clip.duration_sec, fpsOrDefault(manifest))}
          >
            <ClipCard clip={clip} theme={theme} index={index} totalClips={clips.length} pack={pack} />
          </Series.Sequence>
        ))}
        <Series.Sequence durationInFrames={endCardFrames(manifest)}>
          <OutroCard
            theme={theme}
            outro={outro}
            closingLabel={closingLabel}
            reflectionPrompt={reflectionPrompt}
            pack={pack}
          />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
