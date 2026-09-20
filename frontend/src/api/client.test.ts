import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, setUnauthorizedHandler } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
  setUnauthorizedHandler(null);
});

describe("apiFetch", () => {
  it("returns parsed json on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    await expect(apiFetch<{ ok: boolean }>("/api/health")).resolves.toEqual({ ok: true });
  });

  it("throws ApiError with server detail on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "invalid token" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const error = await apiFetch("/api/gallery").catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).message).toBe("invalid token");
  });

  it("invokes the unauthorized handler on 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
    );
    await apiFetch("/api/gallery").catch(() => undefined);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("serializes body and sets json content type for post", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/api/auth/login", { method: "POST", body: { token: "x" } });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["content-type"]).toBe(
      "application/json",
    );
    expect(init.body).toBe(JSON.stringify({ token: "x" }));
    expect(init.credentials).toBe("same-origin");
  });
});
