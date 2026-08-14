# 时间块圈选录入 · 后端需求与开发规划

> 关联前端文档：`docs/time-block-frontend-plan.md`
> 数据契约：`time_blocks: [{"start": 540, "end": 630}]`，当天 00:00 起分钟数，`end` 不含，均为 30 的倍数。

## 1. 背景与目标

配合前端「时间块圈选」录入，为工作记录持久化**具体工作区间**。
原则：**`work_records.minutes` 保留为冗余合计**，现有统计、周报归集、校验全部不受影响；区间明细进新子表。

## 2. 数据模型（alembic 迁移）

新增表 `work_record_time_blocks`：

```sql
CREATE TABLE work_record_time_blocks (
  id            VARCHAR(36) PRIMARY KEY,
  record_id     VARCHAR(36) NOT NULL
                REFERENCES work_records(id) ON DELETE CASCADE,
  start_minute  INTEGER NOT NULL,  -- 当天 00:00 起，含
  end_minute    INTEGER NOT NULL,  -- 当天 00:00 起，不含
  CONSTRAINT ck_wrtb_range
    CHECK (start_minute >= 0 AND end_minute <= 1440 AND end_minute > start_minute),
  CONSTRAINT ck_wrtb_slot
    CHECK (start_minute % 30 = 0 AND end_minute % 30 = 0)
);
CREATE INDEX ix_wrtb_record ON work_record_time_blocks (record_id);
```

- 新建迁移脚本（风格参考 `alembic/versions/d8e7f6a5b4c3_enforce_half_hour_work_record_steps.py`），`down_revision` 接当前链尾；
- 新表不涉及重建 `work_records`，SQLite 直接用 `op.create_table`；注意沿用项目对 SQLite 外键的处理约定；
- `downgrade()` 为 `drop_table` + 删索引；
- **无需数据回填**：历史记录无区间，`time_blocks` 返回空数组即可。

`app/models.py` 新增：

```python
class WorkRecordTimeBlock(Base):
    __tablename__ = "work_record_time_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_records.id", ondelete="CASCADE"), index=True
    )
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        CheckConstraint("start_minute >= 0 AND end_minute <= 1440 AND end_minute > start_minute",
                        name="ck_wrtb_range"),
        CheckConstraint("start_minute % 30 = 0 AND end_minute % 30 = 0", name="ck_wrtb_slot"),
    )
```

`WorkRecord` 加 `relationship`（`cascade="all, delete-orphan"`，`order_by=start_minute`）。

## 3. Schemas（`app/schemas.py`）

```python
class TimeBlockInput(BaseModel):
    start: int = Field(ge=0, lt=1440, multiple_of=30)
    end: int = Field(gt=0, le=1440, multiple_of=30)

    @model_validator(mode="after")
    def validate_order(self):
        if self.end <= self.start:
            raise ValueError("时间块结束必须晚于开始")
        return self

class TimeBlockOut(BaseModel):
    start: int
    end: int
```

改动点：

| Schema（行号参考） | 改动 |
| --- | --- |
| `WorkRecordCreate`（697） | 增加 `time_blocks: list[TimeBlockInput] = []`（上限如 24 段） |
| `WorkRecordUpdate`（715） | 增加 `time_blocks: list[TimeBlockInput] | None = None`（`None` = 不改动，`[]` = 清空） |
| `WorkRecordQuickCreate`（780，`extra="forbid"`） | 增加 `time_blocks: list[TimeBlockInput] = []` |
| `WorkRecordOut`（734） | 增加 `time_blocks: list[TimeBlockOut] = []` |

公共校验（建议写成可复用 validator）：

