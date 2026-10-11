import React from 'react';
import {Img, staticFile, useCurrentFrame} from 'remotion';

// Исходные кадры извлекаются FFmpeg без изменения fps, в lossless PNG.
// Общая секвенция задаёт trim для изображения и подписей одновременно.
export const FrameVideo: React.FC<{style: React.CSSProperties}> = ({style}) => {
  const frame=Math.max(0,Math.floor(useCurrentFrame()));
  return <Img src={staticFile(`source-frames/frame-${String(frame+1).padStart(6,'0')}.png`)} style={style} />;
};
