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
    texture: 'repeating-linear-gradient(135deg, rgba(251,113,133,0.09) 0 2px, transparent 2px 18px)',
    quoteFont: '"Georgia", "Palatino Linotype", serif',
    labelFont: '"Trebuchet MS", "Segoe UI", sans-serif',
    frameStyle: 'corners',
    railStyle: 'segments',
    pillStyle: 'capsule',
    chipStyle: 'solid',
    panelRadius: 36,
    textPrimary: '#f8fafc',
    textMuted: '#cbd5e1',
    labelText: '#dbeafe',
  },
  {
    name: 'harbor',
    colors: ['#38bdf8', '#14b8a6', '#a3e635'],
    panel: 'rgba(3, 15, 24, 0.76)',
    panelBorder: 'rgba(56, 189, 248, 0.22)',
    topGradient: 'linear-gradient(180deg, rgba(3,15,24,0.24) 0%, rgba(3,15,24,0.10) 20%, rgba(3,15,24,0.64) 68%, rgba(3,15,24,0.95) 100%)',
    accentGlow: 'radial-gradient(circle at 82% 14%, rgba(20,184,166,0.28) 0%, transparent 30%)',
    texture: 'repeating-linear-gradient(0deg, rgba(56,189,248,0.08) 0 1px, transparent 1px 22px)',
    quoteFont: '"Book Antiqua", "Georgia", serif',
    labelFont: '"Franklin Gothic Medium", "Trebuchet MS", sans-serif',
    frameStyle: 'rails',
    railStyle: 'ticks',
    pillStyle: 'ghost',
    chipStyle: 'outline',
    panelRadius: 28,
    textPrimary: '#eff6ff',
    textMuted: '#cbd5e1',
    labelText: '#dbeafe',
  },
  {
    name: 'linen',
    colors: ['#f59e0b', '#eab308', '#f87171'],
    panel: 'rgba(28, 18, 8, 0.72)',
    panelBorder: 'rgba(245, 158, 11, 0.24)',
    topGradient: 'linear-gradient(180deg, rgba(24,18,10,0.12) 0%, rgba(24,18,10,0.04) 16%, rgba(24,18,10,0.58) 62%, rgba(24,18,10,0.93) 100%)',
    accentGlow: 'radial-gradient(circle at 16% 80%, rgba(234,179,8,0.24) 0%, transparent 28%)',
    texture: 'repeating-linear-gradient(90deg, rgba(245,158,11,0.07) 0 2px, transparent 2px 26px)',
    quoteFont: '"Cambria", "Georgia", serif',
    labelFont: '"Gill Sans", "Trebuchet MS", sans-serif',
    frameStyle: 'corners',
    railStyle: 'dots',
    pillStyle: 'slab',
    chipStyle: 'glass',
    panelRadius: 42,
    textPrimary: '#fff7ed',
    textMuted: '#fed7aa',
    labelText: '#fde68a',
  },
  {
    name: 'nocturne',
    colors: ['#7dd3fc', '#818cf8', '#c084fc'],
    panel: 'rgba(6, 10, 24, 0.78)',
    panelBorder: 'rgba(129, 140, 248, 0.22)',
    topGradient: 'linear-gradient(180deg, rgba(6,10,24,0.18) 0%, rgba(6,10,24,0.08) 18%, rgba(6,10,24,0.62) 64%, rgba(6,10,24,0.96) 100%)',
    accentGlow: 'radial-gradient(circle at 86% 12%, rgba(129,140,248,0.26) 0%, transparent 34%)',
    texture: 'repeating-linear-gradient(135deg, rgba(125,211,252,0.06) 0 1px, transparent 1px 16px)',
    quoteFont: '"Iowan Old Style", "Georgia", serif',
    labelFont: '"Century Gothic", "Trebuchet MS", sans-serif',
    frameStyle: 'focus',
    railStyle: 'dots',
    pillStyle: 'ghost',
    chipStyle: 'outline',
    panelRadius: 30,
    textPrimary: '#eef2ff',
    textMuted: '#c7d2fe',
    labelText: '#dbeafe',
  },
  {
    name: 'moss',
    colors: ['#34d399', '#22c55e', '#facc15'],
    panel: 'rgba(7, 20, 16, 0.78)',
    panelBorder: 'rgba(52, 211, 153, 0.22)',
    topGradient: 'linear-gradient(180deg, rgba(7,20,16,0.18) 0%, rgba(7,20,16,0.06) 20%, rgba(7,20,16,0.60) 68%, rgba(7,20,16,0.95) 100%)',
    accentGlow: 'radial-gradient(circle at 18% 20%, rgba(34,197,94,0.22) 0%, transparent 34%)',
    texture: 'repeating-linear-gradient(45deg, rgba(52,211,153,0.05) 0 2px, transparent 2px 18px)',
    quoteFont: '"Baskerville Old Face", "Georgia", serif',
    labelFont: '"Candara", "Trebuchet MS", sans-serif',
    frameStyle: 'rails',
    railStyle: 'segments',
    pillStyle: 'capsule',
    chipStyle: 'glass',
    panelRadius: 32,
    textPrimary: '#ecfdf5',
    textMuted: '#bbf7d0',
    labelText: '#d1fae5',
  },
  {
    name: 'oxide',
    colors: ['#fb7185', '#f97316', '#fdba74'],
    panel: 'rgba(26, 10, 10, 0.78)',
    panelBorder: 'rgba(251, 113, 133, 0.24)',
    topGradient: 'linear-gradient(180deg, rgba(26,10,10,0.20) 0%, rgba(26,10,10,0.07) 18%, rgba(26,10,10,0.62) 66%, rgba(26,10,10,0.95) 100%)',
    accentGlow: 'radial-gradient(circle at 20% 82%, rgba(249,115,22,0.22) 0%, transparent 30%)',
    texture: 'repeating-linear-gradient(90deg, rgba(251,113,133,0.05) 0 1px, transparent 1px 24px)',
    quoteFont: '"Constantia", "Georgia", serif',
    labelFont: '"Verdana", "Trebuchet MS", sans-serif',
    frameStyle: 'focus',
    railStyle: 'ticks',
    pillStyle: 'slab',
    chipStyle: 'solid',
    panelRadius: 26,
    textPrimary: '#fff1f2',
    textMuted: '#fecdd3',
    labelText: '#ffe4e6',
  },
  {
    name: 'iris',
    colors: ['#a78bfa', '#60a5fa', '#22d3ee'],
    panel: 'rgba(11, 12, 28, 0.80)',
    panelBorder: 'rgba(167, 139, 250, 0.22)',
    topGradient: 'linear-gradient(180deg, rgba(11,12,28,0.18) 0%, rgba(11,12,28,0.06) 20%, rgba(11,12,28,0.62) 68%, rgba(11,12,28,0.96) 100%)',
    accentGlow: 'radial-gradient(circle at 50% 0%, rgba(96,165,250,0.20) 0%, transparent 36%)',
    texture: 'repeating-linear-gradient(135deg, rgba(167,139,250,0.06) 0 2px, transparent 2px 20px)',
    quoteFont: '"Perpetua", "Georgia", serif',
    labelFont: '"Tahoma", "Trebuchet MS", sans-serif',
    frameStyle: 'corners',
    railStyle: 'dots',
    pillStyle: 'ghost',
    chipStyle: 'glass',
    panelRadius: 40,
    textPrimary: '#f5f3ff',
    textMuted: '#ddd6fe',
    labelText: '#e0e7ff',
  },
  {
    name: 'cobalt',
    colors: ['#22d3ee', '#38bdf8', '#facc15'],
    panel: 'rgba(3, 11, 20, 0.80)',
    panelBorder: 'rgba(34, 211, 238, 0.20)',
    topGradient: 'linear-gradient(180deg, rgba(3,11,20,0.18) 0%, rgba(3,11,20,0.05) 18%, rgba(3,11,20,0.61) 66%, rgba(3,11,20,0.96) 100%)',
    accentGlow: 'radial-gradient(circle at 80% 76%, rgba(34,211,238,0.20) 0%, transparent 32%)',
    texture: 'repeating-linear-gradient(0deg, rgba(34,211,238,0.06) 0 1px, transparent 1px 18px)',
    quoteFont: '"Palatino Linotype", "Georgia", serif',
    labelFont: '"Lucida Sans Unicode", "Trebuchet MS", sans-serif',
    frameStyle: 'rails',
    railStyle: 'segments',
    pillStyle: 'capsule',
    chipStyle: 'outline',
    panelRadius: 24,
    textPrimary: '#ecfeff',
    textMuted: '#bae6fd',
    labelText: '#cffafe',
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
  const seed = `${manifest?.theme || ''}:${manifest?.structure || manifest?.metadata?.structure || ''}:${manifest?.opening_kicker || ''}`;
  return styles[hashTheme(seed) % styles.length];
};

