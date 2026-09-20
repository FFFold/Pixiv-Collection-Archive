import { describe, expect, it } from "vitest";

import { parseSseBlock } from "./sse";

describe("parseSseBlock", () => {
  it("parses an event name and json payload", () => {
    const block = 'event: progress\ndata: {"task_id": "abc", "done": 1}';
    expect(parseSseBlock(block)).toEqual({
      type: "progress",
      payload: { task_id: "abc", done: 1 },
    });
  });

  it("handles multi-line data fields", () => {
    const block = 'event: task\ndata: {"a": 1,\ndata: "b": 2}';
    expect(parseSseBlock(block)?.payload).toEqual({ a: 1, b: 2 });
  });

  it("returns null for keepalive comments", () => {
    expect(parseSseBlock(": keepalive")).toBeNull();
  });

  it("returns null for malformed payloads", () => {
    expect(parseSseBlock("event: x\ndata: {oops")).toBeNull();
  });
});
