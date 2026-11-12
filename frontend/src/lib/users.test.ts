import { test } from "node:test";
import assert from "node:assert/strict";
import type { CollectionsDoc, UsersDoc } from "./api.ts";
import { currentUser, slugFor, userChipLabel, userMenuCollections } from "./users.ts";

// hand-made shapes mirroring GET /api/users (backend users.py public_doc) and GET /api/collections
function users(over: Partial<UsersDoc> = {}): UsersDoc {
  return {
    current: "mattmccoy",
    users: [
      { id: "mattmccoy", name: "Matt McCoy", collections: ["mattmccoy", "rf-sintering"], last_collection: "mattmccoy", profile_name: "RF heating" },
      { id: "ana", name: "Ana", collections: ["ana"], last_collection: "ana", profile_name: "default" },
    ],
    ...over,
  };
}
function cols(names: string[], selected: string | null = "mattmccoy"): CollectionsDoc {
  return {
    selected,
    collections: names.map((name) => ({ name, local: true, drive: false, offline: false })),
    unsorted: { local: 0, drive: 0 }, unexpected: [], drive_connected: false, drive_registered: false,
  };
}

test("slugFor mirrors backend users.slug_for", () => {
  assert.equal(slugFor("Matt McCoy"), "mattmccoy");
  assert.equal(slugFor("  Ana Ruiz-Lopez "), "anaruiz-lopez");
  assert.equal(slugFor("José"), "jose");
  assert.equal(slugFor("!!!"), "");
  assert.equal(slugFor("x".repeat(50)).length, 40);
});

test("currentUser finds the current entry or null", () => {
  assert.equal(currentUser(users())?.name, "Matt McCoy");
  assert.equal(currentUser(users({ current: null })), null);
  assert.equal(currentUser(null), null);
});

test("chip label: the person's name, a prompt when nobody is set, the error when unreachable", () => {
  assert.equal(userChipLabel(users(), null), "Matt McCoy");
  assert.equal(userChipLabel(users({ current: null }), null), "who's using this?");
  assert.equal(userChipLabel(null, "boom"), "users unavailable: boom");
  assert.equal(userChipLabel(null, null), "loading…");
});

test("menu collections: the user's own first (those on disk), then every other collection", () => {
  const u = currentUser(users())!;
  const m = userMenuCollections(u, cols(["ana", "mattmccoy", "rf-sintering", "zeta"]));
  assert.deepEqual(m.mine, ["mattmccoy", "rf-sintering"]);
  assert.deepEqual(m.others, ["ana", "zeta"]);
});

test("menu collections keep a listed collection the doc doesn't show yet (drive unplugged)", () => {
  const u = currentUser(users())!;
  const m = userMenuCollections(u, cols(["mattmccoy"]));
  assert.deepEqual(m.mine, ["mattmccoy", "rf-sintering"]);
  assert.deepEqual(m.others, []);
});

test("collectionRows: every collection with who uses it, where it lives, and the selection", async () => {
  const { collectionRows } = await import("./users.ts");
  const c = cols(["ana", "mattmccoy", "rf-sintering", "zeta"]);
  c.collections[1] = { name: "mattmccoy", local: true, drive: true, offline: false };
  c.collections[2] = { name: "rf-sintering", local: false, drive: true, offline: true };
  const rows = collectionRows(c, users());
  assert.deepEqual(rows.map((r) => r.name), ["ana", "mattmccoy", "rf-sintering", "zeta"]);
  assert.deepEqual(rows[1], { name: "mattmccoy", users: ["Matt McCoy"], where: "Mac + SSD", selected: true });
  assert.deepEqual(rows[0].users, ["Ana"]);
  assert.equal(rows[2].where, "SSD (unplugged)");
  assert.deepEqual(rows[2].users, ["Matt McCoy"]);
  assert.equal(rows[3].where, "Mac");
  assert.deepEqual(rows[3].users, []);
  assert.deepEqual(collectionRows(c, null)[1].users, []);
});

test("initials: first letters of the first and last word", async () => {
  const { initials } = await import("./users.ts");
  assert.equal(initials("Matt McCoy"), "MM");
  assert.equal(initials("ana"), "A");
  assert.equal(initials("  Ana  Ruiz Lopez "), "AL");
  assert.equal(initials(""), "?");
});

test("squareCrop: the centred square of any photo, scaled to the target size", async () => {
  const { squareCrop } = await import("./users.ts");
  assert.deepEqual(squareCrop(4000, 3000, 160), { sx: 500, sy: 0, side: 3000, out: 160 });
  assert.deepEqual(squareCrop(600, 900, 160), { sx: 0, sy: 150, side: 600, out: 160 });
  assert.deepEqual(squareCrop(64, 48, 160), { sx: 8, sy: 0, side: 48, out: 48 }); // never upscale
});

test("startup picker: shown unless this browser opted out; the choice persists", async () => {
  const { pickerAtStartup, setPickerAtStartup } = await import("./users.ts");
  const mem = new Map<string, string>();
  const store = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => { mem.set(k, v); }, removeItem: (k: string) => { mem.delete(k); } };
  assert.equal(pickerAtStartup(store), true);
  setPickerAtStartup(store, false);
  assert.equal(pickerAtStartup(store), false);
  setPickerAtStartup(store, true);
  assert.equal(pickerAtStartup(store), true);
  assert.equal(pickerAtStartup(null), true);
});
