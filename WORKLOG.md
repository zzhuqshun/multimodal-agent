# 多模态智能填报框架工作记录

## 项目速览

- 目标：未知表单理解、多材料关联和带来源证据的可信填报；首期使用虚构出访申请。
- 主工作目录：WSL Ubuntu-24.04-D，user773，/home/user773/multimodal_agent。后续编辑、运行、数据准备和Git操作均在WSL完成。
- Windows smartfill曾为迁移来源；已按用户要求于2026-10-12删除，后续仅使用WSL主目录。迁移以明文内容在Linux重建，未直接复制加密文件。
- 权威来源：用户确认的飞书总体方案https://zcnna0f3aim6.feishu.cn/wiki/NNJWwoDnliiHy8kSHhicvUWfnVg ，机器人读取revision 10；正文在docs/overall-plan.md，交接在docs/handoff.md。
- 13页方案PDF副本在docs/references/overall-plan.pdf，两张表在docs/assets；截断文字与链接目标未恢复。
- GitHub目标：https://github.com/zzhuqshun/multimodal-agent.git。

## 当前状态

- 3模板/15组模拟开发数据已生成于data/dev/v0.1.0：A纵向PDF、B分组Excel、C横向PDF含两个访问项目；6正常、5冲突、4缺失，总计175字段、143文件。
- 每组含可见input.json、documents及分离的ground_truth.json、annotations.json；manifest登记种子20261012、版本、模板族、实体、规则、异常与文件哈希。预测独立保存在runs/，原数据集内没有result.json；没有模型调用或独立人工核验。
- 数据审计与新进程完整字节复现均通过；结果在docs/dev-dataset-audit.json，操作与限制在docs/dev-dataset.md。生成的数据按原约定忽略Git，源码可重新生成；输出已存在时拒绝覆盖。

- 0.1.0数据契约已实现：Pydantic数据契约、跨对象引用/证据/状态/计算链校验、独立GroundTruth、文本原文件核验、JSON Schema导出和CLI。
- data/examples/normal与conflict均为手工模拟样例，各含原始材料、输入、预构造结果和独立答案；正常样例5字段verified，冲突样例护照号码null并请求确认。
- WSL Python 3.12.3独立.venv已建立，依赖已安装；requirements-dev.lock记录实际版本；当前100项测试通过（63项契约、23项开发数据检查、14项规则基线与独立评测集成检查）。
- data/dev、validation、holdout、external已建立，内容默认忽略Git；data/examples内虚构样例可提交。运行产物使用runs/，权重不放项目仓库。
- 已初始化独立Git仓库及codex/contracts-baseline分支，origin指向用户仓库并建立跟踪，契约与开发数据实现已发布。通过现有Windows网关代理连通GitHub，已有SSH身份验证为zzhuqshun。
- WSL可访问PyPI；Windows系统代理为localhost，WSL启动报告NAT模式未镜像该代理；仅为本项目设置Git代理和SSH推送方式，未更改Windows/WSL系统网络配置。
- 远端配置示例在.env.example，部署计划在docs/runtime-and-server.md；没有模型适配器、SSH连接、模型安装或服务调用。
- CLI新增fill-rule、run-rule-baseline、evaluate；规则版从实际PDF矩形/Excel空白合并单元格识别字段，读取UTF-8参考文本并生成JSON草稿，先保存全部预测再打开答案。正式运行15题/175字段通过，190候选、13计算链通过，6题completed、9题needs_review、12个请求；详见docs/rule-baseline-report.json和docs/rule-baseline.md。物理证据核验已支持文本、PDF文本区域、Excel单元格；通用任意表单理解、OCR及文件写回尚未实现。

## 工作记录

### 2026-10-12（实际文件规则填报与独立评测）

