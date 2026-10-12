# 多模态智能填报框架

当前阶段：0.1.0 数据契约、15组模拟开发任务、实际文件规则基线、Qwen提取基线与独立评测。开发环境为 WSL Ubuntu，工作目录为 /home/user773/multimodal_agent。

已实现统一Pydantic模型、跨对象一致性检查、两个手工样例、JSON Schema导出、3模板/15组模拟任务生成与审计，以及从实际PDF/Excel空白表和UTF-8参考材料生成可信JSON草稿的规则基线。预测先独立保存，再加载答案评测；模型服务已部署并通过文字/图片连通探针；Qwen材料提取+程序校验已完成首轮及逐文档对照评测；尚未接入OCR或表单写回。

## 后续主流程

按用户确认的职责分工，扫描件/图片先由OCR提取文字及位置，可读取文字的PDF/Excel使用原生解析；Qwen负责理解片段、关联目标字段、判断下一步并选择工具，程序工具负责计算、校验和执行。先接通OCR并独立评测，再推进片段引用式语义映射和最小工具回路。现有文字提取策略保留为基线，CLI默认尚未切换；OCR与Qwen工具调用目前均未实现。详见[职责与接入顺序](docs/ocr-and-agent-flow.md)。

## 运行

在WSL终端执行：

```bash
cd /home/user773/multimodal_agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pytest
.venv/bin/python -m smartfill validate data/examples/normal
.venv/bin/python -m smartfill validate data/examples/conflict
.venv/bin/python -m smartfill export-schemas schemas
# 数据已生成时直接运行；没有数据时先运行generate-dev
.venv/bin/python -m smartfill run-rule-baseline data/dev/v0.1.0
```

Python要求3.12及以上；当前已验证Ubuntu上的Python 3.12.3。requirements-dev.lock记录本轮实际安装版本；pyproject.toml定义运行依赖与开发依赖范围。当前从源码根目录运行，尚未发布可安装SDK包。

## 当前结构

```text
multimodal_agent/
  smartfill/                 # 契约、实际文件解析、规则填报、评测与CLI
  tests/                     # 契约与异常场景测试
  schemas/                   # 三类顶层接口的JSON Schema
  data/
    examples/normal/         # 正常手工样例
    examples/conflict/       # 冲突手工样例
    dev/v0.1.0/              # 已生成15组开发任务，默认不提交Git
    validation/              # 验证数据
    holdout/                 # 隔离的最终评测数据
    external/                # 公开数据原始下载
  runs/                      # 每次预测及独立评测，默认不提交Git
  docs/                      # 方案、接口、基线报告、部署计划
  .env.example               # 后续远端模型接口配置示例
  requirements-dev.lock
  WORKLOG.md
```

每个手工任务独立包含input.json、documents/、result.json、ground_truth.json。标准答案只用于独立校验，TaskInput和FillingResult拒绝未声明的ground_truth字段。运行目录从项目根开始，源文件相对路径以各任务目录为基准。

## 样例说明

normal样例包含姓名、护照号码、离境日期、返程日期和出访天数5个字段。两个来源的护照号码一致，输出completed。2026-11-03到2026-11-07按明确的模拟规则计为5天，保留输入事实、规则版本及来源。

conflict样例的护照材料记载P00001234，邀请函记载P00005678；输出needs_review，护照号码字段为conflict、建议值为null，并保存两个候选、证据和确认请求。其余字段独立保留已验证建议。

两个样例均为人工构造的接口样例，未经过模型推理，耗时0为手工夹具占位，不能用来报告性能。它们不属于后续15组开发集，也没有独立人工复核标记。

## 校验范围

- 拒绝未知字段、非法类型、路径越界、重复ID、悬空引用和错误字段选择。
- 原文引用使用字符区间[start,end)，必须对应解析片段；CLI还检查原文件SHA-256、文本片段和gold证据。
- 最终值必须对应候选或确定的计算链；冲突/缺失/复核字段不能给出非空最终建议。
- 来源冲突必须保留不同候选并请求确认；缺失必须请求资料；条件不明必须复核。
- 当前唯一执行的计算规则为模拟的含首尾日期天数。其他业务规则仍需后续实现。

JSON Schema可校验结构和基础类型，跨对象引用及状态约束由Python校验器执行。引用匹配不能证明语义理解或OCR识别正确，也不能保证归一化、实体关联或规则执行正确；这些由后续基线、业务校验和评测验证。

物理核验现支持UTF-8文本、PDF文本区域和Excel单元格。规则解析支持明确矩形边框的文本PDF及单工作表、标签邻接空白合并单元格的Excel；不支持OCR、扫描/旋转PDF、Word、复杂表格和多人员消歧。未知标签进入复核。

