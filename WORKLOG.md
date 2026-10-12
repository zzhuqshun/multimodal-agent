# 多模态智能填报框架工作记录

## 项目速览

- 目标：未知表单理解、多材料关联和带来源证据的可信填报；首期使用虚构出访申请。
- 主工作目录：WSL Ubuntu-24.04-D，user773，/home/user773/multimodal_agent。后续编辑、运行、数据准备和Git操作均在WSL完成。
- Windows smartfill曾为迁移来源；已按用户要求于2026-10-12删除，后续仅使用WSL主目录。迁移以明文内容在Linux重建，未直接复制加密文件。
- 权威来源：用户确认的飞书总体方案https://zcnna0f3aim6.feishu.cn/wiki/NNJWwoDnliiHy8kSHhicvUWfnVg ，机器人读取revision 10；正文在docs/overall-plan.md，交接在docs/handoff.md。
- 13页方案PDF副本在docs/references/overall-plan.pdf，两张表在docs/assets；截断文字与链接目标未恢复。
- 当前开发方向（用户2026-10-12确认）：OCR负责扫描件/图片文字识别，原生解析负责可读取文档；Qwen基于来源片段进行语义理解、字段关联、后续判断及工具选择，程序执行工具和确定性校验。OCR采用PaddleOCR-VL-1.6完整解析流水线；独立服务接通后，先做ParsedDocument适配，再做片段引用式语义映射和最小工具回路；现有文字提取策略保留为历史基线，运行默认尚未切换。
- GitHub目标：https://github.com/zzhuqshun/multimodal-agent.git。

## 当前状态

- 已在服务器/data/zhuqianshun_data/server/paddleocr-vl部署PP-DocLayoutV3 + PaddleOCR-VL-1.6（0.9B）完整流水线，独立Python/依赖/权重/缓存；127.0.0.1:18001提供解析服务，WSL转发及客户端已接通。原Qwen主进程1113117持续运行。统一start/status入口已验证复用；联合停止和两服务同时冷启动本轮未执行。
- 最终相同虚构内容3次PNG/2次无文字层扫描PDF解析通过，耗时2.52–4.84秒，姓名/护照/3×3表格行列及区域边界核对通过；没有独立人工转录或泛化准确率结论。初始auto_growth请求多次超时，naive_best_fit修正后重复通过；完整170项pytest通过。报告docs/ocr-service-report.json，说明docs/ocr-runtime.md。
- OCR服务输出尚未转换为ParsedDocument/填报CLI，片段引用式语义映射及Qwen工具选择/执行回路均未实现；现有固定规则执行不等同于模型调用工具。

- 3模板/15组模拟开发数据已生成于data/dev/v0.1.0：A纵向PDF、B分组Excel、C横向PDF含两个访问项目；6正常、5冲突、4缺失，总计175字段、143文件。
- 每组含可见input.json、documents及分离的ground_truth.json、annotations.json；manifest登记种子20261012、版本、模板族、实体、规则、异常与文件哈希。预测独立保存在runs/，原数据集内没有result.json；15组已完成Qwen材料提取基线独立评测，仍无独立人工核验；模型探针不计入任务评测。
- 数据审计与新进程完整字节复现均通过；结果在docs/dev-dataset-audit.json，操作与限制在docs/dev-dataset.md。生成的数据按原约定忽略Git，源码可重新生成；输出已存在时拒绝覆盖。

