# PaddleOCR-VL 文档解析服务

## 选型与当前结果

2026-10-12采用 **PaddleOCR-VL-1.6 完整文档解析流水线（PP-DocLayoutV3 + 0.9B VL）+ Qwen3.5-9B**。前者识别文档图像及表格结构，后者随后负责业务语义、字段关联和工具选择。PP-OCRv6是文字检测/识别模型系列；PP-StructureV3是组合解析流水线；VL-1.6是视觉语言文档解析方案，版本号不能直接比较大小。本项目未实测Structure或v6，因此不声称VL在本项目已比较胜出。

使用完整流水线进行版面检测和区域识别，不把整页直接交给单独VLM并当作带位置的解析结果。复杂表格、扫描件和字段附近的图像关系是选择VL的理由；实际准确性还需要独立材料评测。可直接读取的文本PDF与Excel继续优先原生解析。Qwen正常路径使用带来源和结构的片段；必要时可再设计原图/裁剪复核工具，当前尚未实现。

官方依据：[完整流水线与部署](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.en.md)、[VL-1.6说明](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL-1.6.en.md)、[PP-OCR系列](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md)。官方榜单成绩不代表本项目识别或填报准确率。

已完成独立服务部署、WSL客户端、统一启动/状态脚本及合成图片/扫描PDF接通验证。最终服务连续3次PNG与2次扫描PDF成功，耗时2.52–4.84秒；同一内容的姓名、护照号码、3×3表格内容与行列关系匹配，区域边界通过核验。它们是同一虚构内容的两种表示和重复请求，不能计作5份独立评测数据。测试PDF无文字层，已渲染检查；答案未经过独立人工转录。实际报告见[ocr-service-report.json](ocr-service-report.json)，原始响应位于被Git忽略的runs/ocr-smoke-20261012/。

**尚未接入ParsedDocument及填报CLI，尚未实现Qwen语义映射、工具回路或表单写回。** 现有15组UTF-8开发任务和历史Qwen提取成绩保持原含义。

## 部署位置与独立环境

服务器/data/zhuqianshun_data/server下：

~~~text
start-smartfill.sh
status-smartfill.sh
stop-smartfill.sh
qwen3.5-9b/                    # 原Qwen服务
paddleocr-vl/
  env/                        # OCR独立Python依赖
  runtime/python/             # 独立解释器副本
  models/PP-DocLayoutV3/
  models/PaddleOCR-VL-1.6/
  cache/ tmp/ config/ logs/ state/
  ocr-server.py
  ocr-environment.sh
  serve-ocr.sh
  install-ocr-environment.sh
  download-ocr-models.py
  requirements-ocr.lock
~~~

实际依赖：Python 3.12.14、paddleocr 3.7.0、paddlex 3.7.2、paddlepaddle-gpu 3.2.1（CUDA 12.6构建）；114个包通过uv pip check。锁文件为[requirements-ocr.lock](requirements-ocr.lock)。解释器初次从已有Qwen托管Python复制，此后使用独立副本，不向Qwen或系统环境混装依赖。缓存、临时文件、日志和权重均在OCR目录内，不修改HOME或全局网络设置。

两份模型从官方BOS HTTPS归档下载。state/model-source.json保存来源URL、大小、归档和文件SHA-256；这是本地完整性记录，未取得发布方公布的摘要，不能声称与发布方SHA比对通过。服务器DNS不稳定时，下载脚本支持SMARTFILL_DOWNLOAD_IP供curl --resolve使用，保留域名TLS校验；不改系统hosts。安装时临时使用SSH转发的已有代理，运行时不依赖该代理。

## 启动、查看与停止

在已经SSH登录的服务器运行：

~~~bash
cd /data/zhuqianshun_data/server
bash ./start-smartfill.sh
bash ./status-smartfill.sh
~~~

统一入口复用已READY的服务，缺少的服务使用各自目录的启动脚本。已实测复用路径：Qwen原主进程1113117保持不变，OCR最终进程2036137；本轮没有重启Qwen或停止其他应用。Qwen和OCR均只监听服务器127.0.0.1，端口分别18000和18001。READY只表示模型加载和接口返回正常；实际解析另行验证。本轮未同时关闭再冷启动两项服务。

需要主动停止两项服务时，在服务器执行：

~~~bash
bash /data/zhuqianshun_data/server/stop-smartfill.sh
~~~

