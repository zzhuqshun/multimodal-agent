# MVP 接口与标准答案规范（0.1.0）

日期：2026-10-12。

状态：用户已授权分步实施；数据契约、引用校验、正常与冲突两个手工样例及JSON Schema已实现，WSL中63项测试通过。实际定义以smartfill/contracts.py、integrity.py和schemas/为准，运行与限制见../README.md。后续生成器、解析器、基线和评测仍是计划。

依据：交接说明及机器人读取的总体方案revision 10，正文与响应已保存。两张内嵌表已通过13页PDF复核，PDF副本为references/overall-plan.pdf，表图在assets/。部分截断文字、超链接目标未恢复，详见pdf-review.md。

## 1. 最小目录与实现顺序

以下为分阶段目录规划。当前代码直接位于smartfill/，没有src/层；仅contracts.py、integrity.py、__main__.py和对应测试已实现，其余模块按需添加。实际目录见README。

```text
smartfill/
  WORKLOG.md
  pyproject.toml                  # 到实现阶段定义依赖
  docs/
    handoff.md
    overall-plan.md               # 已读取的飞书正文，表格另见PDF复核
    plan-comparison.md            # 总体方案与交接说明的差异及建议
    mvp-contract-proposal.md
  smartfill/
    contracts.py                 # 第一项：Pydantic 对象及约束
    integrity.py                 # 跨对象引用、证据定位一致性
    dataset.py                   # 后续：固定种子生成与任务清单
    pipeline.py                  # 后续：固定处理链路
    parsers/                     # 后续：按实际输入格式接入
    baselines/                   # 后续：规则、模型两个独立入口
    rules.py
    evaluate.py
  tests/
    test_contracts.py
    test_integrity.py
  data/dev/                      # 仅合成开发数据
    manifest.json
    tasks/<task_id>/
      input.json
      documents/
      ground_truth.json          # 只供评测，不进入模型输入
  runs/<run_id>/                  # 输出、计时、错误、配置版本
```

实施顺序：①总体方案对照与契约确认 → ②契约、引用校验、一个人工构造样例 → ③3种表单及15组带答案合成任务 → ④文本/Excel或可提取文本PDF解析、规则映射基线 → ⑤相同输入的Qwen直接处理基线 → ⑥图片OCR与扫描PDF扩展 → ⑦留出集评测。Word接口预留，首轮实现优先聚焦PDF和Excel。

FastAPI、LangGraph、经验Skills、MCP和GUI在基线可评测之后再考虑。传输接口不应影响核心对象；模型适配器接受解析内容并返回候选结构，不能直接把模型输出视为已验证结果。

## 2. 核心对象与关系

所有序列化对象携带 schema_version；ID 为任务范围内稳定字符串。路径为相对任务目录路径，禁止绝对路径及越界路径。文件哈希用于验证原始材料一致性。

| 对象 | 建议字段 | 语义与边界 |
|---|---|---|
| TaskInput | task_id, schema_version, description, target_document_id, documents, ruleset_id, ruleset_version, as_of_date | 明确目标表单、参考资料和模拟业务规则；参考资料不得包含标准答案 |
| Document | document_id, role(target_form/reference), media_type, relative_path, sha256, synthetic | 原文件身份；护照/签证/邀请函可作为 document_type 提示，不能充当事实真值 |
| ParsedDocument | document_id, parser_name, parser_version, segments, issues | 解析/OCR产物；segment保存原始文字及定位，解析失败保留错误 |
| FormSchema | form_id, target_document_id, fields, groups | 对未知表单的识别结果；字段语义可能未知，不强制映射到预设业务字段 |
| FormField | field_id, label, semantic_key?, value_type, required, required_when?, target_locator, group_id?, row_id?, constraints | label保留原文；semantic_key允许为空；行字段按实例寻址，不能用名称作唯一ID |
| Evidence | evidence_id, document_id, segment_id, locator, quote, origin | 指向来源材料具体位置；quote必须对应解析文字，不由模型补写 |
| ExtractedFact | fact_id, entity_id?, predicate, raw_value, normalized_value, value_type, evidence_ids | 材料中识别的事实，与目标表单分离；未知实体不能强行合并 |
| FieldCandidate | candidate_id, field_id, fact_ids, value, evidence_ids, method, score? | 同字段可有多个候选；score只辅助排序，不能证明正确 |
| ValidationIssue | issue_id, code, severity, field_ids, document_ids, rule_id?, message | 机器可识别code与可读解释；字段异常、解析错误等均有明确归属 |
| FieldResult | field_id, candidate_ids, selected_candidate_id?, suggested_value, status, evidence_ids, issue_ids, derivation? | 统一最终建议；保留候选但异常时不自动采用 |
| FillingResult | task_id, run_id, schema_version, form_schema, parsed_documents, facts, evidence, candidates, fields, issues, review_requests, task_status, errors, timing, run_metadata | 可独立审计的结果包；包含引用的解析片段，或附带带哈希的不可变产物索引 |
| GroundTruth | task_id, schema_version, dataset_version, expected_form, expected_fields, annotation_provenance | 独立标准答案；不来自待测系统的预测 |

