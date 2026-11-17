# CAVAI v0.2 — 原首页直接上传 CATPart

## 从你现有的 PyCharm 项目升级（推荐）

现有项目：`D:\\CAVAI\\py_environment\\CAVAI_v0.1`

1. 先在 PyCharm 终端按 **Ctrl+C** 停止运行中的 `python run.py`。
2. 下载 `upgrade_cavai.py`，将它保存到 `CAVAI_v0.1` 文件夹内，和 `run.py` 放同一层。
3. 确认 PyCharm 终端前有 `(venv)`，进入项目目录，运行：

   ```cmd
   python upgrade_cavai.py
   python run.py
   ```

4. 浏览器访问原地址 `http://127.0.0.1:8000`，按 **Ctrl+F5** 强制刷新。
5. 先启动 CATIA V5，然后在 CAVAI **原首页**选 `Part2.CATPart`，输入用途，
   点击「解析 CATIA / CAD 文件」；随后配置你本地保存的 DeepSeek Key，
   点击「开始 Agent 自主检查」。

脚本会先把现有文件复制到 `.cavai_backup_before_v02` 备份文件夹，再升级。
脚本不读取、不修改 API Key 或其他用户配置。

## 已接入的真实数据链路

- 首页 `/api/upload` 接收 CATPart 文件（最大 25 MiB）。
- Windows `pywin32` 使用已验证的 `win32com.client.Dispatch("CATIA.Application")` 方式连接 CATIA。
- 自动通过 `CATIA.Documents.Open` 打开上传副本，**只读**取得：
  Part 名称、Bodies/Shapes 一级特征名称、Parameters 名称和可读取的字符串值、HybridBodies。
- 自动尝试 `ExportData(..., "stp")`，失败时尝试 `"igs"`。
- 导出成功后，Open CASCADE 解析临时 STEP/IGES，取得尺寸、拓扑和预览网格；
  用户**不用手动转换**。
- 导出失败时仍显示原生 CATIA 的已读数据，但标记几何、尺寸和拓扑为
  **未验证**；不会伪造预览或声称通过检查。
- 原有 DeepSeek 多轮 Function Calling Agent、离线规则检查与报告导出保持可用。

## 已知限制

- Windows + 本机可用 CATIA V5 COM；当前**没有**跨平台 CATPart 解析器。
- STEP/IGES 自动导出依赖本机 CATIA 的翻译器及权限；可能因软件配置而不可用。
- 一级 Shapes/Parameters 读取**不等于**完整特征依赖图或草图约束验证。
- 不检查参数更新稳定性，也不自动证明工艺可生产、装配功能、材料和强度。
- CATProduct 的原生装配读取尚未实现。
- 当前是可信本机实验 Demo，不应未经认证就暴露到公网。
- 若勾选 Agent 云端检查，模型描述、几何摘要和部分参数名称/值可能发送给
  所选 DeepSeek/OpenAI API；应先确认允许外发的工程数据。

## 实际测试范围

在构建环境运行 `pytest -q tests`：17 项测试通过（详见 docs/TEST_RESULTS_v02.md）。
CATPart 上传和 DeepSeek 端到端线路采用**模拟 CATIA COM / HTTP**测试，
几何部分使用项目里的真实 STEP 示例读取。
由于该环境没有 Windows CATIA V5，**真实 CATPart COM 联调尚未执行**。