- 新增smartfill/parsing.py、baseline.py、evaluate.py、experiments.py及tests/test_baseline.py；扩展integrity.py物理回读，CLI增加fill-rule、run-rule-baseline、evaluate，保持0.1.0数据契约不变。
- 从真实PDF矩形和Excel标签/合并空白格发现字段，使用独立生成的字段ID；仅按可见标签、显式项目编号与姓名对应关系提取事实，不读取gold、annotations、manifest或任务ID场景映射。
- 保留同值不同来源候选；冲突、缺失、非法日期和未知标签不产生非空建议。模拟日期计算合并同一语义相同归一化值的来源证据；初次评测发现DEV-002天数数值正确但计算证据不完整，修正后独立评测通过，未修改答案。
- 批量先保存所有预测，再独立加载GroundTruth、验证原文件并按位置/结构对齐；新增漏字段、重复位置、错误归一化、全部拒填、丢弃候选、答案文件缺席、任务/文档ID变化及评测中断保留预测等检查。
- 单任务fill-rule/evaluate命令通过，原数据集重新审计passed且六部分日志结构检查通过；完整100项测试通过；正式运行runs/rule-20261012-112510-7cd43af9覆盖15题175字段，163个verified、5个conflict、1个review_required、6个missing；190候选和13计算链通过，6题completed、9题needs_review、12个处理请求，无运行错误。
- 新增docs/rule-baseline.md和真实运行摘要docs/rule-baseline-report.json，更新README、data说明。本轮所有编辑、测试及Git操作在WSL完成；未调用模型、部署服务器、运行OCR或将值写回PDF/Excel。
- 评测范围明确：可填字段的证据组合及所有来源候选可评测；当前契约不支持为异常字段外挂非候选校验依据，未声称完整校验其跨字段推理证据。本轮仍是受控开发回归，无独立人工核验/泛化结论。

### 2026-10-12（3模板15组开发数据生成与审计）

- 新增smartfill/dataset.py、dataset_audit.py和tests/test_dataset.py；CLI新增generate-dev、audit-dataset，生成器先在临时目录建立并审计后交付，拒绝覆盖已有输出。
- 生成A.pdf、B.xlsx、C.pdf三个空白模板和DEV-001至DEV-015；参考材料为带SIMULATED标记的UTF-8文本，覆盖姓名显式对应、日期格式与干扰日期、访问行关联、来源冲突、签证区间冲突、缺失和天数计算。
- 标准答案从注入后的可见材料构造，独立审计器重新读取实际文件；核验哈希、引用、归一化值、候选保留、计算输入、目标位置及目录越界，隐藏注入前值不用于填写。
- WSL .venv新增ReportLab、openpyxl、pdfplumber及必要依赖；pyproject.toml声明dataset依赖组，requirements-dev.lock固定实际版本。使用WSL现有中文TTF，修正其缺少拉丁字形的问题。
- PDF经Poppler渲染并目视检查；Excel实际回读和OOXML版面预览检查通过，修正标题行高；环境没有Artifact Tool运行库或原生Excel/LibreOffice渲染器，未声称原生渲染验证。
- 86项测试通过，正式数据审计通过；相同种子在新的Linux进程重生成143个文件，全部字节哈希相同。预期状态为163 verified、5 conflict、1 review_required、6 missing；这是答案分布，不是模型成绩。
- 更新README.md、data/README.md、接口说明、新增docs/dev-dataset.md及审计报告；没有下载公开数据、连接模型服务器或调用模型，没有将模拟任务标记为独立人工核验。


### 2026-10-12（删除Windows旧项目）

- 用户明确要求删除C:/Users/xd04333/Documents/ChatGPT/Agent框架/smartfill；操作前核验绝对路径及普通目录属性，删除范围仅限该项目。
- 回收站接口失败后，改用PowerShell原生删除；旧pytest缓存受权限限制，沙箱外重试成功，已确认旧目录不存在。本次为直接删除，未成功移入回收站。
- WSL主目录、核心源码、两个样例、方案PDF和独立Python环境仍存在；清理没有修改业务代码。此前63项测试通过，本轮未重复运行测试。


### 2026-10-12（GitHub首版上传完成）

- 从WSL创建实现提交5800bab，使用用户指定署名；成功推送至zzhuqshun/multimodal-agent的codex/contracts-baseline分支并设置跟踪。
- 提交42个项目文件；虚拟环境、实际数据下载、运行产物、私钥和本机连接配置均未提交。
- 推送后git status --short为空，测试结果保持63项通过；本次仅补记上传事实，不改变代码。

