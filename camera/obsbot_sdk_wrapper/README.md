# OBSBOT C API wrapper — 当前状态

## 独立二维云台验证分支（2026-10-08）

分支：`codex/tinyse-mediapipe-gimbal-validation`，从 `cc0bc7f` 建立。
本试验不接入正式 UI，也不包含原工作目录中的未提交改动。

新增 `obsbot_set_gimbal_speed(index, pitch, pan)` 和
`obsbot_get_gimbal_angles(index, angles)`；需先按下方命令重新编译 wrapper。
Python 验证入口直接复用 DirectShow 原始采集与 MediaPipe 关键点适配器。

在该分支的 Windows 目录中，先关闭其他相机预览和测量，再运行：

```powershell
# 30 / 60 两档水平速度对比，每次 0.3 秒，正反方向各一次；再验证俯仰。
python -m tools.tinyse_gimbal_validator --mode pulse --pulse-pan 60

# 根据脉冲测试确认两个轴的正方向后，验证 MediaPipe 跟踪。
python -m tools.tinyse_gimbal_validator --mode track --duration 60
```

跟踪默认 `pan_gain=240`、`pitch_gain=80`，水平响应为俯仰的 3 倍；
速度上限分别为 90 和 30（SDK 输入值，不代表已测得的实际转速）。
使用 `--pan-gain` / `--pan-max` 单独提高水平响应或上限；
方向不正确时使用 `--pan-sign -1` 或 `--pitch-sign 1` 修正。
坐标取自未镜像原图。屏幕中央 6% 死区内停止，目标使用髋、膝、踝包围范围的中心，
任一必要关键点质量不足时停止。独立控制线程在图像结果超过 250 ms 未更新时停止；
退出时也发送停止指令。SDK 自身阻塞时无法保证及时停止，工具会报告此限制。

工具启动时关闭相机内置 AI，退出后保持关闭；需要时在正式程序中重新激活 AI 跟随。
`track` 模式按 Q / Esc 或 Ctrl+C 退出；`--no-preview` 用于无界面记录。
每次输出到独立 `exports/tinyse_gimbal_*`，保存原始 MJPEG / CSV、命令日志、
采集帧率、录制丢帧、角度反馈和脉冲前后截图。
`hardware_motion_verified` 默认保持 false：须结合截图/录像核对运动方向，
再结合角度变化量与时长比较快慢，不能把 SDK 返回 0 当成实机通过。

离线控制测试：`python -m pytest -q tests/test_gimbal_tracking.py`。

本轮验证记录：
- macOS：控制与 DirectShow 适配测试共 22 项通过；原生 C++ 动态库编译通过，
  7 项 C ABI 非法输入/无设备检查通过（未发送硬件命令）。
- Windows 独立目录：`C:/Users/86150/TinySE-gimbal-validation-20261008`；
  使用 `D:/conda/envs/pydantic_ai/python.exe`，19 项控制测试通过。
- Windows 构建未完成：CMake 未检测到 Visual Studio；Qt 自带 clang-cl
  编译报 `algorithm file not found`，缺少完整 MSVC C++ 标准库/开发环境。
  尚未生成新的 Windows wrapper DLL，尚未发送实机转动指令，
  水平速度提升、方向和采集并行稳定性均待实测。

## 目标

用 C wrapper DLL 桥接 OBSBOT C++ SDK，使 Python ctypes 可调用设备控制 API。
核心原理：STL 类型（`std::string`/`std::vector`/`std::shared_ptr`）留在 C++ 侧，
对外暴露纯 C 结构体和函数。

## 编译环境

已安装并验证可用：

| 工具 | 路径 |
|------|------|
| cmake 4.3.2 | `C:\Program Files\CMake\bin\cmake.exe` |
| MSVC 19.44 | `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe` |
| Windows SDK | 10.0.26100.0 |

激活环境：
```cmd
"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
```

编译命令：
```powershell
cmake -S camera\obsbot_sdk_wrapper -B camera\obsbot_sdk_wrapper\build -G "Visual Studio 17 2022" -A x64
cmake --build camera\obsbot_sdk_wrapper\build --config Release
```