- 0.1.0数据契约已实现：Pydantic数据契约、跨对象引用/证据/状态/计算链校验、独立GroundTruth、文本原文件核验、JSON Schema导出和CLI。
- data/examples/normal与conflict均为手工模拟样例，各含原始材料、输入、预构造结果和独立答案；正常样例5字段verified，冲突样例护照号码null并请求确认。
- WSL Python 3.12.3独立.venv已建立，依赖已安装；requirements-dev.lock记录实际版本；当前170项测试通过（原159项及11项OCR输入/扫描PDF保护检查）。
- data/dev、validation、holdout、external已建立，内容默认忽略Git；data/examples内虚构样例可提交。运行产物使用runs/，权重不放项目仓库。
- 已初始化独立Git仓库及codex/contracts-baseline分支，origin指向用户仓库并建立跟踪，契约与开发数据实现已发布。通过现有Windows网关代理连通GitHub，已有SSH身份验证为zzhuqshun。
- WSL可访问PyPI；Windows系统代理为localhost，WSL启动报告NAT模式未镜像该代理；仅为本项目设置Git代理和SSH推送方式，未更改Windows/WSL系统网络配置。
- 远端Qwen3.5-9B已部署并运行在用户指定的/data/zhuqianshun_data/server/qwen3.5-9b；Python 3.12.14、vLLM 0.17.1、PyTorch 2.10.0+cu128、Transformers 4.57.6均为该目录独立环境。WSL经SSH本地转发访问127.0.0.1:18000，served ID为smartfill-qwen3.5-9b；真实文字与合成图片两轮探针均通过。配置示例在.env.example，本地.env忽略Git且CLI只读取导出的环境变量；报告在docs/server-connection-report.json。
- CLI新增fill-rule、run-rule-baseline、evaluate；规则版从实际PDF矩形/Excel空白合并单元格识别字段，读取UTF-8参考文本并生成JSON草稿，先保存全部预测再打开答案。正式运行15题/175字段通过，190候选、13计算链通过，6题completed、9题needs_review、12个请求；详见docs/rule-baseline-report.json和docs/rule-baseline.md。物理证据核验已支持文本、PDF文本区域、Excel单元格；通用任意表单理解、OCR到填报框架的适配及文件写回尚未实现。

- Qwen首轮正式评测在runs/qwen-dev-v1-20261012：148/163可填字段值正确、146/175字段全通过、2/15整题通过；漏读来源使4个应拒填字段错误给值，1题原文校验失败。报告在docs/model-baseline-report.json；当前仅作为待核验草稿，不自动写回。服务器status-qwen.sh已安装验证，可显示本服务进程、GPU与接口状态。

- 当前逐文档有限纠错版已独立评测：39/163可填字段值正确、44/175字段全通过、4/15整题通过、0错误给值，但11题failed，覆盖率不足；默认仅严格实验草稿模式。严格无纠错对照15/15被拒绝，全部结果与91次真实调用记录在docs/model-document-baseline-report.json；OCR仍未接入。

## 工作记录

### 2026-10-12（独立PaddleOCR-VL部署、扫描解析与统一启动）

- 根据用户强调表格/版面和视觉关系的选型要求，核验官方PP-OCRv6、PP-StructureV3与PaddleOCR-VL-1.6资料，最终采用PP-DocLayoutV3 + VL-1.6（0.9B）完整流水线配合原Qwen3.5-9B；未做Structure/v6准确率对照，不声称比较胜出。初始Structure环境目录调整为paddleocr-vl后重建独立环境，未向Qwen/系统环境混装依赖。
- 服务器独立Python 3.12.14、PaddleOCR 3.7.0、PaddleX 3.7.2、Paddle GPU 3.2.1/cu126及114包依赖核验通过。官方BOS归档下载完成，本地来源/归档和文件SHA留在state/model-source.json；未取得发布方摘要，哈希仅作本地完整性记录。安装时临时代理转发已关闭，没有更改全局网络、HOME、驱动或其他应用环境。
- 新增scripts/ocr-server.py、ocr-environment.sh、serve-ocr.sh、install-ocr-environment.sh、download-ocr-models.py、parse-document.py、make-ocr-smoke-fixture.py及start/status/stop-smartfill.sh，部署到授权server及paddleocr-vl目录。服务仅监听本机18001；单并发、文件/页数/像素限制、原始结果和来源哈希保留；停止脚本使用pidfd及精确命令身份，未实际执行联合停止。
- 首次模型虽加载但推理在embedding处反复超时；依据上游issue 17693调整进程专属分配策略为naive_best_fit，初始10240MiB/增长1024MiB/限制12288MiB。首次恢复请求8.6秒；移除诊断钩子并重启仅本项目OCR后，最终WSL连续3次图片/2次扫描PDF请求成功，耗时2.52–4.84秒。未证明底层通用根因或长期稳定。
- 虚构材料经PDF技能生成与渲染核验；初版字体缺失的夹具未计入结果，修正后的v2原图/扫描PDF无文字层。五次响应逐份核对姓名、护照、9个表格单元格与行顺序、区域边界和上传哈希，均通过；同一内容不计作5份独立样本，没有独立人工转录。VL原始table block_order为null，没有单元格bbox或经校准识字置信度，未补造信息。
- 联合启动实测复用现有健康服务，Qwen主PID1113117不变、OCR最终PID2036137；状态脚本通过。活动OCR安装及模型下载脚本均拒绝修改运行中环境/模型；临时下载代理已关闭，解析不依赖该代理。最终快照OCR6746MiB、Qwen引擎24850MiB，GPU 3另有其他任务，共享资源仍有影响。未停止其他应用或重启Qwen。
- 新增11项OCR输入/PDF渲染边界测试，完整170项pytest通过；实际非法base64/PDF均返回400，脚本语法与部署副本核验完成。新增docs/ocr-runtime.md、ocr-service-report.json、requirements-ocr.lock，同步README、AGENTS、流程与运行说明。原始响应/夹具/来源记录位于忽略的runs/ocr-smoke-20261012。
- 尚未接入ParsedDocument、填报CLI、Qwen语义映射/工具回路或写回；未重跑历史模型批量实验。后续先完成来源片段适配与独立扫描评测。