### 2026-10-12（GitHub连接恢复）

- 从WSL默认路由得到Windows网关，现有7897代理可达；Git ls-remote返回成功且远端无引用。
- 按GitHub官方公布的Ed25519公钥核验主机，通过443端口SSH认证为用户仓库账号；使用已有密钥，未复制或输出私钥。
- 本仓库保存HTTP代理、SSH推送地址和连接参数；提交署名使用用户指定信息，只记录于Git配置，不在本日志保存邮箱。

### 2026-10-12（第一步实现与WSL明文重建）

- 用户授权逐步实施，并要求后续全部在/home/user773/multimodal_agent进行；目标原为空目录，已重建可读源码、样例、Schema、文档及方案PDF/图片。
- 实现smartfill/contracts.py、integrity.py、__main__.py和tests/test_contracts.py；拒绝悬空引用、伪造引用、非法路径、冲突静默选值及不合法状态，校验模拟含首尾日期天数。
- 创建正常与冲突两个手工任务及独立ground_truth.json；异常保留不同来源并请求确认，不用答案填补缺失材料。
- 新增README.md、AGENTS.md、data/README.md、docs/runtime-and-server.md、.env.example、pyproject.toml和requirements-dev.lock；更新接口说明实现状态及PDF位置。
- WSL新进程确认源码可解析、JSON可读；63项pytest通过，两个CLI样例通过，三类JSON Schema已导出。
- 初始化独立Git仓库并设置origin；远端检查20秒超时，curl访问GitHub8秒超时、PyPI访问成功。随后通过Windows网关已有代理恢复GitHub连接，核验远端为空、已有SSH身份认证成功；仅配置本项目Git连接，未修改服务器。
- Windows测试曾有临时文件访问限制；本轮验收以Linux实际结果为准。

### 2026-10-12（PDF正文与两张表复核）

- 按用户要求复核项目根目录多模态智能填报框架建设方案.pdf：提取13页正文，渲染查看第7–10页，提取并目视读取第8、10页表格图片；源PDF未修改。
- 两张表以图片嵌入，因此不在正文提取结果中。确认数据规模表中异常任务包含于完整任务包，独立人工校验集可从留出任务抽取；数据集表右侧部分文字截断，未猜测缺项或链接。
- 新建docs/pdf-review.md、docs/assets/plan-datasets-table.png和plan-data-scale-table.png；更新方案对照及接口草案，保留3模板、15组开发里程碑与更大规模目标的区别。
- 使用已有运行时依赖，无新增安装、模型部署或业务代码。首次终端打印遇GBK编码失败，但UTF-8文本提取文件已生成，随后以PowerShell读取并完成图片核对。

### 2026-10-12（用户本地方案核对）

- 读取项目根目录用户新增的多模态智能填报框架建设方案.md；未改写用户原文件。
- 比对本地导出与机器人取得的revision 10正文，去除Markdown转义、空白及sheet占位符后相同；导出未包含两张内嵌表，表格缺项仍保留。
- 更新docs/plan-comparison.md、docs/mvp-contract-proposal.md及本记录的来源与验证状态。
- PowerShell验证读取响应ok=true、identity=bot、revision_id=10，且保存的Markdown与响应content完全一致；确认WORKLOG六部分齐全。Python直接读取快照曾报UTF-8解码错误，本轮使用PowerShell完成内容验证，尚未核查跨进程读取差异的原因。

### 2026-10-12（总体方案读取与对照）

- 用户提供新Wiki链接并明确允许机器人读取；使用bot身份读取总体方案正文，保存docs/overall-plan.md及完整docs/overall-plan.fetch.json响应。
- 比较总体方案与交接说明，新增docs/plan-comparison.md，记录LangGraph时序、存储、输出执行、业务范围、数据规模、部署顺序和Skills基线的差异；未修改项目长期目标或在线文档。
- 更新docs/mvp-contract-proposal.md的来源、标准答案候选、异常注入可见性、离境日期语义案例及后续人工修正边界。
- 按嵌入资源引用读取两张电子表格，均因机器人缺少sheets:spreadsheet:read失败；未切换身份或猜测表格内容。当前接口建议仍待用户确认，未进行业务代码开发。