运行产物输出到：`camera\bin\obsbot_c_api.dll`（含 `libdev.dll` + `w32-pthreads.dll`）

## 代码结构

```
obsbot_sdk_wrapper/
├── obsbot_c_api.h       # C 头文件：结构体 + 函数声明
├── obsbot_c_api.cpp     # 实现：g_devices 缓存 + C↔C++ 桥接
├── CMakeLists.txt       # 构建配置
└── README.md            # 你正在看的这个文件
```

## 关键实现细节（已踩坑修复）

### obsbot_refresh_devices 时序

**修复前**：先 sleep，再调 `Devices::get()`。但 `Devices::get()` 才触发设备检测线程，导致 sleep 期间什么都没发生。

**修复后**（`obsbot_c_api.cpp:48-61`）：
```cpp
Devices::get();  // 先触发检测线程
sleep(wait_ms);  // 等待线程完成
auto list = Devices::get().getDevList();  // 获取结果
```

### 其他函数

- `obsbot_get_device_info(index)` — 用 `g_devices[index]` 缓存，按索引取设备信息
- `obsbot_get_video_formats(index)` — 填 C 数组，返回总数
- `obsbot_set_record_encode_param(index)` — 直接透传 `DevMediaEncodeParam`
- `obsbot_get_record_encode_param(index)` — 读回参数（Tiny SE 上此函数返回 -1，可能不支持）

## Python 测试脚本

测试脚本：`camera/test_wrapper.py`

工作方式：
1. `obsbot_refresh_devices(5000)` — 5 秒等检测
2. `obsbot_get_device_info(0)` — 获取 SN/名称/固件版本/产品类型
3. `obsbot_get_video_formats(0)` — 列出设备支持的格式
4. `obsbot_set_record_encode_param(0, fps=100)` — 尝试设置 100fps

## Tiny SE 实测结果（2026-04-30）

### 设备信息

| 项 | 值 |
|----|-----|
| SN | RMOWCYHA081RCB |
| Name | OBSBOT_RMOWCYHA081RCB |
| Version | 6.4.3.4 |
| ProductType | 12 (TinySE) |
| DevMode | 0 (UVC) |
| VideoFriendlyName | OBSBOT Tiny SE StreamCamera |

### videoFormatInfo（共 4 个格式）

| 分辨率 | 帧率范围 | 编码 |
|--------|---------|------|
| **1920×1080** | **[15, 100]** | **MJPEG** |
| 1280×720 | [15, 120] | MJPEG |
| 640×360 | [15, 30] | YUY2 |
| 640×480 | [15, 30] | YUY2 |

**关键结论：Tiny SE 硬件支持 1080p@100fps MJPEG。**

### set_record_encode_param(fps=100)

- 返回 `0` (OK) — **SDK 接受了 100fps 参数**
- 但 `get_record_encode_param` 返回 `-1` (ERR) — Tiny SE 可能不支持此 getter，或参数未实际写入

## 未完成：验证 UVC 实际输出

SDK 设完 fps 后，需要验证 UVC 端实际输出是否变为 1080p@100fps。

已知障碍：
- OpenCV DSHOW 后端：设 FOURCC 会卡死 Tiny SE 驱动
- OpenCV MSMF 后端：Tiny SE 打不开
- OpenCV DSHOW 默认模式：640×480 @ 1fps（极不稳定）

**建议尝试路径**：
1. SDK 设完 fps=100 后 → OpenCV DSHOW 打开，**不设 FOURCC/宽高/帧率**，只 `cap.read()` 测实测帧率和分辨率
2. 如果 DSHOW 仍崩 → 试 `cv2.CAP_ANY` 或 DSHOW 的 `cv2.CAP_PROP_MODE_RAW` 
3. 如果 OpenCV 完全不可用 → 考虑用 Windows Media Foundation API 直接拉流

## 环境

- Python: `D:/conda/envs/dayu/python.exe` (64-bit)
- OpenCV: 已安装，DSHOW/MSMF 后端均可用
- ctypes: 标准库
- SDK DLL: `camera/sdk/libdev_v2.1.0_8/windows/win64-release/libdev.dll`
