# CAVAI 技术架构、证据约束与后续开发计划

## A. 为什么这不是“先运行固定检查，再让 AI 总结”

主路径 `AgentRunner.run_events` 把可调用的专业工具 JSON Schema 发送到模型服务。模型返回真实 `tool_calls` 后：

1. 检查工具名称是否存在于 `TOOL_GUIDES` 的允许列表。
2. 确认工具参数为空对象（所有真实工程输入从已校验的上传要求获取，不相信模型编造数值）。
3. 根据工具名称调度 `run_tool`（必要时重新调用 OCCT 的拓扑检查器）。
4. 把 `{status, scope, title, evidence, explanation, recommendation, evidence_id}` 结果按 `role=tool` 发回 LLM。
5. 模型可以选择新的检查工具、调整推断、最终输出修复建议。
6. 关键不变量由系统补做的检查采用 `origin=mandatory_baseline`，绝不计入 Agent 动态调用次数。

因此：**Tool Calling 的决定权属于 LLM；工程事实的产生权属于 CAD 内核与规则工具；修复文本由 LLM 给出但不自动执行。** Agent 的策略不等于专门训练过的 CAD 专家模型，知识目前主要由规则和提示词提供。

## B. 输入与结构化 CAD 表示

所有文件通过格式适配器映射为内存 `CadModel`：

```python
@dataclass
class CadModel:
    filename: str
    format: str
    sha256: str
    summary: dict
    preview: dict
    shape: Any = None   # STEP/IGES read by Open CASCADE
    mesh: Any = None    # STL read by Trimesh
```

`summary` 包含可采集的长度单位、包围盒、体积、实体/面/边计数、圆柱面候选数据、网格完整性和 **哪些原生能力缺失的说明**。

每条检查证据包含：

```json
{
  "evidence_id": "EV-0002",
  "tool": "check_envelope",
  "origin": "llm_tool_call",
  "scope": "functional",
  "status": "pass",
  "title": "导入坐标系下的包络尺寸符合要求",
  "evidence": {
    "measured_mm": [80, 50, 6],
    "max_allowed_mm": [81, 51, 7],
    "excess_mm": [-1, -1, -1]
  }
}
```

上面仅是**证据数据格式说明**；正式运行时，`measured_mm` 必须从实际 CAD 后端产生，不能使用文档里的例子替代真实检测。

## C. 格式能力边界

| 适配器 | 真实几何 | 特征依赖 | 参数/草图 | 装配约束 | 工程性能 |
|---|---|---|---|---|---|
| STEP OCP | 可，当前已测 | 否 | 否 | 否 | 不支持 |
| IGES OCP | 可，具体读取拓扑因导出方式而异；已测曲面 | 否 | 否 | 否 | 不支持 |
| STL Trimesh | 三角网格可 | 否 | 否 | 否 | 不支持 |
| CATPart CATIA COM | Windows 适配后可 | 计划中 | 计划中 | 部分计划中 | 需专用校验器 |
| CATProduct CATIA COM | Windows 适配后可 | 计划中 | 计划中 | 计划中 | 需装配、工况与专用工具 |

**特别案例：** 示例 `bracket_4hole.igs` 虽然可导入实际边界曲面，返回几何尺寸和曲面网格；由于未识别出封闭实体，不提供实体体积，但 `solid_count=0`，圆柱解析面数为零。拓扑检查正确将其提示为需要复核的曲面表示。这既不是伪造缺陷，也不应被当作一个有效的原生实体 CATPart。

## D. 独立事实 vs AI 候选结论

- `input.user_declared_purpose`：用户明确输入（并非经过物理证实的工程事实）。
- `preliminary_llm_intent_hypotheses`：大模型推断可能用途，不能自动升级为设计要求。
- `model_evidence`：几何解析器实际提取的结构事实。
- `tool_trace`：有状态与 ID 的执行记录。
- `confirmed_findings`：工具判断为明确不满足给定可验证条件；不是工程认证。
- `review_items`：模型数据或要求不足，需要人工验证。
- `ai_analysis_unverified_until_engineer_review`：LLM 原始最终解释/修复文字，永远不能替代 CAD 计算证据。

当前能够做的部分**功能**检查主要是：用户明确约束下的 AABB 最大包络比较、实体数量和候选圆柱面直径。尚不能对孔距、紧固件干涉、载荷路径或疲劳给出已验证结论。

## E. Agent 规划与工具执行状态（预留 RL）

状态提取：模型类型、风险桶、已执行工具、剩余工具预算和已发现明确失败。

动作：从 `TOOL_GUIDES` 注册的下一项检查动作中选择。

Agent 当前动作策略：LLM 多轮 Tool Calling，必要时强制安全基线。

以后可插入 `TabularQPolicy` 来对候选工具排序或推荐，不修改物理工具的输出。可采用“模型提议 + 策略建议”的混合模式，或者比较独立的 LLM 策略、固定规则和 Q-learning 策略。

`cavai/rl.py` 已提供：
- `InspectionState`：离散化状态（模型类型/风险/预算/已做检查）
- `ReviewedFeedback`：受审计的真值标签；拒绝模型自我打分，漏检奖励要求完整真值
- `reward_from_review`：奖励计算示例
- `TabularQPolicy.choose/update`：epsilon-greedy 和标准 Q 更新接口

