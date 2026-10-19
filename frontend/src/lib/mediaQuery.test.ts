import { test } from "node:test";
import assert from "node:assert/strict";
import { mediaPreviewQuery } from "./mediaQuery.ts";

test("the media-export preview query keeps today's parameters", () => {
  assert.equal(mediaPreviewQuery(3, {}), "?index=3&scale=1&with_rois=true&frame_stats=false&timestamp=true&colorbar=true");
  assert.equal(mediaPreviewQuery(0, { palette: "iron", title: "a b", plot_series: ["1:mean"], start: 2, stop: 9 }),
    "?index=0&scale=1&with_rois=true&frame_stats=false&timestamp=true&colorbar=true&palette=iron&title=a%20b&plot_series=1%3Amean&start=2&stop=9");
});

test("the preview asks for the RF-banding filter only when it is on", () => {
  assert.match(mediaPreviewQuery(3, { rf_notch: true }), /&rf_notch=true$/);
  assert.doesNotMatch(mediaPreviewQuery(3, { rf_notch: false }), /rf_notch/);
});