### 2026-10-12（确认OCR识别、Qwen理解与工具执行分工）

- 根据用户明确说明，核对docs/overall-plan.md第4.2–4.5节及现有ParsedDocument、ParsedSegment、Evidence，确认扫描材料OCR识别、Qwen语义/动作判断、程序工具执行的后续路线；可直接读取的PDF/Excel保留原生解析。
- 新增docs/ocr-and-agent-flow.md，说明当前未实现项、复用接口边界、片段引用与原文证据来源、OCR置信信息独立留痕、扫描材料物理核验缺口，以及先OCR、后语义映射、再最小工具回路的验收顺序。
- 更新AGENTS.md、README与日志关键决策/待办，替换原“验证集之后再接OCR”的后续安排；保留所有历史提取实验、失败指标和CLI默认策略。未选择或安装OCR引擎，未修改模型/服务器/依赖，未发起模型请求。
- 本轮验证为Git差异检查、文档链接和六部分日志检查；本轮未重跑代码测试，159项通过为上一轮代码验证结果。

### 2026-10-12（逐文档模型提取、覆盖校验与有限纠错）

- 按用户继续指令完成逐文档模型提取，明确当前Qwen已参与文字事实提取、OCR尚未安装或调用；文件文字解析、模型提取、程序规则与独立评测是不同环节。本轮没有训练/微调/更换模型权重，没有修改服务器环境或部署参数。
- model_baseline.py新增逐片段处理覆盖与已知标签错映射拒绝；模型返回key/segment_id/quote对象和ignored ID列表，使用现有vLLM 0.17.1的JSON Schema输出约束。结构约束不包含字段答案，原文仍由模型提取，程序另行核对。
- 保留首轮all策略；CLI默认document策略，最多一次校验纠错，可用--repair-attempts 0关闭。反馈只含核验原因、原文片段编号和可见标签，不提供字段值，不读答案，不修补回答或回退规则；网络/HTTP/响应封装错误不自动重试，第二次仍错误则整题failed。
- 每次请求/响应/错误/反馈和通过的覆盖记录分别保留，拒绝回答不进入候选，但其用量计入统计。experiments.py从实际预测读取基线版本，补按响应统计真实消耗，非法usage类型也能保留失败评测。全部预测保存后才打开答案，0.1.0数据契约不变。
- 3次协议接通试验均失败并保留，共4次chat请求；提示词依次为grounded-document-rows-2、rows-3、objects-4，未将其计作正式成绩。
- 严格逐文档objects-5正式运行runs/qwen-document-dev-v5-20261012：27次请求，15题均被覆盖/引用校验拒绝，0/175字段全通过、0/15整题通过，没有非空建议；明确没有把全部拒绝称为准确率提高。
- 有限纠错repair-6正式运行runs/qwen-document-dev-v6-20261012：60次请求、18次纠错；39/163可填字段值正确、44/175字段全检查通过、4/15整题通过（DEV-001/011/012/013），1题completed、3题needs_review、11题failed。45/190候选召回、1/5冲突召回、3/13计算链通过；39个非空建议中0错误给值。整题通过数增加但覆盖率下降，仍不能自动写回。
- repair-6输入44494 tokens、输出8285 tokens，60次均有响应记录；合计260.93秒、中位数16.07秒、P95为24.52秒。29次回答被拒绝（27次覆盖/错映射、2次原文引用）；典型问题是将访问日期映射为出行/签证日期、改写中文姓名。当前阶段共91次真实chat请求（4试验+27严格+60纠错），没有隐去失败成本。
- 新增21项流程/统计保护检查，完整159项测试通过；原数据集物理审计passed。新增docs/model-document-baseline.md及比较报告，保留首轮报告并明确复现选项，更新README、运行说明和六部分日志；运行材料和响应仍忽略Git。