停止脚本校验本项目根目录进程身份后发送SIGTERM，不按模型名批量杀进程；本轮仅做脚本静态检查，没有实际执行联合停止。服务器重启后需手动统一启动，未设置系统自启动。

持续查看：

~~~bash
tail -f /data/zhuqianshun_data/server/paddleocr-vl/logs/ocr-server.log
watch -n 2 nvidia-smi -i 3
~~~

默认使用GPU 3，单请求并发，CPU计算线程4、nice=10；启动检查空闲显存至少12000MiB。显存分配设置naive_best_fit、初始10240MiB、增长1024MiB、Paddle限制12288MiB。此设置不是硬件隔离配额，实际占用须看进程。最终快照OCR进程6746MiB、Qwen引擎24850MiB；GPU 3还有其他用户任务，不能把整卡占用或利用率归为本项目。共享GPU仍会有资源影响。

原auto_growth配置虽然能加载模型，但真实请求多次在embedding位置超时。根据[上游同类报告](https://github.com/PaddlePaddle/PaddleOCR/issues/17693)更换分配策略后，本机重复测试恢复。报告中的环境与症状相似，不等于已独立证明底层根因或上游问题普遍修复；需扩大样本和长期回归。客户端超时不会强制终止服务端原生推理；若health长期busy且无完成日志，先记录诊断，仅核验并重启本项目OCR进程。不要重复堆积请求。官方提供独立VLM推理后端部署路径，可在后续吞吐或稳定性需求明确时验证。

## WSL调用

已有Qwen转发时，只增加OCR转发。在WSL另一个终端执行并保持打开：

~~~bash
ssh -N -L 127.0.0.1:18001:127.0.0.1:18001 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 zhuqianshun@10.200.10.247
~~~

没有任何转发时可在同一个SSH命令同时加-L 127.0.0.1:18000:127.0.0.1:18000。已经占用的本地端口不要重复建立。SSH/WSL关闭后需重建转发，服务不会因此停止。

在项目根运行客户端，输出文件必须不存在：

~~~bash
cd /home/user773/multimodal_agent
.venv/bin/python scripts/parse-document.py /绝对路径/材料.pdf --output runs/ocr-example.json
~~~

支持PNG/JPEG/PDF；解码文件最多20MiB，PDF最多10页，每页144DPI后最多1200万像素。单区域输出上限1024 tokens，密集表格可能截断；不能把返回成功理解为全部内容完整。服务繁忙返回429；客户端默认超时180秒，不自动重试。接口只接受file_type和file_base64，不接受任意服务器文件路径。客户端核对结果SHA-256对应上传字节并拒绝覆盖现有输出。

输出保留原文件SHA-256、页码、页图像素尺寸、PDF点尺寸/渲染比例、官方原始JSON及Markdown。坐标为返回页图左上角像素坐标，PDF按每点2像素渲染。表格保留HTML行列和表格区域bbox；本次结果没有单元格bbox，table的block_order为null，应保留缺失值，不由模型猜造。其他区域保留模型给出的block_id、block_order和多边形。

VL识别来源应记录origin=vlm，原生解析origin=parser；后续Qwen理解不会改变原始来源类型。模型没有返回经校准的文字识别置信度，不补造分数；整份输出verification_required=true。坐标关联和引用一致性不能证明识字正确。

当前关闭页面方向分类、去畸变、图表、印章识别；不声称支持其完整能力。后续先扩展独立扫描材料，再做ParsedDocument适配与物理来源核验。

## 重建与验证

将项目scripts/中的OCR脚本复制到新的paddleocr-vl根目录，将docs/requirements-ocr.lock复制为该目录requirements-ocr.lock；三个smartfill启停/状态脚本放到父server目录。安装脚本依赖现有uv及旁边Qwen的托管Python来源，适用于当前服务器布局，不能当作任意服务器的一键安装器。

依次运行bash install-ocr-environment.sh、env/bin/python download-ocr-models.py，再从父目录统一启动。安装与下载脚本持有服务锁；已验证OCR运行时拒绝改变环境或模型文件。

本轮完整170项pytest通过，含11项无GPU的OCR上传/PDF渲染边界检查；最终5次真实解析、2项实际HTTP 400检查、部署脚本语法检查及服务复用/状态检查通过。无需为纯文档更新重跑历史Qwen批量提取实验。