1. 单块：`0 <= start < end <= 1440`，30 的倍数（Field 已覆盖）；
2. 块间：排序后**不得重叠**；相邻（`next.start == prev.end`）视为非法，要求前端先合并——**服务端不做静默合并，非法即 422**，避免客户端数据被暗中改写；
3. **minutes 一致性（关键决策）**：载荷带 `time_blocks` 时，服务端以 `SUM(end - start)` 重算 `minutes` 并覆盖入库存储，不校验客户端传的 `minutes`。理由：单一事实来源在区间，避免双写不一致；载荷不带 `time_blocks` 时维持旧行为（老客户端兼容）。

## 4. 服务层（`app/services/work_records.py`）

| 函数 | 改动 |
| --- | --- |
| `create_work_record` | 事务内写入 blocks；有 blocks 时按 §3.3 重算 minutes |
| `quick_create_work_record` | 同上；幂等重放（`replayed`）直接返回已存记录，序列化自然带出 blocks，无需特殊处理 |
| `update_work_record` | `time_blocks is not None` 时整体替换（删除旧块→插入新块）并重算 minutes；替换走同一事务，失败整体回滚 |
| `delete_work_record` | 软删除保持不变；blocks 物理行随硬删级联，软删期间保留（恢复时区间仍在） |

- 序列化器 `app/serializers.py` 的 `work_record_out` 带出 `time_blocks`（按 `start_minute` 排序）；
- 任何导致 blocks 变化的写操作与现有逻辑一致：推进 `revision`、记 `last_edited_by`、代编辑原因等既有约束不变；
- 周报/仪表盘统计只读 `minutes`，无需改动。

## 5. API 契约示例

`POST /api/v1/work-records/quick-create`（`POST /api/v1/work-records` 同理）：

```json
{
  "idempotency_key": "…",
  "work_date": "2026-08-14",
  "content": "完成方案评审并修订总体架构图",
  "minutes": 150,
  "time_blocks": [{"start": 540, "end": 630}, {"start": 840, "end": 930}],
  "project_id": "…"
}
```

`PATCH /api/v1/work-records/{id}`：

```json
{ "revision": 3, "time_blocks": [{"start": 540, "end": 660}] }
```

`WorkRecordOut` 响应追加：

```json
"time_blocks": [{"start": 540, "end": 630}, {"start": 840, "end": 930}]
```

错误响应：重叠/相邻未合并、越界、非 30 倍数 → 422，错误消息中文明示原因。
上线后同步更新 `docs/API_CONTRACT.md`。

## 6. 测试清单（`tests/`）

- [ ] 创建：带 2 段合法 blocks → 201，minutes = 各块之和（即使传入的 minutes 不符也被重算）；
- [ ] 兼容：不带 `time_blocks` 的老载荷 → 行为与现状完全一致；
- [ ] 非法：`end <= start`、越界（<0 / >1440）、非 30 倍数、两块重叠、两块相邻未合并 → 422；
- [ ] 更新：`time_blocks` 省略（None）→ 区间不变；`[]` → 清空区间；新列表 → 整体替换且 minutes 同步；
- [ ] 更新区间会推进 `revision`，旧 `revision` 提交 → 409；
- [ ] 软删后区间仍可随记录读出；硬删级联删除 blocks；
- [ ] 幂等重放返回的 `work_record` 含一致 blocks；
- [ ] 迁移 up/down 在 SQLite 上可重复执行（`upgrade-db` 流程）。

## 7. 上线顺序与回滚

1. **后端先上线**（接受新字段，旧前端无感）；
2. 前端再上线（开始发送 `time_blocks`）。

回滚：前端下线即停止发送；后端字段为可选，保留无影响；如需彻底回滚，执行迁移 `downgrade()` 前先确认无在线依赖（区间内数据会丢失，`minutes` 不受影响）。

## 8. 开发步骤建议

1. 迁移脚本 + `WorkRecordTimeBlock` 模型（0.5d）；
2. Schemas + 公共校验（0.5d）；
3. 服务层写入/替换/重算 minutes + 序列化（1d）；
4. 测试用例补齐（1d）；
5. 更新 `docs/API_CONTRACT.md`，与前端联调（0.5d）。