### 2026-10-12（Qwen材料提取基线、15组独立评测与状态命令）

- 新增smartfill/model_baseline.py和fill-model、run-model-baseline命令；复用物理表单解析和确定性填报校验，模型只从可见材料提取语义键、来源片段和原文值。提示词grounded-source-rows-1，温度0、关闭thinking、单题一次请求、4096输出上限，没有自动重试、回答修补或规则回退。
- baseline.py重构为共用来源核验与填报引擎；模型来源候选标记llm、证据origin为vlm，保留0.1.0契约。核验精确连续原文、未知键/片段、重复来源、回答完成标记、模型ID和实际token用量；错误生成failed且不输出建议。
- experiments.py先保存全部15份预测及模型请求/响应，再独立打开GroundTruth评测；新增17项测试覆盖来源/任务改名、答案文件缺席、非法模型输出、网络失败留痕、无usage保留null及批量答案隔离。完整138项测试通过，原规则回归保持通过；没有安装新依赖。
- 完成DEV-001接通试运行1次及正式15次填报请求；正式产物在runs/qwen-dev-v1-20261012，原始请求/响应和失败均保留，未根据答案调整提示词或重跑挑选成绩。
- 正式独立评测：148/163可填字段值正确、146/175字段全检查通过、2/15整题通过、150/190来源候选召回、1/5冲突召回、8/12正确拒填、11/13计算链通过；4个应拒填字段给出错误非空建议，1题因原文引用不匹配在提取阶段失败。7题completed、7题needs_review、1题failed；流水线completed不等于答案正确。
- 已检查原始响应：DEV-007/008/009/010漏读冲突来源，DEV-003/006遗漏地址，DEV-004改写中文姓名空格并遗漏姓名对应项。程序可拦截虚构/改写引用，但无法仅凭引用证明所有来源都已提取；当前模型版不能自动写回业务表单。
- 修正数据审计的误导性固定model_runs: 0字段，改为embedded_model_predictions: 0并注明只审计数据集、不扫描外部runs/；更新相关测试与数据文档，历史生成快照保留。
- 正式运行合计151.24秒，中位数9.37秒，P95为15.49秒；服务记录15971输入tokens、4907输出tokens，15题均返回stop。新增docs/model-baseline.md、model-baseline-report.json及逐字段失败检查，明确模型提取+程序校验范围、开发集限制及历史规则比较。
- 新增scripts/status-qwen.sh并仅安装到服务器授权模型根目录；实际检查主进程1113117匹配本目录、GPU 3占用25312MiB、接口READY。状态脚本只读，不触发生成或重启；更新README、部署运行文档及状态查看说明。没有更改其他应用、模型环境、驱动或运行参数。

### 2026-10-12（服务器独立环境、Qwen部署与WSL连通）

