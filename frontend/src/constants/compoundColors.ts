export type Compound = 'SOFT' | 'MEDIUM' | 'HARD' | 'INTERMEDIATE' | 'INTERS' | 'INTER' | 'WET' | 'WETS' | string | null | undefined;

const normalize = (compound: Compound): string => {
  const c = (compound || '').toUpperCase();
  if (c === 'INTERS' || c === 'INTER') return 'INTERMEDIATE';
  if (c === 'WETS') return 'WET';
  return c;
};

// Icon imports (Vite will bundle these)
// Using default export URLs for images
import redIconUrl from '../tire-compound-icons/red.svg';
import yellowIconUrl from '../tire-compound-icons/yellow.svg';
import whiteIconUrl from '../tire-compound-icons/white.svg';
import greenIconUrl from '../tire-compound-icons/green.png';
import blueIconUrl from '../tire-compound-icons/blue.svg';

export const getCompoundColor = (compound: Compound): string => {
  switch (normalize(compound)) {
    case 'SOFT':
      return '#EA3C53'; // red
    case 'MEDIUM':
      return '#FFCC00'; // yellow
    case 'HARD':
      return '#E6E6E6'; // near-white
    case 'INTERMEDIATE':
      return '#00A651'; // green
    case 'WET':
      return '#0077FF'; // blue
    default:
      return 'rgba(255,255,255,0.4)';
  }
};

export const getCompoundInitial = (compound: Compound): string => {
  switch (normalize(compound)) {
    case 'SOFT':
      return 'S';
    case 'MEDIUM':
      return 'M';
    case 'HARD':
      return 'H';
    case 'INTERMEDIATE':
      return 'I';
    case 'WET':
      return 'W';
    default:
      return '-';
  }
};

export const getCompoundBadgeStyle = (compound: Compound): { bg: string; fg: string; border: string } => {
  const c = normalize(compound);
  if (c === 'SOFT') {
    return { bg: '#EA3C53', fg: '#FFFFFF', border: '#EA3C53' };
  }
  if (c === 'MEDIUM') {
    return { bg: '#FFCC00', fg: '#000000', border: '#FFCC00' };
  }
  if (c === 'HARD') {
    return { bg: '#FFFFFF', fg: '#000000', border: '#000000' };
  }
  if (c === 'INTERMEDIATE') {
    return { bg: '#00A651', fg: '#FFFFFF', border: '#00A651' };
  }
  if (c === 'WET') {
    return { bg: '#0077FF', fg: '#FFFFFF', border: '#0077FF' };
  }
  return { bg: 'transparent', fg: 'rgba(255,255,255,0.7)', border: 'rgba(255,255,255,0.4)' };
};

export const getCompoundIconUrl = (compound: Compound): string | null => {
  switch (normalize(compound)) {
    case 'SOFT':
      return redIconUrl;
    case 'MEDIUM':
      return yellowIconUrl;
    case 'HARD':
      return whiteIconUrl;
    case 'INTERMEDIATE':
      return greenIconUrl;
    case 'WET':
      return blueIconUrl;
    default:
      return null;
  }
};

