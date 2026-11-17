# CIVA v1.0.2：面向 AI 生成 CATIA 模型的智能验证研究原型

CIVA（CATIA Intelligent Verification Agent）研究如何检查 Codex 等 Vibe Coding 工具生成的 CATIA 模型：**设计要求 → 读取结构化证据 → 检查缺陷 → 分析特征依赖 → 给出修复建议 → 用 Q-learning 优化检查顺序**。

> **先说清楚：现在是离线、合成数据研究原型，不是完成 CATIA 原生自动检查的产品。**
> 所有真实几何测量、特征依赖和工程约束证据都必须由可信工具提供；当前的 CATIA V5 适配器只能尝试读取少量元数据。不修改 CATIA 模型，不训练大语言模型，不自动提交修复。

## 1. 零基础，先跑起来（Windows）

需要：Python **3.10 或更新版本**。建议先从 [python.org](https://www.python.org/downloads/) 安装（安装时勾选 `Add Python to PATH`）。

1. 解压 `CIVA_v1.0.2.zip`。
2. 进入 `CIVA_v1.0.2` 文件夹。
3. 双击 **`RUN_DEMO_WINDOWS.bat`**。
4. 运行结束后，在 `runs/demo` 中双击 `full_report.html`（五条规则全部检查）；再打开 `rl_triage_report.html`（Q-learning 只检查预算内的类别）。
5. `runs/demo/q_policy.json` 是训练产生的 Q 表；`runs/demo/benchmark.json` 是模拟评测结果。

也可以在解压后的项目根目录打开终端：

```bash
python -m pip install -e .
python -m civa demo
python -m unittest discover -s tests -v
```

> 无需 CATIA、GPU、API Key。`RUN_DEMO_WINDOWS.bat` 自动设置 `PYTHONPATH=src`，无需先安装项目。

## 2. 与 v1.0.1 相比有什么升级？

| 模块 | v1.0.2 的工作状态 |
| --- | --- |
| 参数化设计 | ✅ 对输入的参数数值及公差进行规则检查（不解析 CATIA 公式） |
| 几何正确性 | ✅ 对输入的测量值检查（不自动测量 CATPart 几何） |
| 特征树结构 | ✅ 对输入的结构化 `feature_tree` 检查直接依赖、特征存在性及状态 |
| 工程约束 | ✅ 新增数值上下限及布尔约束规则；需要事先提供证据 |
| 缺陷分析与修复 | ✅ 为 FAIL 的规则生成疑似原因、上下游特征和只读修复建议；不证明根因 |
| Q-learning | ✅ 四类动作、有限预算、奖励/惩罚、Q 表训练、决策轨迹和离线对比 |
| 真正 CATIA 智能验证 | ⏳ 仍未实现可信的原生几何、特征树、工程数据抽取 |
| 自动修改 CATIA | ⛔ 不执行；修复仅为候选方案，需人工审核 |

**注意：预算按“检查类别”计算，不是按单条规则计算。** 例如选择 `feature`，会执行该类别下的 `REQ-F001` 和 `REQ-F002` 两条规则。

## 3. 核心方法（你答辩可这么讲）

系统首先读取描述设计目标的 `requirements.json` 和模型证据 `snapshot.json`，按照四个方面检查模型。如果发现不符合要求的项目，就定位对应的检查项，沿**已提供**的特征依赖图找上下游影响，提出下一步人工确认和修改方案。系统不直接修改原模型。

随后加入 Q-learning：**状态**包含模型的可见风险类型、此前检查结果和剩余检查预算；**动作**是选择 `parameter / geometry / feature / constraint / STOP`；**奖励**来自离线模拟案例中已知的缺陷真值。训练让 Q 表逐渐学到在有限检查预算下下一项该选哪类。实际验证时没有隐藏真值，系统也不会凭空计算“正确检出”的奖励。

奖励函数：

```text
R = 6 × 正确检出(TP) − 8 × 漏检(FN) − 10 × 误报(FP) − 0.5 × 检查类别次数
```

奖励参数可通过 `--tp / --fn / --fp / --cost` 修改，但重新训练后才会生效。**算法只选择检查顺序，不负责替规则判断 PASS/FAIL。**

## 4. 常用命令

```bash
# 训练：合成数据上迭代 10000 回合，最多选 2 类检查
python -m civa train --episodes 10000 --budget 2 --out runs/q_policy.json

# 想自己设置奖励，例：正确检出 +8，漏检 -10，误报 -12，每类检查 -1
python -m civa train --episodes 10000 --budget 2 --tp 8 --fn -10 --fp -12 --cost -1 --out runs/custom_q_policy.json

# 看懂 Q 表：初始状态下各类动作的 Q 值
python -m civa inspect-policy --policy runs/q_policy.json

# 未见过的模拟案例：RL、固定顺序、简单风险提示策略三者比较
python -m civa evaluate --policy runs/q_policy.json --cases 500

# 五条规则全部执行
python -m civa verify --mode full --snapshot examples/bracket_bad.json --requirements examples/requirements.json --out runs/full.html

# 只执行预算允许的类别，输出逐步决策轨迹
python -m civa verify --mode budgeted --policy runs/q_policy.json --snapshot examples/bracket_bad.json --requirements examples/requirements.json --out runs/rl.html

# 证据不完整时：应给出 UNVERIFIED，而不是 PASS
python -m civa verify --mode full --snapshot examples/bracket_partial.json --requirements examples/requirements.json --out runs/partial.html
```

`RUN_DEMO_WINDOWS.bat` 和 `python -m civa demo` 会一次性运行训练、评测、两种报告。

## 5. 输入数据是什么？

- `examples/requirements.json`：**设计目标**。声明板厚 5 mm、孔径 8 mm、最小壁厚 2.5 mm、草图约束及切除特征的父节点。
- `examples/bracket_bad.json`：**模拟错误模型**。人为设置了不同类别的错误，包含参数、测量值、特征状态、工程约束以及 `feature_tree` 依赖关系。
- `examples/bracket_good.json`：对应的模拟正确模型。
- `examples/bracket_partial.json`：证据缺失模型，用于演示 `UNVERIFIED`。

举例：

```json
{
  "id": "REQ-C001",
  "family": "constraint",
  "target": "MinWallThickness",
  "operator": "min",
  "expected": 2.5,
  "tolerance": 0.05,
  "feature_ref": "BasePad"
}
```

这项规则要求输入证据中的 `constraints.MinWallThickness` 不小于 `2.5 mm`（演示容差 `0.05 mm`），因此输入 `1.7` 时判定 FAIL。**结构化数值必须已经使用与要求一致的单位；代码不自动转换 CATIA 单位。**

`feature_tree` 示例：

```json
"feature_tree_complete": true,
"feature_tree": {
  "BasePad": {"depends_on": []},
  "HoleSketch": {"depends_on": ["BasePad"]},
  "HolePocket": {"depends_on": ["HoleSketch"]}
}
```

`feature_tree_complete=true` 仅表示**数据提供者明确保证特征列表完整**。无法确认完整性时，请不要设为 true；否则可能把没有抽取到的特征误判为缺失。依赖关系必须来自可信提取或人工整理，不能凭演示数据推测真实 CATIA 特征树。

## 6. 从哪里看代码？

建议按以下顺序，**不需要一上来读完整个项目**：

1. `examples/requirements.json` — 检查目标是什么。
2. `examples/bracket_bad.json` — 检查证据长什么样。
3. `src/civa/core.py`：`check_one()` → `verify_full()` → `repair_proposals()`。
4. `src/civa/rl.py`：`VerificationEnv.state()` → `legal_actions()` → `step()` → `train()` → `policy_verify()`。
5. `src/civa/cli.py` — 键入命令后，调用了哪一个函数。
6. `tests/` — 用一个小测试证明自己的理解。

更详细的逐段教程：**[docs/读代码入门.zh-CN.md](docs/读代码入门.zh-CN.md)**。
GitHub 图文思路与 Git 命令：**[docs/上传GitHub.zh-CN.md](docs/上传GitHub.zh-CN.md)**。
强化学习技术说明：**[docs/reinforcement_learning.md](docs/reinforcement_learning.md)**。

## 7. 真实 CATIA 接口的边界

可选：仅在 Windows + 安装了有授权的 CATIA V5 + `pycatia` 时尝试：

```bash
python -m pip install pycatia
python -m civa capture-catia --out runs/catia_snapshot.json
```

目前只能采集当前 CATPart 的文档名、Body 名称和**未经单位归一化**的参数显示字符串。几何、工程约束、特征依赖没有可靠读取，相关字段留空，因此示例规则应返回 `UNVERIFIED`。后续应先开发可信的证据提取与人工标注的数据集，再用真实模型做评测。禁止宣称此版本已能自动修复 CATIA 模型。

本项目采用 MIT 许可（原创代码）。请勿公开企业专有 CATIA 文件、许可证、API Key 或私密数据。CIVA 与 Dassault Systèmes 无官方关联。
