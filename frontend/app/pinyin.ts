import { match } from "pinyin-pro";

/**
 * 支持拼音的文本匹配：中文按全拼/首字母匹配，英文按子串匹配。
 * 查询串为空时恒为 true。
 */
export function pinyinMatch(text: string | null | undefined, query: string) {
  const keyword = query.trim();
  if (!keyword) return true;
  const source = (text ?? "").toLocaleLowerCase();
  const target = keyword.toLocaleLowerCase();
  if (source.includes(target)) return true;
  return match(source, target) !== null;
}

/** 任一字段命中即视为匹配。 */
export function pinyinMatchAny(
  fields: Array<string | null | undefined>,
  query: string,
) {
  return fields.some((field) => pinyinMatch(field, query));
}