正式开发集运行15/15题通过，175字段中163字段填写、12字段按预期拒填，190来源候选和13条计算链通过；当前完整159项测试通过。此数据参与开发，不能作为真实业务或未知模板泛化成绩。运行方法、指标分母和异常证据评分限制见[规则基线说明](docs/rule-baseline.md)，真实摘要见[运行报告](docs/rule-baseline-report.json)。

## 服务器与后续步骤

本地WSL负责框架、数据、规则和评测；服务器独立目录运行Qwen3.5-9B，WSL通过SSH转发访问OpenAI兼容HTTP接口。权重、Python环境、缓存和日志集中在/data/zhuqianshun_data/server/qwen3.5-9b，保留已有应用；当前使用GPU 3、单并发、8192上下文，检查时约25GiB显存占用。实际文字及合成图片探针均通过，详见[连通报告](docs/server-connection-report.json)。

CLI新增check-model，从导出的SMARTFILL_MODEL_*环境变量读取地址、模型ID和超时；.env不自动加载。本地.env已配置，未提交Git。在WSL项目根确认自己的.env后执行：

~~~bash
set -a
source .env
set +a
.venv/bin/python -m smartfill check-model
~~~

服务器仅监听本机端口；SSH或WSL断开后需重建转发，方法见[运行说明](docs/runtime-and-server.md)。GPU依赖单独固定于docs/requirements-server.lock，不安装到WSL框架环境。

Qwen首轮正式评测已完成：148/163可填字段值正确、146/175字段全检查通过、2/15整题通过；150/190来源候选召回、1/5冲突召回，4个错误非空建议、1题原文校验失败。该版共享物理字段解析和程序规则，仅模型提取材料，不能作为端到端自动填报能力。源码、运行方式与失败分析见[模型基线](docs/model-baseline.md)，真实比较见[模型报告](docs/model-baseline-report.json)。

~~~bash
.venv/bin/python -m smartfill run-model-baseline data/dev/v0.1.0
~~~

在已SSH登录的服务器查看状态：

~~~bash
cd /data/zhuqianshun_data/server/qwen3.5-9b
bash ./status-qwen.sh
~~~

脚本显示进程、GPU和接口READY；GPU利用率0%可以是空闲，当前模型仍占用约25GiB显存。持续查看与SSH连接方法见[运行说明](docs/runtime-and-server.md)。

逐文档、覆盖检查和最多一次模型纠错现已实现，默认CLI采用该策略，原始all策略保留。新一轮4/15整题通过、44/175字段全检查通过、0错误非空建议，但11题被拒绝；可填字段的值正确覆盖仅39/163，不能说整体准确率已提高。严格无纠错对照15题全部拒绝，失败结果也保留。详见[逐文档模型说明](docs/model-document-baseline.md)和[完整比较](docs/model-document-baseline-report.json)。

当前测的是模型文字提取与框架调用/校验的组合：Qwen已实际参与，OCR尚未安装或调用，模型权重没有训练或更换。规则版在固定格式开发材料上的满分不等同于未知表单泛化成绩。

下一步缩小模型输出任务，让模型匹配字段与原文片段/位置，减少重新抄写原文造成的错误；随后准备独立验证数据与OCR扩展。当前默认严格实验模式，只生成待核验JSON草稿，不自动写回表单。

公开数据、模型权重、真实业务文件、.env、虚拟环境和运行产物不提交Git。暂未声明本项目开源许可证，仓库可访问不等于数据和模型可重新分发。

## GitHub

目标仓库：https://github.com/zzhuqshun/multimodal-agent 。开发分支为codex/contracts-baseline。当前机器通过Windows网关已有7897代理访问，HTTPS读取、SSH的443端口推送；连接配置只作用于本仓库，不包含私钥。主机公钥按GitHub官方来源核验：https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints 。

WSL重启后若网关IP改变，需要更新本仓库Git代理和core.sshCommand中的代理地址。可用ip route show default查看当前网关；这是本机网络配置，不是项目运行依赖。

## 生成开发数据

~~~bash
.venv/bin/python -m smartfill generate-dev
.venv/bin/python -m smartfill audit-dataset data/dev/v0.1.0
~~~

已生成3种PDF/Excel模板、15组虚构任务（6正常、5冲突、4缺失）、175个目标字段。参考材料当前为UTF-8文本；标准答案和注入记录独立存放，不进入运行输入。生成数据时没有调用模型，后续已单独完成Qwen基线评测。生成器拒绝覆盖已有输出目录，详细目录、字体环境、重新生成方式及限制见docs/dev-dataset.md。

当前159项测试通过，包含开发数据、契约、规则、HTTP、下载保护及模型提取适配检查。生成数据保存在WSL的data/dev/v0.1.0，按约定被Git忽略；GitHub保存可复现的生成器与依赖。
