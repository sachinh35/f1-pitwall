import '@testing-library/jest-dom/vitest';

// jsdom has no layout engine, so every element reports a 0x0 rect by default. Recharts'
// ResponsiveContainer (used by LapComparisonChart) reads this to size its SVG and renders
// nothing at 0x0 - fix the default to a plausible viewport size so chart internals actually
// mount in tests, instead of every chart test silently rendering an empty container.
if (!('ResizeObserver' in globalThis)) {
  class MockResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  // @ts-expect-error - minimal stub, not the full ResizeObserver interface
  globalThis.ResizeObserver = MockResizeObserver;
}

Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
  configurable: true,
  value: () => ({
    width: 800,
    height: 500,
    top: 0,
    left: 0,
    bottom: 500,
    right: 800,
    x: 0,
    y: 0,
    toJSON() {},
  }),
});

// Recharts' own mouse-position math (getMouseInfo) divides the mocked getBoundingClientRect
// width by element.offsetWidth to compute a "scale" factor - jsdom has no layout engine and
// reports offsetWidth/offsetHeight as 0 by default, which turns that division into Infinity and
// makes every mouse coordinate resolve as out-of-bounds. Match it to the mocked rect above.
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 800 });
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 500 });

Object.defineProperty(HTMLCanvasElement.prototype, 'clientWidth', { configurable: true, value: 800 });
Object.defineProperty(HTMLCanvasElement.prototype, 'clientHeight', { configurable: true, value: 400 });

// jsdom doesn't implement the canvas 2D drawing API at all - TrackMap and CompareWidget both
// draw every frame via requestAnimationFrame, and silently no-op their whole draw loop when
// getContext("2d") returns null. This stub is just enough surface area (every method those two
// components call) for that draw code to actually execute under test - no drawing math changes.
class MockCanvasRenderingContext2D {
  strokeStyle = '';
  fillStyle = '';
  lineWidth = 1;
  lineJoin = 'miter';
  lineCap = 'butt';
  globalAlpha = 1;
  font = '';
  textAlign = 'start' as CanvasTextAlign;
  setTransform() {}
  clearRect() {}
  fillRect() {}
  beginPath() {}
  moveTo() {}
  lineTo() {}
  arc() {}
  stroke() {}
  fill() {}
  fillText() {}
  save() {}
  restore() {}
  setLineDash() {}
}

Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
  configurable: true,
  value: () => new MockCanvasRenderingContext2D(),
});
