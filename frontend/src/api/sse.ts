import { useEffect, useRef, useState } from "react";

export interface SseEvent {
  type: string;
  payload: Record<string, unknown>;
}

export function parseSseBlock(block: string): SseEvent | null {
  if (block.startsWith(":")) return null;
  let type = "message";
  const dataLines: string[] = [];
  block.split("\n").forEach((line) => {
    if (line.startsWith("event:")) {
      type = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  });
  if (dataLines.length === 0) return null;
  try {
    const payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    return { type, payload };
  } catch {
    return null;
  }
}

export function useEventStream(enabled: boolean, onEvent: (event: SseEvent) => void) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return undefined;
    const source = new EventSource("/api/events");

    const dispatch = (raw: string) => {
      const parsed = parseSseBlock(raw);
      if (parsed) handlerRef.current(parsed);
    };

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event: MessageEvent<string>) => {
      dispatch(`event: message\ndata: ${event.data}`);
    };

    return () => {
      source.close();
      setConnected(false);
    };
  }, [enabled]);

  return { connected };
}