### 2026-10-12

- 读取用户交接说明和适用工作区约定，检查空目录、父级 Git 根、命令路径、Python 解释器及依赖可发现性、本机 GPU。
- 使用 lark-cli docs +fetch 读取指定飞书 Wiki，返回缺少用户授权；依交接要求等待导出 Markdown，不推测方案正文。
- 新建 smartfill 项目，保存 docs/handoff.md、docs/mvp-contract-proposal.md 和本记录；提出对象关系、证据与状态约束、15 组开发任务矩阵和下一项实现边界。
- 本轮没有安装依赖、下载数据、部署模型或编写业务代码；未运行 MVP 与业务测试。



## 关键决策

- 用户要求后续全部在WSL开发，Linux目录为主目录，避免Windows加密链影响代码、依赖和上传。
- schema_version固定0.1.0；值和定位使用kind判别类型。标准答案独立于预测ID与运行输入；未知字段被拒绝。
- 异常字段最终建议为null并带对应动作；verified需要可追溯候选或计算链，只表示当前检查通过，不能证明OCR/语义正确。
- 先契约与标准答案，再3模板/15组开发数据、规则基线与评测、Qwen直接基线及OCR；LangGraph、Skills、多Agent、数据库、MCP和GUI待基线可评测后考虑。
- 框架与数据在WSL；模型权重与服务计划在服务器，通过OpenAI兼容HTTP接口调用；当前仅预留配置约定。
- 开发数据生成器固定dev用途；相同种子、版本、字体和依赖下可复现。改变种子不产生新的模板族/独立留出实体。
- 15组仅为开发里程碑；评测按模板族和实体隔离。总体方案300–500组完整任务目标保留，100–150组异常为其子集，人工核验可从留出集抽取。
- 不提交密钥、真实业务文件、权重、外部数据下载或运行产物；不强制覆盖远端历史。

## 待办与风险

- GitHub连接已恢复，开发分支已上传；WSL网关IP变化后需刷新本仓库代理与SSH连接参数，详见README。
- 下一阶段：核验服务器连接/GPU/目录，部署并连通Qwen后运行相同任务，与规则基线比较；后续补独立模板族/实体验证集及人工核验。
- 仅支持受控布局的文本PDF/单工作表Excel及UTF-8参考材料；扫描/旋转PDF、Word、OCR、复杂Excel、多人员消歧及其他业务规则未实现。当前输出JSON草稿，未写回表单；异常跨字段推理证据评分受契约限制，引用一致性不能替代能力测试。
- 服务器SSH主机、端口、用户名、登录方式和可用目录待提供；交接所述4×A100未核验；具体Qwen权重和vLLM版本部署前查官方来源。
- 公开数据下载前补查截断许可列与官方链接；方案PDF未保留链接目标。
- 两个手工样例独立于15组开发集；开发集仍为受控模板和单人员文本材料，所有human_reviewed=false，不用于未知模板泛化或真实业务结论。需要后续独立人工核验和隔离模板族/实体的留出集。

## 验证方式

在WSL项目目录执行：

~~~bash
.venv/bin/python -m pytest
.venv/bin/python -m smartfill audit-dataset data/dev/v0.1.0
.venv/bin/python -m smartfill run-rule-baseline data/dev/v0.1.0
.venv/bin/python -m smartfill validate data/examples/normal
.venv/bin/python -m smartfill validate data/examples/conflict
.venv/bin/python -m smartfill export-schemas schemas
git status --short
~~~

- 当前100项测试包含63项契约检查、23项数据检查和14项规则填报/独立评测集成检查；契约测试覆盖往返序列化、引用/类型/状态/计算约束、独立答案、原文件哈希/引用核验及Schema确定性导出。
- 两个CLI样例通过；人工夹具timing=0不作为耗时测量。
- Linux新进程检查Python语法、JSON解析与文件头，拒绝%TSD-Header；PDF与PNG以明文字节重建。
- 历史来源核验：机器人读取revision 10；13页PDF已渲染查看第7–10页并查看第8、10页两表原图，没有线上写入。
