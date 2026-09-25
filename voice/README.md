# Iron_Jump 语音首版

豆包 ASR 2.0 → Pipecat → Qt 业务路由 → 豆包 TTS 2.0 → 扬声器。
控制指令直接调用 SessionController；配置与报告复用现有 DeepSeek Agent。
本版中的“豆包回应”指豆包语音合成，沿用用户提供的 ChatGPT 对话架构，没有替换现有 LLM。

2026-09-16 已完成本地 API Key 配置和真实 ASR/TTS 云端回环，开始/暂停/继续/结束四项通过。
详细结果见 `docs/gait_voice_validation.md`。真实麦克风、实际播音、应用内现场延迟与 Windows 设备仍待验收；
离线测试和合成音频回环不能替代这些现场验证。

## 安装与开启

在运行 Iron_Jump 的 Python 3.11+ 环境中执行：

```sh
python -m pip install -r requirements.txt -r requirements-voice.txt
python -m nltk.downloader punkt_tab
python -m voice --devices
python -m voice --check
python ui/main_window.py
```

把 `voice/env.example` 中的语音配置追加到现有 `.env`。不要覆盖已有 LLM 配置。
新版语音控制台的 API Key 与方舟/DeepSeek Key 不通用；ASR 与 TTS 可分别配置。
资源 ID 应匹配已开通的小时版或并发版；音色应是账号可用的 TTS 2.0 音色。
环境变量优先于 `.env`。密钥不会写入 IPC 或显示在日志中。
Pipecat 启动会预热 NLTK；提前安装 `punkt_tab`，也可用 `NLTK_DATA` 指向已经安装的数据目录。
若缺少该数据，本版会在打开麦克风前提示安装，不让首次使用卡在隐式下载。

点击窗口右下角“开启语音”。只有主动开启才访问麦克风并把音频发送至火山语音服务。
识别结果、文字回应和延迟指标显示在语音面板。关闭语音或关闭窗口会释放音频设备与网络连接。
没安装可选依赖或没配 Key 时，原有手动测试不受影响。

已默认启用本地 WebRTC AEC3 和适度降噪，关闭自动增益。语音面板连接成功后会显示 AEC3 已启用。
使用一个 24 kHz、10 ms 帧的双向音频流，以实际送往声卡的 PCM（含静音）为参考；
根据声卡 ADC/DAC 时间戳提供延迟，清理后的麦克风音频连续重采样为 16 kHz 送给 ASR。
打断时丢弃未播放音频，保留已播放部分的 AEC 历史，以继续消除房间尾音。
没有原生依赖时明确报错，不会静默回退到无 AEC 的采集。
不同声卡、外放音量与房间仍需实测；耳机可作为故障排查时的对照。
PortAudio 设备不可用时检查系统麦克风权限，或用 `--devices` 指定设备。

## 完整操作顺序

1. 配置页选择测试身份、测试类型，打开语音。
2. 说“帮我配置连续纵跳十次”。立即播报正在生成建议；结果由现有 Agent 校验后显示。
3. 查看建议，说“确认配置”。实际应用后播报确认。
4. 说“准备测试”。进入设备准备页，等待设备连接。
5. 说“开始”。采集启动确认后播报“测试已开始”。
6. 说“暂停”。引擎冻结处理与计时，回传执行信号后播报“测试已暂停”。
7. 说“继续”。引擎恢复计时与处理，回传后播报“测试已继续”。
8. 说“结束”。停止采集、生成报告、跳转报告页后播报；自动达标结束也播报。
9. 说“分析报告”。复用当前报告的权限范围、分析服务和校验结果，播报主要结论及限制。
10. 说“返回配置”开始下一轮。运行中不能直接返回配置。

跑步机步态报告页还可以直接问“左右脚差异怎么样”“步频稳定吗”“前后半程有什么变化”
或“哪些数据没算进去”，再追问“具体证据呢”。这些专项问题使用本地确定性计算，
完整回答同步显示在“步态专项问答”页，点击证据编号可定位逐步/周期明细。
切换报告会清除追问上下文。专项问答不需要调用 LLM；语音输入和播报仍需 ASR/TTS 服务。