标准 Q 更新：

\[
Q(s,a)\leftarrow Q(s,a)+\alpha[r+\gamma\max_{a'}Q(s',a')-Q(s,a)].
\]

示例奖励系数仅是**待研究的实验设计**：

\[
R=8TP-12FN-5FP-0.4C.
\]

必须在独立、完整的工程标签集上调参；不能根据大模型自己的描述给真值奖励。当前无真实标注集，RL 尚未训练，也未参与 MVP 动态规划。

### 未来可复现实验

1. 建立一组带人工验证真值的零件：正确零件、缺失孔、尺寸超限、非封闭实体、错误材料/装配等。
2. 每个案例给定相同可用工具、相同计算预算、相同设计要求与相同工程真值。
3. 基线 A：固定规则顺序。基线 B：LLM 自主工具调用。实验 C：Q-learning 选择下一项检查。
4. 指标：TP/FN/FP、严重缺陷检出率、发现高风险缺陷前调用次数、平均时间/Token/成本。
5. 模型与零件类型分层拆分训练/验证/测试；保留未见零件，避免同一 CAD 变体泄露。
6. 提供置信区间和失败案例；若 Q-learning 表现不优，应如实报告。

## F. CATIA V5 真正接入的分阶段实施路线

**前提：** 有安装并取得许可的 CATIA V5 的 Windows 机器，以及可工作的 Python COM 环境（pywin32 或 pycatia）。Linux 环境中的本项目无法验证 COM 行为。

1. `CatiaV5Adapter`：将 CATPart 文档打开，读取 Part、Body、Shapes、Sketches、Parameters，构建形状/特征 ID。
2. `FeatureDependencyGraph`：遍历可获取的引用及父子关系，建立依赖边；对无法读取的元素标注 unknown。
3. `CATProductAdapter`：读取 Products/Components、实例变换、装配约束、引用文件路径，遇到缺失外部引用则报告不可验证。
4. `CATUpdateTool`：在隔离副本上运行更新，捕获 CATIA 返回的错误和失效特征；默认只读，需用户确认才允许修改。
5. `GeometryBridge`：从 CATIA 的几何对象或临时 STEP 导出构建与 OCCT 的统一 B-Rep 记录。**原生特征树来自 CATIA，而不是 STEP 逆向猜测**。
6. `RepairExecutor`（未来）：在用户确认后修改参数→在副本更新→复查所有依赖→保留回滚和审计记录。
7. Windows CI 或实体 CATIA 工作站验收：使用真实 CATPart/CATProduct 和错误树样例逐项测试。

`examples/catia_v5_com_probe.py` 是**尚未验证、尚未接入系统的 COM 代码起点**。它只演示预期读取 BODY 特征名和参数，不运行更新或保存，不能当作已实现能力。

## G. 安全、性能与运维局限

目前针对可信本地开发环境：
- 单进程、内存模型仓库、最大上传 25 MiB、最大 STL 三角面 250,000、预览面数最多 3500、模型约 1 小时过期。
- API Key 仅存在单次运行配置内，不写回报告。
- 仅允许配置 HTTPS 外部 Base URL；本地地址默认需要 opt-in。生产部署必须再加 DNS/IP 白名单和反 SSRF 机制。
- HTTP 调用有超时、受限重试、Token 和回合预算，但远端的精确计费无法硬性保证。
- LLM 只可选择已注册、输入为空的只读工具。所有工程尺寸来自独立验证后的上传模型和用户明确要求。

**尚未解决，不应直接上线：**
- CAD 内核面对恶意或损坏 CAD 的进程级隔离、解析超时和沙箱；
- 组织级认证、权限、密钥托管、审计、存储加密与多租户隔离；
- 复杂 STEP/IGES 大规模装配支持、系统级并发、巨型 STL 优化；
- 工程 standards / 公差链 / 运动仿真 / FEA / 真实机械功能验收；
- 完整专业知识库的可靠性评测与实验验证。

## H. MVP 后验收 checklist

- [x] 上传真实 STEP/IGES/STL，并解析几何/网格。
- [x] 生成实际网格三维预览和几何测量。
- [x] 用户设置外部 Chat Completions Key、Base URL 和模型参数。
- [x] 实现多轮 function tool calls + 工具结果回传。
- [x] 采用机械知识提示词、只读工具及证据 ID。
- [x] 区分基本结构状态、明确功能约束结果和全部功能未验证。
- [x] 缺陷/未确认项及 AI 修复建议 + JSON/HTML 导出。
- [x] Q-learning 状态、奖励和更新接口（仅离线测试，没有训练）。
- [x] 本地实际解析和 mock HTTP 调用自动化测试。
- [ ] 使用真实用户外部 API Key 完成公网端到端试验。
- [ ] Windows + 真实 CATIA V5 COM 验证 CATPart/CATProduct。
- [ ] 专家复核真值数据集与严格 RL 对照实验。
- [ ] FEA / 约束依赖 / 复杂装配工程分析。
