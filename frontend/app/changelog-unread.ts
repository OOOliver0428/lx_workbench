export const CHANGELOG_SEEN_EVENT = "changelog:seen";

export interface ChangelogLastSeen {
  id: string;
  created_at: string;
}

export function changelogLastSeenKey(userId: string) {
  return `changelog.lastSeen:${userId}`;
}

export function readLastSeen(userId: string): ChangelogLastSeen | null {
  if (!userId) return null;
  try {
    const raw = window.localStorage.getItem(changelogLastSeenKey(userId));
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (
      value &&
      typeof value === "object" &&
      typeof (value as { id?: unknown }).id === "string" &&
      typeof (value as { created_at?: unknown }).created_at === "string"
    ) {
      const record = value as ChangelogLastSeen;
      return { id: record.id, created_at: record.created_at };
    }
    return null;
  } catch {
    return null;
  }
}

export function writeLastSeen(
  userId: string,
  entry: { id: string; created_at: string },
) {
  if (!userId || !entry) return;
  try {
    window.localStorage.setItem(
      changelogLastSeenKey(userId),
      JSON.stringify({ id: entry.id, created_at: entry.created_at }),
    );
  } catch { /* Storage is optional. */ }
}

export function isChangelogUnread(
  latest: { id: string; created_at: string } | null,
  lastSeen: ChangelogLastSeen | null,
): boolean {
  if (!latest) return false;
  if (!lastSeen) return true;
  if (latest.id === lastSeen.id) return false;
  const latestTime = new Date(latest.created_at).getTime();
  const seenTime = new Date(lastSeen.created_at).getTime();
  if (Number.isNaN(latestTime) || Number.isNaN(seenTime)) return false;
  return latestTime > seenTime;
}
