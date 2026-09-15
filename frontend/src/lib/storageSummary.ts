// Header summary for the experiments page. The list unions runs from local disk and the offload
// drive, so a single combined total would never drop when you move a run to the drive — defeating
// the point of offload. Split the figures by location so freeing local space is visible.

export interface Located {
  library?: "local" | "drive";
  size_bytes?: number;
}

export interface Breakdown {
  total: number;
  localCount: number;
  driveCount: number;
  localBytes: number;
  driveBytes: number;
}

export function storageBreakdown(items: readonly Located[]): Breakdown {
  const b: Breakdown = { total: 0, localCount: 0, driveCount: 0, localBytes: 0, driveBytes: 0 };
  for (const it of items) {
    b.total += 1;
    const bytes = it.size_bytes ?? 0;
    if (it.library === "drive") {
      b.driveCount += 1;
      b.driveBytes += bytes;
    } else {
      b.localCount += 1; // missing library => local
      b.localBytes += bytes;
    }
  }
  return b;
}

const gb = (n: number) => `${(n / 1e9).toFixed(2)} GB`;

export function summaryLabel(b: Breakdown, driveConnected: boolean): string {
  const parts = [`${b.total} experiment${b.total === 1 ? "" : "s"}`];
  if (b.localBytes > 0) parts.push(`${gb(b.localBytes)} local`);
  if (driveConnected && b.driveBytes > 0) parts.push(`${gb(b.driveBytes)} on drive`);
  return parts.join(" · ");
}
