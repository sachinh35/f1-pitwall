import { describe, expect, it } from "vitest";
import { flagClass, resolveFlagDisplay } from "./trackStatus";

describe("flagClass", () => {
  it('classifies status "1" as green (all clear)', () => {
    expect(flagClass("1")).toBe("status-green");
  });

  it.each(["2", "6", "7"])("classifies status %s as yellow", (status) => {
    expect(flagClass(status)).toBe("status-yellow");
  });

  it.each(["4", "5"])("classifies status %s as red", (status) => {
    expect(flagClass(status)).toBe("status-red");
  });

  it("classifies an unrecognized status as unknown", () => {
    expect(flagClass("99")).toBe("status-unknown");
  });

  it("classifies a missing status as unknown", () => {
    expect(flagClass(undefined)).toBe("status-unknown");
  });
});

describe("resolveFlagDisplay", () => {
  it(
    "overrides TrackStatus with a Race Suspended message when SessionStatus is Aborted - " +
      "regression test for the real live scenario where TrackStatus cycled back to Yellow " +
      "(marshals clearing sectors) minutes before SessionStatus actually left Aborted",
    () => {
      const result = resolveFlagDisplay({ Status: "2", Message: "Yellow" }, { Status: "Aborted" });
      expect(result).toEqual({ text: "Race Suspended", className: "status-red" });
    }
  );

  it("falls back to the real TrackStatus message when SessionStatus is not Aborted", () => {
    const result = resolveFlagDisplay({ Status: "2", Message: "Yellow" }, { Status: "Started" });
    expect(result).toEqual({ text: "Yellow", className: "status-yellow" });
  });

  it("falls back to TrackStatus when sessionStatus is not provided", () => {
    const result = resolveFlagDisplay({ Status: "1", Message: "AllClear" });
    expect(result).toEqual({ text: "AllClear", className: "status-green" });
  });

  it("shows Unknown when neither TrackStatus nor an Aborted SessionStatus is available", () => {
    const result = resolveFlagDisplay({}, { Status: "Inactive" });
    expect(result).toEqual({ text: "Unknown", className: "status-unknown" });
  });
});