关系：TaskInput 指定 Document → 解析得到 ParsedDocument → 目标文档得到 FormSchema，参考资料得到 ExtractedFact → Fact以Evidence支撑 → 候选关联目标field与Fact → 规则产出Issue及FieldResult → FillingResult汇总。GroundTruth在评测器中与预测比较，不能传给pipeline。

### 值与定位规范

- 文本保留原文和规范化值；证件号码必须是字符串，保留前导零。日期采用ISO日期，明确类型；含歧义日期不自行推断日/月顺序。
- 金额采用十进制字符串及币种，避免浮点误差；枚举值、单位、时区及列表有明确类型。null表示未确定，不能用空字符串或“未知”替代。
- PDF/图片：page从1开始，bbox为页面旋转校正后左上原点的归一化坐标，记录坐标基准与变换信息。文本引用锚定segment及字符区间[start,end)。
- Excel：sheet名称与A1单元格/范围；Word后续采用段落或表格/行/列地址；文本采用segment或行号及字符区间。Locator使用有判别字段kind的联合类型，不能把不同格式拼成任意字符串。
- 目标字段位置target_locator属于目标表单；来源Evidence.locator属于参考材料，两者分别校验。
- OCR证据首先证明“解析片段中有该文字”，不能单凭引用匹配证明OCR正确；视觉证据保留原页位置，后续通过标注或人工抽样检查。
- required_when使用有限声明式条件，例如“出访类型等于会议”，不执行来自文档或模型的任意Python表达式；当前无法判断条件时标记review_required。

### 字段状态与不可违反的约束

| 状态 | 含义 | 建议值 |
|---|---|---|
| verified | 来源可定位，适用规则通过且无未解决冲突；不代表政府或外部机构认证 | 可非空 |
| conflict | 同一实体与同一语义存在不兼容来源，规则未能解决 | null，保留各候选及证据 |
| missing | 条件满足但资料没有可用来源 | null，并明确补充项 |
| review_required | 身份关联、语义、OCR或条件无法可靠判断 | null，列出确认问题 |
| needs_calculation | 输入足够但计算尚未执行或结果尚未校验 | null，记录所需规则和输入 |
| not_applicable | 明确条件为假，字段无需填写（0.1.0已采用） | null，并记录条件依据 |

计算成功后可转为verified；derivation必须记录rule_id/version、输入fact/candidate ID及结果单位，证据来自输入事实。禁止给计算结果伪造原文引用。

第一版建议仅verified字段允许非空suggested_value。即使出现看似合理的冲突候选，也不静默按文件顺序、模型分数或“新日期”择优。若模拟规则确实规定优先级，应保留规则和被排除来源；缺少依据就拒填。

所有ID唯一；所有外键可解析；候选必须属于当前字段；selected_candidate_id必须来自该字段候选；被采用的值与候选值/计算结果一致。Evidence引用的文件、segment及定位必须存在，quote应与片段对应。伪造quote、孤立引用、证据越界、verified而没有直接证据或有效计算链均应被拒绝。

task_status建议区分completed、needs_review、failed。completed可含规则确认的not_applicable；存在待补充、冲突或复核则needs_review；不可恢复的输入/执行错误为failed。timing区分总耗时与各阶段，单位毫秒；run_metadata记录实现、规则、提示词、模型标识及配置版本，不保存密钥。没有返回token用量时写null，不能计为0；硬件显存等另行采样，不由模型猜测。

## 3. Ground Truth 与评测规范

expected_form独立标注label、类型、必填条件、分组和目标位置。expected_fields按gold_field_id保存语义与目标位置、accepted_values、expected_status、expected_action、evidence_alternatives、expected_issue_codes及必要计算规则。动作建议fill、request_documents、request_confirmation、calculate、leave_blank。

预测field_id不要求等于gold_field_id。评测先按目标位置与结构对齐字段，并检查标签/类型；重复标签通过行、组和位置区分。不能只靠预设semantic_key对齐，否则会掩盖未知表单识别失败。

按总体方案第6.5节补充expected_candidates，保存异常字段应出现的来源候选及其状态依据，不能只标最终空值。annotation_provenance记录合成器/人工标注与复核信息；异常清单记录注入前事实、注入后可见内容及预期动作。隐藏的注入前事实仅供数据质量核验，不能用于填补运行时材料缺失。

evidence_alternatives表示“可接受的多个证据组合”，每个组合内可能要求多个引用；记录document_id、定位、原文或原文校验摘要，不能依赖预测系统生成的evidence_id。日期、证件号必须精确规范化匹配；名称等是否允许别名必须在标注中逐项明确。

异常字段的accepted_values为[null]，同时必须匹配状态、issue和预期动作；仅输出null不能获得完整分数。计算题同时标注期望结果、输入来源和规则。合成器生成事实种子后产生材料和答案，再进行独立校验；不能用待评测模型自行生成并判定标准答案。

