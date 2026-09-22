import assert from "node:assert/strict";
import test from "node:test";
import {
  CHANGELOG_SEEN_EVENT,
  changelogLastSeenKey,
  isChangelogUnread,
  readLastSeen,
  writeLastSeen,
} from "../app/changelog-unread.ts";

function stubStorage(initial = new Map()) {
  const values = initial;
  globalThis.window = {
    localStorage: {
      getItem: (key) => (values.has(key) ? values.get(key) : null),
      setItem: (key, value) => values.set(key, String(value)),
    },
  };
  return values;
}

function teardown() {
  delete globalThis.window;
}

test("no latest entry means nothing is unread", () => {
  assert.equal(isChangelogUnread(null, null), false);
  assert.equal(
    isChangelogUnread(null, { id: "a", created_at: "2026-09-20T02:00:00Z" }),
    false,
  );
});

test("a latest entry without any last-seen record is unread", () => {
  assert.equal(
    isChangelogUnread({ id: "a", created_at: "2026-09-20T02:00:00Z" }, null),
    true,
  );
});

test("seeing the current latest entry clears the unread state", () => {
  const latest = { id: "a", created_at: "2026-09-20T02:00:00Z" };
  assert.equal(
    isChangelogUnread(latest, { id: "a", created_at: "2026-09-20T02:00:00Z" }),
    false,
  );
  // Editing the same entry bumps timestamps but must not re-trigger unread.
  assert.equal(
    isChangelogUnread(latest, { id: "a", created_at: "2026-09-19T02:00:00Z" }),
    false,
  );
});

test("a newer entry created after the last-seen one is unread", () => {
  assert.equal(
    isChangelogUnread(
      { id: "b", created_at: "2026-09-21T02:00:00Z" },
      { id: "a", created_at: "2026-09-20T02:00:00Z" },
    ),
    true,
  );
});

test("an older entry resurfacing after deletion is not unread", () => {
  assert.equal(
    isChangelogUnread(
      { id: "a", created_at: "2026-09-20T02:00:00Z" },
      { id: "b", created_at: "2026-09-21T02:00:00Z" },
    ),
    false,
  );
  assert.equal(
    isChangelogUnread(
      { id: "b", created_at: "2026-09-21T02:00:00Z" },
      { id: "a", created_at: "2026-09-21T02:00:00Z" },
    ),
    false,
  );
});

test("unparseable timestamps never trigger unread", () => {
  assert.equal(
    isChangelogUnread(
      { id: "b", created_at: "not-a-date" },
      { id: "a", created_at: "2026-09-20T02:00:00Z" },
    ),
    false,
  );
  assert.equal(
    isChangelogUnread(
      { id: "b", created_at: "2026-09-21T02:00:00Z" },
      { id: "a", created_at: "garbage" },
    ),
    false,
  );
});

test("last-seen records are stored per user under a versioned key", () => {
  const values = stubStorage();
  try {
    writeLastSeen("alice", { id: "a", created_at: "2026-09-20T02:00:00Z" });
    writeLastSeen("bob", { id: "b", created_at: "2026-09-21T03:00:00Z" });
    assert.deepEqual(readLastSeen("alice"), {
      id: "a",
      created_at: "2026-09-20T02:00:00Z",
    });
    assert.deepEqual(readLastSeen("bob"), {
      id: "b",
      created_at: "2026-09-21T03:00:00Z",
    });
    assert.deepEqual([...values.keys()].sort(), [
      "changelog.lastSeen:alice",
      "changelog.lastSeen:bob",
    ]);
    assert.equal(changelogLastSeenKey("alice"), "changelog.lastSeen:alice");
    assert.equal(CHANGELOG_SEEN_EVENT, "changelog:seen");
  } finally {
    teardown();
  }
});

test("corrupt or malformed last-seen payloads read as absent", () => {
  const values = stubStorage();
  try {
    values.set("changelog.lastSeen:alice", "bad json");
    assert.equal(readLastSeen("alice"), null);
    values.set(
      "changelog.lastSeen:alice",
      JSON.stringify({ id: "a" }),
    );
    assert.equal(readLastSeen("alice"), null);
    values.set(
      "changelog.lastSeen:alice",
      JSON.stringify({ id: 7, created_at: "2026-09-20T02:00:00Z" }),
    );
    assert.equal(readLastSeen("alice"), null);
    values.set("changelog.lastSeen:alice", JSON.stringify(null));
    assert.equal(readLastSeen("alice"), null);
  } finally {
    teardown();
  }
});

test("unavailable storage degrades to no record and never throws", () => {
  globalThis.window = {
    localStorage: {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    },
  };
  try {
    assert.equal(readLastSeen("alice"), null);
    writeLastSeen("alice", { id: "a", created_at: "2026-09-20T02:00:00Z" });
  } finally {
    teardown();
  }
  assert.equal(readLastSeen("alice"), null);
  writeLastSeen("alice", { id: "a", created_at: "2026-09-20T02:00:00Z" });
});