const baseScaleForFrame = (width, height) => Math.max(0.5, Math.min(width / 1080, height / 1920));

const px = (value, scale, min = 0) => Math.max(min, Math.round(value * scale));

const pillRadius = (pack, scale) => {
  if (pack.pillStyle === 'slab') {
    return px(18, scale, 10);
  }
  if (pack.pillStyle === 'ghost') {
    return px(22, scale, 12);
  }
  return 999;
};

const panelRadius = (pack, scale) => px(pack.panelRadius || 36, scale, 18);

const chipStyleForPack = (pack, color, scale) => {
  if (pack.chipStyle === 'outline') {
    return {
      background: 'transparent',
      border: `${Math.max(1, px(1.5, scale))}px solid ${color}99`,
      color: pack.labelText || '#e2e8f0',
    };
  }
  if (pack.chipStyle === 'glass') {
    return {
      background: 'rgba(255,255,255,0.08)',
      border: `${Math.max(1, px(1, scale))}px solid rgba(255,255,255,0.12)`,
      color: pack.labelText || '#e2e8f0',
      backdropFilter: 'blur(12px)',
    };
  }
  return {
    background: color,
    color: '#08111f',
  };
};

const BackdropTexture = ({pack}) =>
  pack.texture ? (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        backgroundImage: pack.texture,
        opacity: 0.4,
        mixBlendMode: 'screen',
        pointerEvents: 'none',
      }}
    />
  ) : null;

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
      background: pack.pillStyle === 'ghost' ? 'rgba(8,12,22,0.44)' : 'rgba(8,12,22,0.72)',
      border: `${Math.max(1, px(2, scale))}px solid ${color}`,
      borderRadius: pillRadius(pack, scale),
      color: pack.textPrimary || '#f8fafc',
      fontFamily: pack.labelFont,
      fontSize: px(26, scale, 14),
      fontWeight: 800,
      letterSpacing: px(1.6, scale),
      padding: `${px(12, scale, 6)}px ${px(20, scale, 10)}px`,
      textTransform: 'uppercase',
      boxShadow: `0 0 40px ${color}24`,
      backdropFilter: pack.pillStyle === 'ghost' ? 'blur(18px)' : 'blur(12px)',
    }}
  >
    {theme}
  </div>
);