- 用户提供SSH连接信息并要求模型环境尽量集中在指定server目录、避免影响其他工作；通过已有known_hosts严格核验后从WSL登录，凭据仅经匿名管道传递，未写入项目、部署脚本或日志。
- 只读确认Ubuntu 20.04.6、系统Python 3.8.10、驱动570.133.20及4张A100 80GB；指定目录可写且已有sam3_server，保留既有环境与进程。
- 在/data/zhuqianshun_data/server/qwen3.5-9b建立独立Python 3.12.14解释器、env、models、cache、tmp、logs、state；安装vLLM 0.17.1和PyTorch 2.10.0+cu128，BF16微型运算及vLLM扩展导入通过。未安装到系统/其他应用环境，未修改驱动或系统网络。
- 官方Hugging Face直连失败，使用Qwen官方ModelScope来源；适配旧curl和短暂DNS/连接超时后，15个文件共19329314298字节（含4权重分片）全部按固定源修订和SHA-256校验。来源记录在服务器state/model-source.json，精确依赖在state/requirements-server.lock及项目docs/requirements-server.lock。
- 新增smartfill/model_api.py、check-model CLI和.env.example实际配置说明；标准库HTTP处理模型列表、固定文字探针、超时/状态/响应校验、拒绝重定向及用量null。没有读取任务答案或将业务材料发送给模型。
- 新增scripts/serve-qwen.sh、install-qwen-environment.sh、download-qwen-model.py源码；处理vLLM旧版不接受CUDA UUID的问题，用数字索引加UUID比对确认GPU 3。运行锁防重复服务与运行中改环境，已验证安装脚本会拒绝修改活动服务环境。
- 单卡BF16、单并发、8192上下文、仅本机18000端口、CPU线程4、nice=10；通过核验进程身份的pidfd只停止并重启本次新服务，将显存规划从0.45降为0.32。旧进程释放时一次启动保护正确拒绝加载，完全释放后启动成功；没有停止其他应用。
- WSL建立只监听本机的SSH转发，运行信息在runs/server-runtime，登录信息不进Git。初始和最终配置共4次真实chat请求，文字返回SMARTFILL_OK、96×96纯红图片返回red，两轮通过；实际耗时与token用量在报告中，未作为吞吐或OCR评测。
- 最终GPU 3快照占用25312MiB、空闲55842MiB，模型目录du约28GiB；从本服务进程白名单环境变量核验主要缓存/临时目录均在模型根目录。共享硬件仍有资源影响，不承诺其他任务性能完全不变。
- 完整121项测试通过（原100、18项HTTP、3项下载保护）；部署脚本语法检查通过。新增docs/server-connection-report.json、依赖锁，更新README及运行说明；Qwen自动填报/15组任务模型评测、OCR和表单写回尚未实现。

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

- 扫描文档主方案采用PaddleOCR-VL-1.6完整流水线；文字、版面区域、表格HTML和原始来源一起保留。VL识别记origin=vlm，原生解析记parser；不补造识字置信度、单元格坐标或缺失阅读顺序。PP-OCRv6与VL-1.6版本号不可直接比较；实际能力由独立材料评测决定。
- 用户要求后续全部在WSL开发，Linux目录为主目录，避免Windows加密链影响代码、依赖和上传。
- schema_version固定0.1.0；值和定位使用kind判别类型。标准答案独立于预测ID与运行输入；未知字段被拒绝。
- 异常字段最终建议为null并带对应动作；verified需要可追溯候选或计算链，只表示当前检查通过，不能证明OCR/语义正确。
- 契约、开发集、规则/Qwen文字提取基线已有验证；后续优先OCR最小链路和独立识别评测，再实现片段引用式语义判断及最小工具执行回路。模型选择动作，程序执行工具并独立校验；LangGraph等框架按实际流程需要引入，不把完整框架作为OCR接入前提。
- 框架与数据在WSL；模型权重、托管Python、独立依赖、缓存、临时文件及日志集中在服务器授权的qwen3.5-9b与paddleocr-vl独立子目录，保留已有sam3_server；不修改系统Python/驱动或其他服务。两服务仅监听服务器本机，通过SSH转发访问；Qwen提供OpenAI兼容接口，OCR提供独立JSON解析接口。
- 首轮单请求策略保留；当前逐文档至多一次校验纠错，两次请求/回答/反馈均留痕，网络错误不重试，不回退规则；全部预测落盘后才加载答案。引用校验不能发现所有来源遗漏，流水线completed/verified不代表独立评测通过。
- 开发数据生成器固定dev用途；相同种子、版本、字体和依赖下可复现。改变种子不产生新的模板族/独立留出实体。
- 15组仅为开发里程碑；评测按模板族和实体隔离。总体方案300–500组完整任务目标保留，100–150组异常为其子集，人工核验可从留出集抽取。
- 不提交密钥、真实业务文件、权重、外部数据下载或运行产物；不强制覆盖远端历史。

