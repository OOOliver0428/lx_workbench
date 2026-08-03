export type LocalDateSource = Pick<Date, "getTime" | "getTimezoneOffset">;

export function localDateInputValue(date: LocalDateSource = new Date()) {
  const localTime = date.getTime() - date.getTimezoneOffset() * 60_000;
  return new Date(localTime).toISOString().slice(0, 10);
}
