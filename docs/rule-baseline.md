# 实际文件规则基线与独立评测

## 材料的用途

每组开发任务是一道完整的模拟填报题：空白PDF/Excel是要填的表，UTF-8参考材料是信息来源，input.json声明可见文件、规则版本和单人员范围。ground_truth.json是分离的标准答案，annotations.json记录场景，manifest.json记录生成与审计信息。后三者不能作为填报输入。

这些材料用于调试、回归和比较规则版与后续Qwen版。它们不用于训练模型，也不是实际业务材料。15组受控开发任务已用于开发，不能作为未知模板泛化成绩；human_reviewed仍全部为false。

## 运行

所有命令在WSL项目根执行：

```bash
cd /home/user773/multimodal_agent
.venv/bin/python -m smartfill run-rule-baseline data/dev/v0.1.0
.venv/bin/python -m smartfill fill-rule data/dev/v0.1.0/tasks/DEV-007 --output runs/passport-check/result.json
.venv/bin/python -m smartfill evaluate data/dev/v0.1.0/tasks/DEV-007 runs/passport-check/result.json
```

批量运行自动建立新的runs/rule-时间-随机后缀目录；也可指定--output。目录已存在时拒绝覆盖，不能写入数据集内。单任务输出必须在任务目录之外，已存在时拒绝覆盖。fill-rule遇到材料/规则错误时保存failed结果并返回非零退出码；TaskInput本身不合法时CLI直接报错。

运行目录包括每题result.json、evaluation.json及summary.json。批量执行先保存全部15个预测，再由独立评测器打开答案；答案损坏会保留预测和evaluation_error.json，不生成成功摘要。runs/不提交Git；本次经过核对的摘要快照在docs/rule-baseline-report.json。

## 实现范围

- parsing.py实际读取PDF文本和矩形边框，识别Excel单可见工作表中的标签及相邻空白合并单元格。PDF位置从页面几何归一化生成，不读取模板ID、gold位置或答案字段ID。
- 参考材料只支持UTF-8纯文本，按行保留原文和位置；表单使用声明的领域标签词表，访问项目按可见项目编号关联。不识别的字段进入review_required，不猜值。
- baseline.py仅读input.json及其声明的documents/文件，先核验哈希和路径。单人员范围须显式声明；姓名别名只按可见的明确中英文对应和输出约定归一化。
- 每条同值来源也保留独立候选；值不一致时保留候选、最终建议为null并请求确认。缺失请求材料；无法解析的日期要求复核。
- 只执行sim-travel/1预先实现的规则：来源一致性、含首尾日期的天数、签证区间覆盖。计算输入合并同一语义、相同归一化值的来源证据；任何上游冲突或非法日期阻止计算。规则说明文本不作为可执行代码。
- integrity.py回读实际文本、PDF区域和Excel单元格验证解析内容。证据引用与契约正确不能证明语义正确；这由分离的答案评测进一步检查。

当前输出是带来源的JSON填报草稿；尚未把值写回PDF/Excel。扫描PDF、图片OCR、旋转PDF、Word、复杂Excel、多人员消歧和任意业务规则尚未实现。PDF/Excel支持范围只覆盖这里明确描述的布局，不能据此称为通用表单理解。没有调用Qwen或任何模型服务。

## 指标定义与限制

评测器按目标位置一对一对齐字段：Excel位置完全相等，PDF同页同坐标约定且矩形IoU至少0.8。重复或歧义位置不匹配。标签去空白后相同、类型、必填条件、分组与重复行结构均正确才算识别正确；预测ID、gold ID及semantic_key不参与匹配。

所有比率均保存分子、分母；分母为0时value为null。

| 指标 | 分子 / 分母 |
| --- | --- |
| field_precision / field_recall | 结构正确的匹配字段 / 预测字段或答案字段 |
| field_f1 | 2 × 结构正确的匹配字段 / 预测字段与答案字段数之和 |
| aligned_value_accuracy | 已对齐且结构正确、值正确并为verified的可填字段 / 已对齐且结构正确的答案可填字段 |
| end_to_end_value_recall | 同上分子 / 全部答案可填字段；漏字段也降低成绩 |
| state_action_accuracy | 状态及动作均正确的字段 / 全部答案字段 |
| wrong_fill_rate | 错误非空建议，包括多余字段或不应填的字段 / 全部非空建议 |
| conflict_precision / conflict_recall | 正确识别冲突 / 预测冲突或答案冲突 |
| correct_refusal_rate | 状态、动作、空值和issue codes均正确的异常字段 / 答案异常字段 |
| filled_field_evidence_accuracy | 覆盖至少一组允许证据组合的答案可填字段 / 有证据标注的答案可填字段 |
| source_candidate_precision / source_candidate_recall | 值及来源证据匹配的一对一候选 / 预测候选或答案候选 |
| calculation_chain_accuracy | 规则版本、输入值及证据、输出值、单位全部正确的计算字段 / 答案可计算字段 |
| full_field_pass_rate | 结构、值、状态、动作、问题码、候选、适用证据/计算链全部通过 / 全部答案字段 |
| task_pass_rate | 所有字段通过、无多余字段/运行错误且任务状态正确 / 全部任务 |

冲突/复核字段的候选证据仍逐条检查，但当前0.1.0契约不能在FieldResult额外挂接不属于候选/计算输入的校验依据。签证区间等校验上下文留在全局facts/evidence及issue.document_ids；本轮没有对异常字段的完整跨字段推理证据组合评分。full_field_pass_rate受这一范围限制，不能解释为全部异常推理已获验证。

耗时由实际perf_counter计时，覆盖哈希检查、解析、事实提取、规则与契约校验、物理回读；不含最初TaskInput反序列化、结果写盘和独立评分。stages_ms是该范围内的分段耗时。模型调用为0，model_id和token计数为空；不报告模型成本或服务器吞吐。

## 本次结果与后续

2026-10-12正式运行15组、175字段：163字段verified，5字段conflict，1字段review_required，6字段missing；6题completed、9题needs_review，12个待处理请求。190个来源候选保留，13条日期计算链通过。具体比率及运行位置见JSON摘要；这是开发集回归结果。

100项测试通过，包括原有86项及14项新增集成检查：答案文件缺席、任务/文档ID变化、哈希/规则错误、非法日期、未知标签、伪造解析片段、漏字段、重复位置、错误归一化、全部拒填、丢弃同值候选，以及先完成全部预测再打开答案。

下一步先核验服务器连接、GPU和可用目录，再部署并连通Qwen，通过同样任务和独立评测比较模型基线；之后引入独立模板/实体的验证集、人工核验和OCR，逐步接近真实材料。