开始/暂停/继续/结束不经过 LLM。重复指令不会反向切换；状态不符、设备错误、确认超时都有明确文字和语音反馈。
只执行 ASR 的 definite 最终分句；partial 用于显示和判断插话。明确的控制指令可立即打断；
普通插话需至少 4 个字符、连续两次前缀一致的临时结果，或等待最终结果，避免短杂音触发打断。
按分句时间去重，同一句话再次说仍可识别。
音频输出阶段记录近期播报文本，过滤与其一致的识别片段及短暂尾音；这是文本回声过滤，
它仅作为 AEC3 之外的补充。为保留紧急控制，明确的开始/暂停/停止等命令不被文本过滤。
“不要开始”“暂停测试这个功能是怎么实现的”不会命中控制路由。
说话打断后清除旧音频并取消当前合成任务；旧 Agent 工作仍可完成，但其过期语音回复被丢弃。
配置建议仍需单独确认才能应用，ASR 未理解的长句不会直接操作设备。

## 验证

AEC 离线验证：`python -m pytest -q tests/test_voice_aec.py`。
本机声学验证前先关闭其他语音窗口，在安静环境运行：

```sh
python -m voice.aec_probe tests/fixtures/voice/tts_start.wav
```

此命令会外放测试语音并使用麦克风约 12 秒，只在内存中计算，不保存或上传录音。
输出的能量下降包含降噪效果，不等同严格的纯回声 ERLE，更不能代替真人插话测试。
随后重开演示语音，分别验证安静时不自问自答、外放期间说“暂停”能执行、播报后正常对话。

```sh
QT_QPA_PLATFORM=offscreen python -m pytest -q \
  tests/test_voice_protocol.py tests/test_voice_clients.py \
  tests/test_voice_pipeline.py tests/test_voice_session.py
```

- 协议测试检查官方二进制头、负序号尾包、分句去重、TTS 连接/会话事件和异常包。
- Pipecat 测试运行真实 PipelineWorker，使用合成服务替身检查流式音频、播报取消、清空旧音频、语气词和过期回复。
- Qt 测试用真实 SessionController/GaitEngine 与模拟 USB，验证开始、暂停、继续、结束、报告跳转及配置确认。

配置有效 Key 后可运行真实云端回环，会调用收费的 ASR/TTS API，发送四条合成指令音频，不操作 USB：

```sh
python -m voice.smoke --output-dir /tmp/ironjump-voice-smoke
```

逐项核对识别文本与命令，并保存 WAV 供试听。该回环验证云端接入，不代表真实麦克风识别率或扬声器播放成功。
最终现场验收需用真实麦克风与测试设备重复完整操作，另检查播报中插话、断网、无权限、设备未连接、自动结束和关闭窗口。
运行中网络断开会停止语音进程，保留手动控制；不会自动重放命令或自动重连采集。

日志中的控制延迟为“最终识别文本到引擎执行确认”，TTS 首包延迟为“发起合成到音频首包”。
两者均不等于口头指令到扬声器实际发声的端到端延迟；云端回环另记录从音频发送开始到最终识别的时间。

## 参考

- 用户提供的 ChatGPT“其他项目”对话：规则控制路由、执行成功后确认、保留 DeepSeek 配置/报告 Agent、Pipecat 管理打断。
- [双向流式 ASR 2.0](https://docs.volcengine.com/docs/6561/2630027?lang=zh)：`bigmodel_async`、`volc.seedasr.sauc.duration`、新版 `X-Api-Key`。
- [V3 双向流式 TTS](https://docs.volcengine.com/docs/6561/2532486?lang=zh)：`tts/bidirection`、`seed-tts-2.0`、PCM 24 kHz。
- [Pipecat](https://github.com/pipecat-ai/pipecat)：固定 `1.9.0`，独立进程运行，Qt 通过 JSON 行消息桥接。
