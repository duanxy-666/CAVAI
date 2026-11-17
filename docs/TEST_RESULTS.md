# CAVAI MVP · 已执行测试记录

记录环境：Linux x86_64，Python 3.13.5，`cadquery 2.8.0`，`trimesh 4.11.1`，
`fastapi 0.128.2`，`httpx 0.28.1`，Open CASCADE (OCP)，pytest。

运行命令：

```bash
python -m pytest -q tests
node --check cavai/static/app.js
```

**最新结果：15 passed，0 failed；JavaScript 语法检查 exit=0。**

## 有效的真实模型解析实测

所有文件由实际 CadQuery/OCP 实体创建，再以 STEP / IGES / STL 写入磁盘并重新读取：

| 文件 | 实际读取结果 | 结论 |
|---|---|---|
| `bracket_4hole.step` | 80×50×6 mm；B-Rep 检查有效；1 solid、10 faces、4 analytic cylindrical faces；每个圆柱直径 6 mm；实体体积 23,321.416 mm³ | 成功读取可用 STEP 实体信息 |
| `bracket_4hole.igs` | 80×50×6 mm；10 imported faces，但 **0 solid**、0 analytic cylindrical faces；不报告可信实体体积 | 成功读取实际 IGES 曲面，不能冒充 CATPart 或保证结构性 |
| `bracket_4hole.stl` | 80×50×6 坐标单位；用户确认 mm 后得到 mm 标注；网格封闭且方向一致；网格体积约 23,321.697 mm³ | 成功读取三角网格，体积与精确 B-Rep 不同，符合网格近似特性 |

关键验证：
- 若 `max_envelope_mm=[81,51,7]`，样例 STEP 的尺寸上限检查通过。
- 若 `max_envelope_mm=[70,51,7]`，工具准确返回第一轴超出 10 mm。
- 若提供 `target_cylinder_diameter_mm=6`，可读取 4 个匹配解析圆柱面；**并不证明是完整的安装孔/孔距匹配**。
- 当 STL 单位为 unknown 时，毫米包络比对返回 `unverified`，没有伪造毫米尺寸。
- 无法读取 CATPart 时明确返回失败信息，不把任意字节当 CAD。

## API 与 Agent 测试

- FastAPI 文件上传、图形预览接口、离线规则检查、支持格式与功能清单接口：通过。
- `httpx.MockTransport` 模拟兼容 Chat Completions API：验证 POST 地址、Bearer 头、`tools` 声明、多轮 `assistant.tool_calls` 和 `role=tool` 的返回。
- LLM 根据第一轮几何工具结果又请求了后续 `check_envelope`；工具不是在 LLM 完成后才机械地运行，动态工具执行记录可以追溯。
- 未产生 Tool Calling 时，报告不会把 `mandatory_baseline` 冒充自主动作。
- CAD 工具故意抛异常时，该项结果为 `unverified` 而不是“通过”；Agent 仍能生成可追溯报告。
- `/api/inspect` 的完整报告，以及 `/api/reports/<id>.json` / `.html` 导出：通过。
- `/api/inspect/stream` 的实际分段 `phase` → `tool` → `report` NDJSON 事件：通过。
- Key 的 Pydantic repr 被遮盖、报告不包含测试 API Key：通过。
- `ReviewedFeedback` 必须来自可信类别且拥有完整真值，才能计漏检奖励；Q 更新基本计算：通过。

## 不要把测试结果扩大解释

**未在当前环境验证：**

1. 真实公网 DeepSeek / OpenAI Key 的账号、额度、模型权限和 API 回答质量（无用户 Key）。
2. Windows + CATIA V5 已安装状态下对 CATPart/CATProduct 的原生 COM 解析、更新、装配检查。
3. 机械强度/疲劳/装配干涉/制造工艺、真正的参数依赖、专家确认的修复动作。
4. 大规模真实零件集、损坏 CAD、并发生产负载与运行隔离安全。
5. 有专家真值标签的强化学习训练，以及 Q-learning 优于基线的统计证据。

这个软件目前是一个具有真实数据解析与可执行 Agent 调度能力的 **本地研究型 MVP**，不是工业设计放行软件。

`examples/REAL_OFFLINE_EVIDENCE.json` 是从真实示例 STEP 运行规则工具得到的结果（明确标记为离线规则输出），不是伪造的 LLM 推理报告。
