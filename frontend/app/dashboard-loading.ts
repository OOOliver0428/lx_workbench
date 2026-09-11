export function createLatestRequest() {
  let version = 0;
  return {
    cancel() { version += 1; },
    async run<T>(request: () => Promise<T>): Promise<T | undefined> {
      const current = ++version;
      try {
        const result = await request();
        return current === version ? result : undefined;
      } catch (error) {
        if (current === version) throw error;
        return undefined;
      }
    },
  };
}

export function readManagementScope(userId: string) {
  try {
    const raw = window.localStorage.getItem(`workMgmt.scope:${userId}`);
    const value = raw ? JSON.parse(raw) : null;
    return {
      scopeType: typeof value?.scopeType === "string" ? value.scopeType : "",
      departmentId: typeof value?.departmentId === "string" ? value.departmentId : "",
    };
  } catch {
    return { scopeType: "", departmentId: "" };
  }
}

export function saveManagementScope(userId: string, scopeType: string, departmentId: string) {
  try {
    window.localStorage.setItem(`workMgmt.scope:${userId}`, JSON.stringify({ scopeType, departmentId }));
  } catch { /* Storage is optional. */ }
}
