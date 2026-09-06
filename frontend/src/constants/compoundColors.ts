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

