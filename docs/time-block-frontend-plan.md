# 时间块圈选录入 · 前端需求与开发规划

> 关联后端文档：`docs/time-block-backend-plan.md`
> Demo 已就绪：`/time-block-demo`（组件 `frontend/app/components/time-block-picker.tsx`）

## 1. 背景与目标

工作记录的「投入时长」目前是数字输入框（0.5h 步进），只能记录总耗时。
目标：改为**在时间轴上按住拖动圈选时间块**，一次录入同时得到：

- 合计耗时（沿用现有 `minutes` 字段与统计逻辑）；
- 具体工作区间（如 09:00–10:30、14:00–15:00），随记录持久化。

粒度：0.5h；范围：当天 00:00–24:00；**不支持跨天**（跨天拆成两条记录）。

## 2. 现状与改动范围

| 位置 | 现状 | 改动 |
| --- | --- | --- |
| `records-view.tsx` `QuickCreateModal`（约 955 行） | `<input name="hours" type="number" step="0.5">` | 替换为 `<TimeBlockPicker name="time">` |
| `records-view.tsx` `RecordEditModal`（约 588 行） | 同上，`defaultValue={record.minutes / 60}` | 替换为 `TimeBlockPicker`，用 `record.time_blocks` 回填 |
| `frontend/app/types.ts` `WorkRecord`（315 行起） | 无区间字段 | 新增 `time_blocks: TimeBlock[]` |
| `frontend/app/api.ts` | 提交载荷仅 `minutes` | 请求/响应类型补充 `time_blocks` |
| `frontend/app/globals.css` | Demo 样式已追加（`.tbp-*`） | 无需改动 |

组件与样式已在 Demo 中完成，迁移成本集中在两个弹窗的接线。

## 3. 组件契约（已实现，直接使用）

```tsx
<TimeBlockPicker
  name="time"            // 隐藏字段前缀
  defaultBlocks={blocks} // 编辑回填，[{start, end}]，分钟、30 的倍数
  onChange={(blocks, totalMinutes) => {}}  // 可选
/>
```

渲染隐藏字段，可被 `FormData` 直接采集：

- `time_hours`：合计小时数（如 `2.5`），**沿用现有 `minutes = Number(hours) * 60` 逻辑**；
- `time_blocks`：JSON 字符串，如 `[{"start":540,"end":630}]`（当天 00:00 起分钟数，`end` 不含）。

交互（Demo 已验证）：

- 空白处按住拖动：新建块（最小 0.5h，吸附半小时刻度）；
- 拖块体：平移；拖块左右边缘：改起止；松手后重叠/相邻块自动合并；
- 触屏长按约 260ms 激活，不与页面滚动冲突；
- 块标签单独删除，「清空」一键移除；未圈选时提交需拦截提示。

## 4. 数据流改动

### 4.1 快速记录（QuickCreateModal）

```ts
// 现状
minutes: Math.round(Number(form.get("hours")) * 60),
// 改为
minutes: Math.round(Number(form.get("time_hours")) * 60),
time_blocks: JSON.parse(String(form.get("time_blocks") ?? "[]")),
```

提交前校验：未圈选任何块（`time_hours` 为 0）时提示「请圈选工作时间块」。

### 4.2 编辑记录（RecordEditModal）

- 回填：`defaultBlocks={record.time_blocks}`；历史无区间的记录 `time_blocks` 为 `[]`，时间块为空、仅保留分钟数显示（见 4.4 降级）。
- 提交：`api.records.update` 载荷增加 `time_blocks`；语义为**整体替换**（后端约定）。

### 4.3 类型

```ts
// types.ts
export interface TimeBlock {
  start: number; // 当天 00:00 起分钟，含，30 的倍数
  end: number;   // 不含，30 的倍数
}
export interface WorkRecord {
  // …既有字段
  time_blocks: TimeBlock[];
}
```

### 4.4 降级与兼容

- 后端未返回 `time_blocks` 字段时按 `[]` 处理（`record.time_blocks ?? []`）；
- 编辑一条无区间的历史记录：时间块区域为空，用户圈选后保存即完成补录；不圈选直接保存时**不传 `time_blocks` 字段**（后端 `null` = 不改动），避免把老记录的区间误清为空。

## 5. 展示侧（二期，可选）

- `record-card` 的工时旁追加区间摘要：`2.5h · 09:00–10:30、14:00–15:00`；
- 按日分组头部可渲染当天时间覆盖迷你条（复用 `.tbp-track` 只读模式）。
- 建议二期做，一期保持卡片不变，控制改动面。

## 6. 边界与异常

| 场景 | 行为 |
| --- | --- |
| 未圈选直接提交 | 前端拦截并提示（`time_hours` 为 0） |
| 区间总长 > 24h | 不可能出现（轴上限即 24h）；块被钳制在当天内 |
| 跨天工作 | 不支持，引导用户按天拆分两条记录 |
| 快速拖动/抖动 | 吸附 30 分钟刻度，松手才提交合并 |
| 触屏误触 | 长按 260ms 激活；激活前移动超过 10px 视为滚动，取消本次拖动 |
| 窄屏 | 轨道 `min-width: 560px`，外层 `.tbp-scroll` 横向滚动 |

## 7. 联调依赖与上线顺序

**后端必须先上线**：`WorkRecordQuickCreate` 是 `extra="forbid"`，前端先发 `time_blocks` 会被 422 拒绝。

1. 后端上线（接受并持久化 `time_blocks`，旧前端不受影响）；
2. 前端上线（开始发送 `time_blocks`，并消费返回值做编辑回填）。

## 8. 验收标准

- [ ] 快速记录弹窗中圈选 2 段区间，提交后列表显示正确合计工时；刷新后编辑弹窗能回填 2 段区间；
- [ ] 块可平移、改长、删除、合并，合计始终等于各块之和；
- [ ] 无区间时提交被拦截并给出提示；
- [ ] 编辑历史记录（无区间）不圈选直接保存，区间保持为空而非报错；
- [ ] 移动端长按拖动可用，页面滚动不受影响；
- [ ] `npm run lint`、`npm test`（含 SSR 构建）通过。

## 9. 开发步骤建议

1. `types.ts` / `api.ts`：补 `TimeBlock` 类型与载荷字段（0.5d）；
2. `QuickCreateModal` 接线 + 空值拦截（0.5d）；
3. `RecordEditModal` 回填与「未圈选不传字段」逻辑（0.5d）；
4. 自测 + 边界回归（触屏/窄屏/合并）（1d）；
5.（二期）卡片区间摘要展示。
