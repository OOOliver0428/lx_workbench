export interface WeeklyPreviewVersion {
  id: string;
  content: string;
  guidance: string;
  createdAt: string;
  kind: "generated" | "edited" | "saved";
  generation?: number;
}

export interface WeeklyPreviewState {
  content: string;
  versions: WeeklyPreviewVersion[];
  activeVersionId: string;
}

type VersionStamp = { id: string; createdAt: string };

export type WeeklyPreviewAction =
  | { type: "load"; content: string }
  | { type: "edit" | "saved"; content: string }
  | ({ type: "generated"; content: string; guidance: string } & VersionStamp)
  | ({ type: "restore"; versionId: string } & VersionStamp);

export function createWeeklyPreviewState(content = ""): WeeklyPreviewState {
  return {
    content,
    versions: content ? [{
      id: "saved-initial", content, guidance: "", createdAt: "", kind: "saved",
    }] : [],
    activeVersionId: content ? "saved-initial" : "",
  };
}

// Generation and navigation never discard a working copy. AI versions stay immutable.
function checkpoint(state: WeeklyPreviewState, stamp: VersionStamp) {
  if (!state.content.trim() || state.versions.some((item) => item.content === state.content)) {
    return state.versions;
  }
  const active = state.versions.find((item) => item.id === state.activeVersionId);
  const snapshot: WeeklyPreviewVersion = {
    id: `${stamp.id}-edit`,
    content: state.content,
    guidance: active?.guidance ?? "",
    createdAt: stamp.createdAt,
    kind: "edited",
  };
  return [snapshot, ...state.versions];
}

export function weeklyPreviewReducer(
  state: WeeklyPreviewState,
  action: WeeklyPreviewAction,
): WeeklyPreviewState {
  switch (action.type) {
    case "load":
      return createWeeklyPreviewState(action.content);
    case "edit":
    case "saved":
      return { ...state, content: action.content };
    case "generated": {
      const version: WeeklyPreviewVersion = {
        id: action.id,
        content: action.content,
        guidance: action.guidance,
        createdAt: action.createdAt,
        kind: "generated",
        generation: state.versions.filter((item) => item.kind === "generated").length + 1,
      };
      return {
        content: version.content,
        versions: [version, ...checkpoint(state, action)],
        activeVersionId: version.id,
      };
    }
    case "restore": {
      const version = state.versions.find((item) => item.id === action.versionId);
      if (!version) return state;
      return {
        content: version.content,
        versions: checkpoint(state, action),
        activeVersionId: version.id,
      };
    }
  }
}
