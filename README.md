# 多模态智能填报框架

当前阶段：0.1.0 数据契约与15组模拟开发任务。开发环境为 WSL Ubuntu，工作目录为 /home/user773/multimodal_agent。

已实现统一Pydantic模型、跨对象一致性检查、两个手工样例、JSON Schema导出，以及3模板/15组模拟任务生成与独立审计。CLI验证的是已经构造好的结果，不会自动理解表单，也不会调用OCR或模型。

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
```

Python要求3.12及以上；当前已验证Ubuntu上的Python 3.12.3。requirements-dev.lock记录本轮实际安装版本；pyproject.toml定义运行依赖与开发依赖范围。当前从源码根目录运行，尚未发布可安装SDK包。

## 当前结构

```text
multimodal_agent/
  smartfill/                 # 数据模型、校验、数据生成/审计、CLI
  tests/                     # 契约与异常场景测试
  schemas/                   # 三类顶层接口的JSON Schema
  data/
    examples/normal/         # 正常手工样例
    examples/conflict/       # 冲突手工样例
    dev/v0.1.0/              # 已生成15组开发任务，默认不提交Git
    validation/              # 验证数据
    holdout/                 # 隔离的最终评测数据
    external/                # 公开数据原始下载
  docs/                      # 总体方案正文、接口说明、部署计划
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

PDF/图片、Excel及Word已有定位对象；通用结果的原文证据核验当前只支持UTF-8纯文本；开发数据审计额外回读自建PDF/Excel的空白字段区域。尚未接入这些格式的解析器，也没有自动填报或模型基线准确率结论。

## 服务器与后续步骤

本地WSL负责框架、数据和规则；计划由服务器运行Qwen，通过OpenAI兼容HTTP接口调用。服务器地址、服务模型ID和密钥由外部配置提供，不硬编码进数据模型。当前.env.example仅为预留约定，CLI尚未加载它或发起网络请求。

后续顺序：规则基线与评测 → 服务器环境核验和Qwen部署/连通 → 相同数据上的模型基线 → OCR扩展。详见docs/runtime-and-server.md。

公开数据、模型权重、真实业务文件、.env、虚拟环境和运行产物不提交Git。暂未声明本项目开源许可证，仓库可访问不等于数据和模型可重新分发。

## GitHub

目标仓库：https://github.com/zzhuqshun/multimodal-agent 。开发分支为codex/contracts-baseline。当前机器通过Windows网关已有7897代理访问，HTTPS读取、SSH的443端口推送；连接配置只作用于本仓库，不包含私钥。主机公钥按GitHub官方来源核验：https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints 。

WSL重启后若网关IP改变，需要更新本仓库Git代理和core.sshCommand中的代理地址。可用ip route show default查看当前网关；这是本机网络配置，不是项目运行依赖。

## 生成开发数据

~~~bash
.venv/bin/python -m smartfill generate-dev
.venv/bin/python -m smartfill audit-dataset data/dev/v0.1.0
~~~

已生成3种PDF/Excel模板、15组虚构任务（6正常、5冲突、4缺失）、175个目标字段。参考材料当前为UTF-8文本；标准答案和注入记录独立存放，不进入运行输入。没有调用模型。生成器拒绝覆盖已有输出目录，详细目录、字体环境、重新生成方式及限制见docs/dev-dataset.md。

当前86项测试通过，包括23项新增数据检查。生成数据保存在WSL的data/dev/v0.1.0，按约定被Git忽略；GitHub保存可复现的生成器与依赖。
