# 已将一处OpenCV内部GIL等待精确对应到NumPy数组创建路径

承接 `0befc72`，本轮只用旧CPU/等待记录、精确PE静态检查及无图像运算的新进程只读指针检查。没有新增采集/GUI/模型/人体/USB/Run/优化A/B窗口，没有修改正式程序或原NumPy。尚未验证任何缓存/预分配候选。

## 原生工作与公开调用边界

同一旧CPU PID11948的扩展记录中，GUI TID20448和另一个TID14312的闭合、IP匹配链均包含独立核验的cv2.resize公开入口；TID12820包含cv2.imdecode。其他几个原生线程没有Python公开调用边界，继续不命名业务线程。

精确OpenCV PE/SHA与异常表核验表明：TID13080的IP与GUI resize链内IP处于同一私有运行时函数范围0x25d4ca0～0x25d5b72；TID7916/22184与TID14312 resize链内IP处于另一范围0x25dc290～0x25dc812。指令为像素访存/寄存器数值路径中的movzbl、movd等，不是仅因模块叫cv2而命名算子。共享代码范围不能证明它们属于同一个同时resize任务，也不能唯一绑定正式GUI还是模型源调用。

`test_public_paths.py`确认仅精确模块、半开入口范围才匹配，未落入入口的原生worker不会被补上Python调用者。加上前次3项角色测试，共5项通过。

## GIL等待进入点的更强身份依据

旧已保留的三类等待见证（PID17752，imdecode TID13080，resize/cvtColor TID20420）包含：匹配PDB的低层等待、take_gil、PyGILState_Ensure，以及cv2.pyd返回RVA0x1ea260d。

当前精确PE的AMD64异常表将该返回点置于唯一范围0x1ea2580～0x1ea2876。没有采用objdump的邻近PyInit_cv2标签，也不把它声明为匹配PDB符号。

该范围的错误分支直接以参数指向内嵌字符串：

- 函数标识：`NumpyAllocator::allocate`。
- 编译源标识：`modules\python\src2\cv2_numpy.cpp`，错误行46。
- 错误文本：`The numpy array of typenum=%d, ndims=%d can not be created`。

这是本范围内编译器源上下文，不是私有PDB函数匹配；即使存在内联，也只按已核对的源码路径标识陈述。

## 实际C API表与参数核对

新建的无设备进程只import原cv2/NumPy并读本进程已加载模块和函数表，不调用resize/cvtColor/imdecode/flip或模型：

1. 精确cv2.pyd仍是 `ae833b9b5771f5932200bd3b8ad0f483f4fbec92cbdbd26d21d38fe524c60e66`，原NumPy pyd仍是 `4fb4c5d62a6bd766eea716350eaf5396580e33cf7dc159e305488d1b7d72dad2`。
2. 机器码在RVA0x1ea276e读取的全局指针（RVA0x68ed630）与NumPy `_ARRAY_API` capsule地址相同。
3. 类型槽2等于实际 `numpy.ndarray` 类型地址；函数槽93由精确安装头文件确认是公开C API `PyArray_New`，实际指针RVA0xcddf0位于精确NumPy映像的可执行.text节。
4. RIP/IAT的GIL入口/出口目标分别等于实际CPython `PyGILState_Ensure` / `PyGILState_Release` 地址；array构造调用位于RVA0x1ea27a7，介于两者之间。
5. 从r11d置零到构造调用没有中间调用，静态参数流显示strides、external data、obj等参数为NULL，类型参数取实际PyArray_Type槽。这是NumPy-backed数组创建路径，不只是泛指“OpenCV可能在分配”。

第一次读取附带的文件长度范围只是宽泛约束，不用于身份证明；独立validate_array_identity按真实SizeOfImage和可执行节再次核验。原输出保留，精确校验见array_identity_validation01.json。

因此，现在能更具体陈述：**这些现场等待链的一处GIL进入点位于OpenCV的NumPy数组创建路径、调用PyArray_New之前。** 这仍是等待者位置，未识别持有者；不能说allocator长时间持有GIL、数组创建消耗了某个CPU占比，或这就是首窗主因。

## 对根因与修复的边界

已有模型open、首调用和独立串行CPU账本说明慢态范围更广，不由这一分配边界独自解释。即便以后检查dst/预分配，也必须先核验实际数组创建路径是否消失、返回/完整像素与模型结果、异常及跨线程生命周期；“返回同一个dst对象”本身不足以证明没有内部临时分配。当前没有实施或运行该优化。

旧全局CPU/等待栈失败、3%/1%扰动失败及所有原始窗口不变。未知内核/内部函数保留原模块、SHA、RVA和原始地址。根因贡献和正式修复仍未完成；本阶段不需要真人测试。