const ProgressRail = ({index, total, color, scale, pack}) => {
  if (pack.railStyle === 'dots') {
    return (
      <div style={{display: 'flex', gap: px(12, scale, 6), marginTop: px(18, scale, 10), alignItems: 'center'}}>
        {Array.from({length: total}).map((_, itemIndex) => (
          <div
            key={itemIndex}
            style={{
              width: itemIndex === index ? px(22, scale, 10) : px(10, scale, 5),
              height: px(10, scale, 5),
              borderRadius: 999,
              background: itemIndex <= index ? color : 'rgba(226,232,240,0.18)',
              opacity: itemIndex === index ? 1 : 0.72,
            }}
          />
        ))}
      </div>
    );
  }
  if (pack.railStyle === 'ticks') {
    return (
      <div style={{display: 'flex', gap: px(12, scale, 6), marginTop: px(18, scale, 10), alignItems: 'flex-end'}}>
        {Array.from({length: total}).map((_, itemIndex) => (
          <div
            key={itemIndex}
            style={{
              width: 0,
              height: itemIndex === index ? px(24, scale, 12) : px(14, scale, 8),
              borderLeft: `${Math.max(1, px(3, scale))}px solid ${itemIndex <= index ? color : 'rgba(226,232,240,0.18)'}`,
              opacity: itemIndex === index ? 1 : 0.72,
            }}
          />
        ))}
      </div>
    );
  }
  return (
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
};

const CornerFrame = ({color, scale, pack}) => {
  if (pack.frameStyle === 'rails') {
    return (
      <>
        <div
          style={{
            position: 'absolute',
            top: px(44, scale, 20),
            bottom: px(44, scale, 20),
            left: px(28, scale, 14),
            width: Math.max(1, px(3, scale)),
            background: `linear-gradient(180deg, transparent 0%, ${color} 18%, ${color} 82%, transparent 100%)`,
            opacity: 0.28,
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: px(44, scale, 20),
            bottom: px(44, scale, 20),
            right: px(28, scale, 14),
            width: Math.max(1, px(3, scale)),
            background: `linear-gradient(180deg, transparent 0%, ${color} 18%, ${color} 82%, transparent 100%)`,
            opacity: 0.28,
          }}
        />
      </>
    );
  }
  if (pack.frameStyle === 'focus') {
    return (
      <>
        <div
          style={{
            position: 'absolute',
            top: px(60, scale, 24),
            left: '50%',
            width: px(320, scale, 140),
            height: Math.max(1, px(2, scale)),
            transform: 'translateX(-50%)',
            background: `linear-gradient(90deg, transparent 0%, ${color} 20%, ${color} 80%, transparent 100%)`,
            opacity: 0.32,
          }}
        />
        <div
          style={{
            position: 'absolute',
            bottom: px(60, scale, 24),
            left: '50%',
            width: px(320, scale, 140),
            height: Math.max(1, px(2, scale)),
            transform: 'translateX(-50%)',
            background: `linear-gradient(90deg, transparent 0%, ${color} 20%, ${color} 80%, transparent 100%)`,
            opacity: 0.32,
          }}
        />
      </>
    );
  }
  return (
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
};

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
      <BackdropTexture pack={pack} />
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
            color: pack.textPrimary || '#f8fafc',
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
              color: pack.labelText || '#dbeafe',
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
          color: pack.textMuted || 'rgba(226,232,240,0.78)',
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
      <BackdropTexture pack={pack} />
      <CornerFrame color={color} scale={scale} pack={pack} />

      <AbsoluteFill
        style={{
          padding: `${px(58, scale, 28)}px ${px(54, scale, 26)}px ${px(78, scale, 38)}px ${px(54, scale, 26)}px`,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <ThemePill theme={theme} color={color} pack={pack} scale={scale} />
        <ProgressRail index={index} total={totalClips} color={color} scale={scale} pack={pack} />

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: px(16, scale, 8),
            color: pack.labelText || '#dbeafe',
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
              borderRadius: panelRadius(pack, scale),
              padding: `${px(28, scale, 14)}px ${px(30, scale, 15)}px`,
              border: `${Math.max(1, px(1, scale))}px solid ${pack.panelBorder}`,
              boxShadow: pack.frameStyle === 'focus' ? '0 24px 90px rgba(0,0,0,0.48)' : '0 22px 80px rgba(0,0,0,0.42)',
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
                color: pack.textPrimary || '#f8fafc',
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
                    ...chipStyleForPack(pack, color, scale),
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
                    ...chipStyleForPack(pack, color, scale),
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
                  color: pack.textMuted || '#cbd5e1',
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
      <BackdropTexture pack={pack} />
      <ThemePill theme={theme} color={accent} pack={pack} scale={scale} />
      <div
        style={{
          transform: `translateY(${Math.round((1 - enter) * px(48, scale, 20))}px)`,
          opacity: enter,
        }}
      >
        <div
          style={{
            color: pack.textPrimary || '#f8fafc',
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
              color: pack.labelText || '#dbeafe',
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
