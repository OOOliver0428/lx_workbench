type RandomUuidSource = {
  randomUUID?: () => string;
};

let fallbackSequence = 0;

export function createClientMessageId(
  source: RandomUuidSource | undefined = globalThis.crypto,
) {
  if (typeof source?.randomUUID === "function") {
    return source.randomUUID();
  }

  fallbackSequence += 1;
  return `message-${Date.now().toString(36)}-${fallbackSequence.toString(36)}`;
}
