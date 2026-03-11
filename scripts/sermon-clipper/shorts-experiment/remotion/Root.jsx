import React from 'react';
import {Composition} from 'remotion';
import {SermonShortComposition, calculateShortMetadata} from './SermonShortComposition';

const defaultManifest = {
  theme: 'sermon short',
  intro: '',
  outro: '',
  width: 1080,
  height: 1920,
  fps: 30,
  clips: [],
};

export const RemotionRoot = () => {
  return (
    <Composition
      id="SermonShort"
      component={SermonShortComposition}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={300}
      defaultProps={{manifest: defaultManifest}}
      calculateMetadata={calculateShortMetadata}
    />
  );
};
