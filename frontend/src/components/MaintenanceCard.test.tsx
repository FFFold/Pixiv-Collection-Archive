import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import MaintenanceCard from "./MaintenanceCard";

afterEach(() => vi.restoreAllMocks());

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MaintenanceCard />
    </QueryClientProvider>,
  );
}

function mockFetch() {
  const mock = vi.fn().mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ id: "t1", kind: "maintenance", status: "running" }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("MaintenanceCard", () => {
  it("submits a refresh-previews task after confirmation", async () => {
    const fetchMock = mockFetch();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderCard();

    await userEvent.click(screen.getByRole("button", { name: "重抓封面（改原图比例）" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [input, init] = fetchMock.mock.calls.at(-1) ?? [];
    expect(String(input)).toContain("/api/maintenance/refresh-previews");
    expect(init?.method).toBe("POST");
  });

  it("does nothing when the confirmation is declined", async () => {
    const fetchMock = mockFetch();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderCard();

    await userEvent.click(screen.getByRole("button", { name: "重抓封面（改原图比例）" }));

    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("submits a full restart when the user asks for one", async () => {
    const fetchMock = mockFetch();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderCard();

    await userEvent.click(screen.getByRole("button", { name: "重新全量重抓封面" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls.at(-1) ?? [];
    expect(JSON.parse(String(init?.body))).toEqual({ restart: true });
  });
});
