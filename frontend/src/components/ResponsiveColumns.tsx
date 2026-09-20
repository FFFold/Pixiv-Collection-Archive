import { useEffect, useState } from "react";

export function columnsForWidth(width: number): number {
  if (width < 640) return 2;
  if (width < 1024) return 3;
  if (width < 1536) return 4;
  return 6;
}

export function useResponsiveColumns(): number {
  const [columns, setColumns] = useState<number>(() =>
    typeof window === "undefined" ? 4 : columnsForWidth(window.innerWidth),
  );

  useEffect(() => {
    const handleResize = () => setColumns(columnsForWidth(window.innerWidth));
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return columns;
}
