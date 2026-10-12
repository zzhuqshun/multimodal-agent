# WSL框架与独立Qwen服务

## 目录与职责

WSL项目/home/user773/multimodal_agent保存代码、任务数据、规则、评测和运行结果。模型权重和推理环境独立放在用户指定服务器目录的qwen3.5-9b子目录；已有sam3_server保留。

服务器目录结构如下：

```text
/data/zhuqianshun_data/server/qwen3.5-9b/
  env/                       # 本服务独立Python环境
  runtime/python/            # 本服务使用的托管Python解释器
  models/Qwen3.5-9B/          # 权重、分词器、视觉处理配置
  cache/                     # uv、HF、vLLM、CUDA、Triton等缓存
  tmp/                       # 临时文件
  logs/                      # 安装、下载、推理日志
  state/                     # 文件来源/哈希、依赖版本、PID及完成标记
  requirements-server.lock   # 固定实际安装依赖
  install-environment.sh
  download-model.py
  serve-qwen.sh
```

所有新建模型专属环境、缓存、临时文件和日志都位于此目录。没有修改系统Python、驱动、已有应用环境、其他服务配置或全局网络配置；没有使用Docker部署。模型运行仍会消耗共享服务器的GPU、CPU、内存和磁盘资源，不能解释为完全没有资源影响。

## 已核实的环境及来源

2026-10-12通过SSH只读核验：服务器为Ubuntu 20.04.6、系统Python 3.8.10、NVIDIA驱动570.133.20、4张A100 80GB。指定/data目录可写，检查时约1.1TB可用；已有其他GPU任务。独立环境使用托管Python 3.12.14，不升级系统解释器。

模型ID为Qwen/Qwen3.5-9B，官方模型页标注Apache-2.0许可：[Qwen模型页](https://huggingface.co/Qwen/Qwen3.5-9B)。服务器直连Hugging Face失败，使用[Qwen官方ModelScope仓库](https://modelscope.cn/models/Qwen/Qwen3.5-9B)获取文件，逐文件固定源修订并校验公布的SHA-256；来源记录位于服务器state/model-source.json。

[vLLM Qwen3.5-9B部署说明](https://recipes.vllm.ai/Qwen/Qwen3.5-9B)列出0.17.0以上支持；[vLLM安装说明](https://docs.vllm.ai/en/v0.17.1/getting_started/installation/gpu/)要求结合CUDA/PyTorch构建选择独立环境。官方模型页仍提到main/nightly安装方式，因此文档建议不能替代本机加载测试。实际环境以服务器state/requirements-server.lock和本项目核验报告为准。

## 启动与资源范围

scripts/serve-qwen.sh是服务器启动脚本的源码副本，复制到上述模型根目录使用。它以前台方式运行，日志需要由调用方重定向到该目录logs/。

启动前检查本服务锁、模型/依赖完成标记、选定GPU空闲显存及利用率、127.0.0.1:18000端口；不满足时退出，不停止其他进程。默认GPU索引3，也可通过SMARTFILL_GPU_INDEX指定；使用PCI顺序的数字CUDA索引，并比较实际GPU UUID与所选nvidia-smi设备；不一致则退出。固定的vLLM 0.17.1启动路径不接受CUDA_VISIBLE_DEVICES中的UUID字符串。空闲检查是启动时快照，不是GPU排他调度。

最终配置为单卡BF16、8192上下文、单并发、gpu-memory-utilization=0.32、eager执行；OpenMP/MKL线程数4、编译并行上限2，进程nice=10。0.32是服务的显存规划参数，不是硬件隔离配额；实际占用须看nvidia-smi。每次请求最多1张图片，视频关闭。该配置用于小规模接通验证，不能代表完整上下文能力或吞吐性能。

当前环境已完成安装，无需重复安装。重建时将scripts/install-qwen-environment.sh、download-qwen-model.py、serve-qwen.sh及docs/requirements-server.lock复制到新的模型根目录，分别使用install-environment.sh、download-model.py、serve-qwen.sh、requirements-server.lock文件名；先运行安装脚本，再用该目录env/bin/python运行下载脚本，最后启动服务。安装脚本持有服务锁，服务运行期间拒绝改变环境；下载脚本复用已记录的固定文件修订，坏哈希不发布为正式模型文件。所有操作使用该目录环境，WSL框架不安装GPU依赖。

启动示例在服务器执行：

```bash
cd /data/zhuqianshun_data/server/qwen3.5-9b
SMARTFILL_GPU_INDEX=3 nohup bash ./serve-qwen.sh > logs/vllm-server.log 2>&1 < /dev/null &
tail -f logs/vllm-server.log
```

state/service.pid保存本服务主进程PID。需要停止时先核对PID的命令行确实是本目录服务，再发送SIGTERM；不要使用按模型名匹配的批量kill。当前不设置系统自启动，不占用已有应用端口。

## WSL连接与检查

服务只监听服务器127.0.0.1:18000，由SSH本地转发访问。重新建立连接时，在WSL终端用自己的SSH连接信息执行：

```bash
ssh -N -L 127.0.0.1:18000:127.0.0.1:18000 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 用户名@服务器地址
```

非默认SSH端口加-p。终端保持打开；WSL关闭或SSH断开后需重建。当前会话建立的转发进程信息在项目runs/server-runtime/，不保存密码；模型服务与转发的生命周期独立。

WSL项目.env.example给出本地转发地址和served model ID；CLI只读取已导出的环境变量，不自动执行.env。确认自己的.env内容后：

```bash
cd /home/user773/multimodal_agent
set -a
source .env
set +a
.venv/bin/python -m smartfill check-model
```

check-model先请求/v1/models确认配置的模型ID，再发送固定文字探针；不读取任何任务、答案或标注文件。记录实际耗时及服务返回的token用量，缺失用量保留null。拒绝HTTP重定向，HTTP错误不打印响应体，非法结构/截断回答/超时视为失败。URL、模型名、API密钥和超时由环境提供，密钥不进入日志或Git；localhost SSH转发模式下当前无需API密钥。

## 验证范围与后续

完整121项测试通过，其中18项模型HTTP检查、3项下载保护检查。HTTP检查覆盖成功、有/无usage、401/500、重定向、非法JSON、模型ID不匹配、截断回答、超时和非法配置；下载检查覆盖固定修订、坏哈希拒绝、正确文件复用及错误目录拒绝。

真实服务已完成初始与降低显存后的两轮文字/图片验证，共4次chat请求；文字正确返回SMARTFILL_OK，图片正确回答red。最终GPU 3快照占用25312MiB，空闲55842MiB；模型目录磁盘占用约28GiB（包含硬链接缓存的du统计）。当前服务使用Python 3.12.14、vLLM 0.17.1、PyTorch 2.10.0+cu128、Transformers 4.57.6。15个模型文件共19329314298字节通过SHA-256核验，含4个权重分片。

实际报告见[服务器连通报告](server-connection-report.json)，包含初始及最终配置探针的原始耗时和token用量。首次调用及重启后的调用可能包含运行时预热；这4次探针不能代表稳定吞吐。主要缓存/临时目录已从本服务进程环境的白名单变量核验，都位于模型根目录。

此阶段负责部署与连通，尚未实现Qwen自动填报适配，也未用模型运行15组开发任务。下一阶段将可见输入与答案严格分开，生成符合现有契约的模型预测，再使用相同独立评测器与规则基线比较。图片探针仅确认接口可接收图片，不等同于OCR或业务表单准确率验证。