至少分别报告：字段识别precision/recall/F1、对齐字段的值准确率、错误填报率、冲突precision/recall、证据组合正确率、应拒填字段的正确拒填率、任务全字段通过率、待人工处理字段数、耗时。人工干预次数在离线阶段只记录请求次数，不能声称实际人工操作次数。

每个指标必须公开分子、分母与未对齐字段处理方式；漏识别字段计入端到端失败。先报告状态与动作，再报告非空值，避免“全拒填”取得看似高分。失败阶段使用parse/form_understanding/extraction/mapping/validation，首期不包含未开发的GUI执行。

## 4. 首批15组开发任务

建议3种模板：A为纵向键值PDF，B为分组Excel，C为带访问行项目的横向PDF。开发轮可先用可提取文本PDF，再加入受控扫描变体；同一任务的扫描变体不能算独立泛化样本。

| 任务 | 模板 | 类别 | 注入条件与预期动作 |
|---|---|---|---|
| DEV-001 | A | 正常 | 单人单次出访；证件、邀请函字段可定位并填写 |
| DEV-002 | B | 正常 | 日期格式不同但无歧义，规范化后一致 |
| DEV-003 | C | 正常 | 多个访问行，单位和日期分别关联正确行 |
| DEV-004 | A | 正常 | 中英文姓名按明确给定的别名关系关联 |
| DEV-005 | B | 正常 | “拟离境日期/计划出发日”语义对齐；同时提供晚一天的邀请访问开始日与签发日期，不得用相近日期替代离境日期 |
| DEV-006 | C | 正常 | 按明确模拟规则计算含首尾日期的出访天数；保留输入与计算链 |
| DEV-007 | A | 冲突 | 同一人员两份材料证件号不一致；证件号null、conflict |
| DEV-008 | B | 冲突 | 两份参考材料记载护照有效期不一致；相关字段拒填并确认 |
| DEV-009 | C | 冲突 | 同一访问项目两份邀请材料日期不一致；对应行日期conflict |
| DEV-010 | A | 冲突 | 任务所给申请人信息与证件姓名矛盾；姓名conflict，其余字段按各自可验证性判断 |
| DEV-011 | B | 冲突 | 签证停留区间无法覆盖计划行程；保留候选事实，受业务约束影响字段拒填并提示复核 |
| DEV-012 | C | 缺失 | 未提供签证有效期；该字段missing并请求补充 |
| DEV-013 | A | 缺失 | 邀请方地址缺失；地址missing，其余可填 |
| DEV-014 | B | 缺失 | 缺返程日期；返程missing、出访天数因缺输入为missing（不是needs_calculation） |
| DEV-015 | C | 缺失 | 缺第二访问单位联系人；只影响相应行字段 |

每模板5组：2正常，剩余冲突/缺失按矩阵分配；总计6正常、5冲突、4缺失。DEV-011属于规则冲突，issue_code应与来源值冲突区分；0.1.0状态术语已固定，业务规则实现留待基线阶段。

每组使用独立虚构实体和材料ID，保存generator_version、seed、template_family_id、entity_ids、ruleset_version、原文件哈希、异常清单和答案。DEV-010的申请人信息需在TaskInput中明确为可审计输入，不能成为未声明的隐藏事实。

生成器同时产生事实、材料和gold定位，渲染后重新核验文字与坐标，防止答案指向旧版文件。模板不向运行时暴露标准语义映射；传统规则基线可使用事先声明的通用词典，但不能读取gold或模板隐藏标签。

15组均标为dev，固定随机种子便于回归。后续留出集另用模板族与实体，两者集合均不相交；生成种子不同本身不能证明无数据泄漏。公开数据集暂不下载、不重新分发，许可在选定具体资源后逐项核验。

PDF第10页规模表确认后续100–150组异常属于300–500组完整任务，不少于100组人工核验样本可从留出任务中抽取。manifest应记录split、template_family_id、entity_ids、异常标签、人工核验状态，避免将子集重复计入总量。

## 5. 下一项实际实现及验收边界

总体方案正文及PDF两张表已复核；本轮已实现contracts.py、integrity.py、CLI、63项测试、一个正常与一个冲突JSON样例，并导出JSON Schema。未安装OCR、vLLM或Agent框架。数据集表的截断文字与具体链接不作为已核实信息。

验收包括：正常结果可序列化往返；冲突结果保留两个来源且建议值为空；缺失字段有请求动作；计算结果能追溯输入和规则；伪造证据、重复ID、错误字段引用、越界定位、verified无依据等失败样例被拒绝；Ground Truth独立加载且不进入待测处理链。

业务规则需标为模拟规则，尤其证件有效性、签证日期与出访天数；不宣称这些规则代表现行法规。该功能已完成；本轮交付运行方法、实测结果与限制，下一阶段为15组开发数据生成器。

后续人工复核阶段单独保存ReviewDecision（run_id、field_id、原建议、修正值、依据、操作时间及审核标识），不得覆盖模型原始输出；本轮仅预留边界，不实现审核流程。