## 待办与风险

- GitHub连接已恢复，开发分支已上传；WSL网关IP变化后需刷新本仓库代理与SSH连接参数，详见README。
- 下一步将独立OCR-VL响应转换为ParsedDocument并核验原文件/页图/区域关联，保留表格行列及坐标转换。扩展独立扫描/旋转/拍照/密集表格样本及人工转录，分别评测文字与结构错误；当前五次调用仅同一合成内容，尚无真实准确率或长期稳定结论。随后进行Qwen片段语义映射和日期计算、校验、复核工具回路。
- 原生Paddle推理曾卡住；分配策略修正后的重复测试通过，但客户端超时不会取消服务端推理，1024 tokens/区域上限可能截断密集表格。当前未启用方向分类、去畸变、图表和印章；没有校准置信分数、单元格bbox或完整阅读顺序。联合停止和两服务同时冷启动未实测，未设置系统自启动。
- 逐文档实验仍有11/15题failed、可填字段正确覆盖39/163；减少模型抄写原文不能自动解决语义错配。保留历史对照，不用规则代填提高模型成绩；独立模板族/实体的验证集及人工核验仍待补充。
- 仅支持受控布局的文本PDF/单工作表Excel及UTF-8参考材料；旋转/拍照PDF、Word、OCR框架适配、复杂Excel、多人员消歧及其他业务规则未实现。当前输出JSON草稿，未写回表单；异常跨字段推理证据评分受契约限制，引用一致性不能替代能力测试。
- 服务器连接已核验，实际4×A100 80GB；GPU 0/2已有任务，当前模型使用GPU 3，单并发/8192上下文/显存规划0.32，快照占用25312MiB。共享资源仍有影响，启动空闲检查不能替代GPU调度；SSH转发断开需重建，未设置系统自启动。模型探针只确认连通与简单视觉输入，不能作为OCR或填报准确率。
- 公开数据下载前补查截断许可列与官方链接；方案PDF未保留链接目标。
- 两个手工样例独立于15组开发集；开发集仍为受控模板和单人员文本材料，所有human_reviewed=false，不用于未知模板泛化或真实业务结论。需要后续独立人工核验和隔离模板族/实体的留出集。

## 验证方式

- 本轮完整170项pytest通过；最终5次真实VL解析核对通过，2项非法HTTP输入400，统一启动复用/状态/运行中安装拒绝通过；脚本语法、部署副本SHA、明文和Git差异核验完成。联合停止与两服务同时冷启动未执行，未重跑历史Qwen批量评测。

在WSL项目目录执行：

~~~bash
.venv/bin/python -m pytest
.venv/bin/python -m smartfill audit-dataset data/dev/v0.1.0
.venv/bin/python -m smartfill run-rule-baseline data/dev/v0.1.0
.venv/bin/python -m smartfill validate data/examples/normal
.venv/bin/python -m smartfill validate data/examples/conflict
.venv/bin/python -m smartfill export-schemas schemas
set -a
source .env
set +a
.venv/bin/python -m smartfill check-model
.venv/bin/python -m smartfill run-model-baseline data/dev/v0.1.0
git status --short
~~~

- 当前170项测试包含原159项及11项OCR输入/PDF边界检查；原测试包括逐文档覆盖、语义映射、有限纠错、用量缺失/中断/非法响应统计检查；契约测试覆盖往返序列化、引用/类型/状态/计算约束、独立答案、原文件哈希/引用核验及Schema确定性导出。
- 两个CLI样例通过；人工夹具timing=0不作为耗时测量。
- Linux新进程检查Python语法、JSON解析与文件头，拒绝%TSD-Header；PDF与PNG以明文字节重建。
- 历史来源核验：机器人读取revision 10；13页PDF已渲染查看第7–10页并查看第8、10页两表原图，没有线上写入。
