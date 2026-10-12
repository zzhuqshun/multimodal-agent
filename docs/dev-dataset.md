# 15组模拟开发任务

日期：2026-10-12。数据版本/生成器版本0.1.0，默认种子20261012，split固定为dev。

本批数据用于开发调试，不是未知模板泛化评测、独立人工核验集或真实业务数据。没有调用大模型，没有生成预测result.json，也没有模型准确率结论。

## 生成与检查

在WSL项目根目录执行：

~~~bash
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m smartfill generate-dev
.venv/bin/python -m smartfill audit-dataset data/dev/v0.1.0
.venv/bin/python -m pytest
~~~

默认生成目录为/home/user773/multimodal_agent/data/dev/v0.1.0。生成器拒绝覆盖任何已存在的输出目录。需要重新生成时使用新的目录，例如：

~~~bash
.venv/bin/python -m smartfill generate-dev --output data/dev/rebuild-001 --seed 20261012
~~~

相同生成器、依赖、字体和种子下，文件内容可复现；测试比较全部文件字节哈希。数据先在相邻临时目录生成并完成审计，成功后整体移入目标目录，审计失败不会交付半成品。

WSL当前中文字体为/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf，来自已存在的系统字体。其他环境可通过--font指定可嵌入的中文TrueType字体；字体文件哈希与生成依赖版本记录在manifest.render_environment中。字体缺失时生成器报错，不自动下载字体。字体或渲染依赖变化可能改变PDF字节和定位，需重新审计。

当前WSL没有Artifact Tool运行库及其工作区依赖加载工具，Excel生成使用openpyxl回退；PDF使用ReportLab，独立回读使用pdfplumber。PDF经过Poppler渲染目视检查，Excel经过实际文件回读及基于OOXML的版面预览检查；未进行原生Excel/LibreOffice渲染。

## 目录和输入边界

~~~text
v0.1.0/
  manifest.json
  templates/
    A.pdf
    B.xlsx
    C.pdf
  tasks/
    DEV-001/
      input.json
      documents/
        form.pdf
        passport.txt
        itinerary.txt
        visa.txt
        invitation-1.txt
        invitation-2.txt
      ground_truth.json
      annotations.json
    ... DEV-015/
~~~

部分任务会额外包含姓名对应表、申请人声明或冲突材料；模板B的form为xlsx。参考资料是有SIMULATED标记的UTF-8文本，没有模拟真实证件版式、照片、印章或扫描噪声。

运行时仅使用input.json及其中documents声明的文件。ground_truth.json、annotations.json、manifest的任务类别和异常标签不传给填报程序或模型。annotations保存注入前/后变化及受影响字段，只用于数据质量审查。生成器没有将答案或隐藏语义映射写入空白表单，不给模板添加答案公式或隐藏工作表。

manifest记录数据版本、生成器版本、种子、模板族、split、独立实体ID、模拟规则版本、异常标签、人工核验状态及逐文件SHA-256。15组任务的实体ID互不重复，但每组复用本族模板；改变种子不会产生新的模板族和独立留出实体，不能把重生成结果当作留出集。

## 模板与任务

| 模板族 | 格式 | 字段数/任务 | 结构 |
|---|---|---:|---|
| A | 纵向PDF | 9 | 单列标签和填写区域 |
| B | Excel | 9 | 人员、行程、参考信息三个分组 |
| C | 横向PDF | 17 | 9个基本字段，2个访问项目各4字段 |

每个模板5组：2组正常，其余按矩阵分配，总计6正常、5冲突、4缺失。完整逐任务矩阵见mvp-contract-proposal.md第4节。正常任务覆盖不同日期格式、显式中英文姓名对应、离境日与访问开始日/签发日区分、访问项目分行关联与含首尾天数计算。

几个关键异常：

- DEV-007/008/009/010：护照号、有效期、第一项目开始日或姓名的来源冲突，保留所有可见候选，答案为null并请求确认。
- DEV-011：模拟签证有效期未覆盖返程日。返程为conflict，issue为visa_range_mismatch；天数为review_required，issue为upstream_conflict。它与source_conflict区分。
- DEV-012/013：缺签证有效期或邀请方地址，请求资料。
- DEV-014：缺返程日，返程和天数均missing；不使用隐藏的注入前返程日计算答案。
- DEV-015：仅第二访问项目联系人missing，其他项目字段继续填写。

所有规则均为显式模拟规则，不代表法规或真实机构填报要求。任务明确所有材料属于同一出访人员；签证区间缺失只要求补充签证字段，不把有来源的行程日期一并清空。姓名按可见对应表归一化为英文姓名，日期仅接受明确的年月日格式；参考资料中相近日期不替代目标字段。

## 审计与实测边界

本轮86项测试通过，其中新增23项数据检查。数据独立审计结果保存在dev-dataset-audit.json。

175个目标字段的标准答案分布：163个verified、5个conflict、1个review_required、6个missing。这是预期答案统计，不是系统预测成绩。

审计器重新读取文件，检查文件哈希、路径边界、材料声明、模拟标记、PDF区域内标签、Excel合并区域与空白填写格；从可见参考文本重新解释日期、姓名对应和来源冲突，校验候选、最终答案、计算输入及注入结果。没有使用待测模型生成或评判标准答案。

生成器与审计器由同一开发过程编写，仍可能共享理解偏差；所有任务human_reviewed=false。已完成开发者层面的代表场景检查，没有标记为独立人工核验。扫描、OCR、多人员实体歧义、复杂自然语言邀请函以及真实文档鲁棒性仍待后续数据扩展。

## 下一步

实际文件解析入口、规则基线和按目标位置/结构对齐的独立评测已完成；正式开发集运行结果见[规则基线报告](rule-baseline-report.json)，使用与指标说明见[规则基线说明](rule-baseline.md)。当前完整测试100项通过；上述86项为数据生成阶段的历史记录。下一步核验服务器并连接Qwen，再用相同数据比较模型基线。

生成的数据目录按既有约定被Git忽略；GitHub保存源码、依赖与审计说明，拉取代码后可以运行上述命令生成数据。不要将虚拟环境、外部数据、权重或私密资料加入仓库。
