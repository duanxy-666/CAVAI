# CAVAI v0.2 联调记录

| 项目 | 结果 | 限制 |
|---|---|---|
| Python 文件 AST 语法 | 通过 | 构建环境 Python 3.13 |
| 原有 STEP / IGES / STL 几何解析测试 | 通过 | 使用真实样例 |
| 原首页 `/api/upload` 接受 CATPart | 通过 | CATIA COM 由测试替身提供 |
| CATPart 自动导出后 OCCT 读取 | 通过 | 测试替身返回的是仓库中真实 STEP 文件 |
| CATPart 原生信息无几何导出 | 通过 | 确认拓扑、尺寸、实体数不会伪造为通过 |
| CATPart Agent 动态工具调用与流报告 | 通过 | LLM HTTP 由 MockTransport 模拟 |
| JavaScript `node --check` | 通过 | 不等于真实浏览器功能验收 |
| Windows CATIA V5 COM 真机联调 | 未运行 | 必须在用户电脑测试真实 CATPart |
| 真实 DeepSeek API 调用 | 未运行 | 需用户本地配置 Key |

测试集执行结果：**17 passed**。测试集通过不代表已验证工程可制造性。
