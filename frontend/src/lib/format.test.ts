import { describe, expect, it } from "vitest";

import { formatBytes, formatDate, formatIndex } from "./format";

describe("formatBytes", () => {
  it("formats bytes with binary units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("formatDate", () => {
  it("formats ISO dates as YYYY-MM-DD", () => {
    expect(formatDate("2026-03-16T11:42:49+09:00")).toBe("2026-03-16");
  });

  it("returns a dash for empty values", () => {
    expect(formatDate(null)).toBe("—");
  });
});

describe("formatIndex", () => {
  it("pads the display index", () => {
    expect(formatIndex(7)).toBe("#0007");
    expect(formatIndex(1234)).toBe("#1234");
  });
});
