/** Options the media-export preview understands (a subset of the export's MediaOptions). */
export interface MediaPreviewOptions {
  with_rois?: boolean; frame_stats?: boolean; timestamp?: boolean; colorbar?: boolean;
  title?: string | null; plot_series?: string[]; overlay_rois?: number[]; visible_opacity?: number;
  palette?: string; start?: number; stop?: number;
  /** Colour the preview with the RF banding removed (numbers stay raw). */
  rf_notch?: boolean;
}

/** The query string of ``/export/media/preview`` for frame ``index``. */
export function mediaPreviewQuery(index: number, o: MediaPreviewOptions): string {
  return `?index=${index}&scale=1&with_rois=${o.with_rois !== false}&frame_stats=${!!o.frame_stats}&timestamp=${o.timestamp !== false}&colorbar=${o.colorbar !== false}`
    + (o.palette ? `&palette=${o.palette}` : "")
    + (o.title ? `&title=${encodeURIComponent(o.title)}` : "")
    + (o.plot_series ?? []).map((s) => `&plot_series=${encodeURIComponent(s)}`).join("")
    + (o.overlay_rois ?? []).map((r) => `&overlay_rois=${r}`).join("")
    + (o.visible_opacity ? `&visible_opacity=${o.visible_opacity}` : "")
    + (o.plot_series?.length ? `&start=${o.start ?? 0}&stop=${o.stop ?? 0}` : "")
    + (o.rf_notch ? "&rf_notch=true" : "");
}
