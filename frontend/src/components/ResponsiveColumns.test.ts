import { describe, expect, it } from "vitest";

import { columnsForWidth } from "./ResponsiveColumns";

describe("columnsForWidth", () => {
  it("scales the column count with the viewport width", () => {
    expect(columnsForWidth(480)).toBe(2);
    expect(columnsForWidth(768)).toBe(3);
    expect(columnsForWidth(1280)).toBe(4);
    expect(columnsForWidth(1920)).toBe(6);
  });
});
