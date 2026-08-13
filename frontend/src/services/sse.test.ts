import { beforeEach, describe, expect, it, vi } from "vitest";
import { connectRaceModeStream } from "./sse";

class MockEventSource {
  static instances: MockEventSource[] = [];
  static CLOSED = 2;

  url: string;
  closed = false;
  readyState = 0;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(cb);
  }

  close() {
    this.closed = true;
    this.readyState = MockEventSource.CLOSED;
  }

  dispatch(type: string, data: unknown) {
    const event = { data: JSON.stringify(data) } as MessageEvent;
    (this.listeners[type] ?? []).forEach((cb) => cb(event));
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  // @ts-expect-error - test stub, not the real browser EventSource
  global.EventSource = MockEventSource;
});

describe("connectRaceModeStream", () => {
  it("connects to the expected URL for the given stream id", () => {
    connectRaceModeStream("stream-1", {});
    expect(MockEventSource.instances[0].url).toBe("http://localhost:8000/live/stream-1/events");
  });

  it("registers a listener per handler key and dispatches parsed JSON to it", () => {
    const onWeather = vi.fn();
    connectRaceModeStream("stream-1", { WeatherData: onWeather });

    const source = MockEventSource.instances[0];
    source.dispatch("WeatherData", { weather: { AirTemp: "25.1" } });

    expect(onWeather).toHaveBeenCalledWith({ weather: { AirTemp: "25.1" } });
  });

  it("does not register a listener for handler keys that are undefined", () => {
    connectRaceModeStream("stream-1", { WeatherData: undefined });
    const source = MockEventSource.instances[0];
    expect(source.listeners["WeatherData"]).toBeUndefined();
  });

  it("logs and swallows malformed JSON instead of throwing", () => {
    const onWeather = vi.fn();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    connectRaceModeStream("stream-1", { WeatherData: onWeather });
    const source = MockEventSource.instances[0];

    expect(() => source.listeners["WeatherData"][0]({ data: "not-json" } as MessageEvent)).not.toThrow();

    expect(onWeather).not.toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("logs a warning on error only once the connection's readyState is CLOSED", () => {
    const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => {});
    connectRaceModeStream("stream-1", {});
    const source = MockEventSource.instances[0];

    source.readyState = 1; // CONNECTING/OPEN - EventSource will retry on its own
    source.onerror?.();
    expect(consoleWarn).not.toHaveBeenCalled();

    source.readyState = MockEventSource.CLOSED;
    source.onerror?.();
    expect(consoleWarn).toHaveBeenCalledWith(expect.stringContaining("stream-1"));

    consoleWarn.mockRestore();
  });

  it("returns a cleanup function that closes the underlying connection", () => {
    const disconnect = connectRaceModeStream("stream-1", {});
    const source = MockEventSource.instances[0];

    disconnect();

    expect(source.closed).toBe(true);
  });
});
