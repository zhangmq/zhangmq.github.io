---
layout: post
lang: zh-CN
title: "Linux 视频播放器里的实时 AI 超分"
date: 2026-08-18 12:00:00 +0800
categories: ai
tags: [mpv, cuda, tensorrt, rife]
permalink: /zh/2026/08/18/linux-ai-upscaling-player/
translation: /en/2026/08/18/linux-ai-upscaling-player/
description: VFX 超分和 RIFE 插帧是怎么接进 Linux 播放器的，整条管线又是怎么搬到 GPU 上的。
---

> [English](/en/2026/08/18/linux-ai-upscaling-player/)

NVIDIA 的 RTX Video Super Resolution 是个好东西——老 720p 内容放出来能明显变清楚。可惜它在 Linux 上不存在：RTX VSR 背后的驱动级接口只开放给 Windows，我也没找到任何用底层 SDK 的 Linux 播放器。所以我就让 AI 编码代理写了一个。

这篇文章说三件事：AI 阶段（VFX 超分和 RIFE 插帧）是怎么接进播放器的、整条管线是怎么搬到 GPU 上的、以及扩展 mpv 视频管线时有哪些坑。项目本身是基于 libmpv + Qt 6/QML 的 Linux 桌面播放器，开源（GPLv2+），代码在 [github.com/zhangmq/vsr-player](https://github.com/zhangmq/vsr-player)。

## AI 跑在哪：自定义 mpv 视频滤镜

mpv 本身支持用户滤镜，但我们的滤镜要在构建时链接 VFX SDK 和 TensorRT，所以直接编进了打过补丁的 mpv。仓库里保留一份纯净的 mpv 0.41 源码当基座，另开一个 `src/mpv/` 覆盖层目录，只放改动过的文件，构建脚本负责合并——这就是 patch 方案：升级和对比 diff 都干净。

```
demux → decode → [vf_hwup] → [vf_rife] → [vf_vsr] → VO (libmpv) → Qt 场景图
                  ↑            ↑             ↑
             SW→CUDA 上传   RIFE (TRT)    VFX SDK + CUDA
```

三个自定义滤镜：

- `vf_hwup` —— 软解帧上传到 CUDA，下游滤镜从此只见到硬件帧
- `vf_rife` —— RIFE 插帧（TensorRT），在源分辨率上做，超分之前
- `vf_vsr` —— CUDA + VFX SDK 超分

**mpv 是怎么驱动滤镜的（最容易踩坑的地方）。** mpv 滤镜是 pull 模型：管线反复调用滤镜的 process 函数，每次调用**至多**出一帧——没帧可出就返回 NULL，管线过会儿再问。对插帧这类滤镜，这一点决定了全部设计：你得维护一个内部就绪队列，process 里每次弹出一帧，PTS 自己显式设置。没有 push 接口，也不会一次性塞给你一批帧——帧必须扣在手里，攒够一对才能插值，所以滤镜自己持有小的 lookahead 缓冲，EOF 时还得处理 flush。

另一条约定：mpv 里每帧都是 `mp_image`，plane 引用计数，色彩参数（colorspace、levels、transfer）挂在帧上。滤镜必须尊重所有权——帧入队就持有引用（talloc ref），输出时移交所有权。这块弄错了不会当场报错，而是在 teardown 时以 double-free 或 canary assert 的形式爆出来。

## VSR 接入

`vf_vsr` 吃硬件帧（NV12/P010，8 或 10 bit），吐出超分后的 RGBA 帧。

VFX SDK 是个走 `dlopen` 的 C API（项目不链接它——SDK 自带的 TensorRT 10 绝不能进我们的链接命名空间，后面细说）。播放器整个生命周期只建一个 VFX 会话（`NvVFX_CreateEffect("VideoSuperRes")`），每次加载文件时配置：绑定输入/输出 RGBA buffer、设质量等级（`SetU32("QualityLevel", …)`）。

每帧的流程：

1. YUV → RGBA 转换（为什么放在 GPU 上做，见"把整条管线搬到 GPU 上"一节）。
2. RGBA 帧推进会话的输入 buffer，在共享 CUDA 流上执行。
3. 输出 buffer 拷进滤镜自己的 buffer（一次 D2D 拷贝，pitch 归滤镜管）再包成 `mp_image`（RGBA、full range）。

两个值得注意的细节：

- **色彩元数据必须跟着帧走。** 转换矩阵/range 取自 `mp_image` 的色彩参数（BT.601/709/2020、limited/full），容器没声明就按分辨率猜。VFX 模型期望输入一致；喂错颜色空间，效果就是"能跑，但颜色莫名不对"。
- **尺寸变化是热更新，不是重建。** 只要输入尺寸不变，会话就一直活着：输出尺寸变了只需重新绑定输出 buffer（`SetImage`）——全屏切换走的正是这条路。只有输入尺寸变了才销毁会话（换文件本来就要重建整条滤镜链，这种情况很少）。改质量只是一次 `SetU32`。

## RIFE 接入

RIFE 是神经网络插帧模型。我们的引擎是 RIFE 4.26 ONNX 编译出的 TensorRT 引擎，**动态 shape**（min 128×128、opt 1152×1920、max 2176×3840）——一个引擎文件通吃 4K 以内的所有分辨率。滤镜加载时读引擎 profile，分辨率一变只调 `setInputShape`；buffer 按 profile max 分配一次，之后永不移动。

模型输入 7 通道：`[imgA(RGB), imgB(RGB), t]`。滤镜做的事：

- 队列里持有当前源帧；下一帧到了就凑成一对
- 用自定义 CUDA 内核**直接在引擎的设备 buffer 里组装 7 通道输入**——引擎自己持有 `d_in`/`d_out` 设备指针，assemble 内核写 `d_in`（带 reflect pad），另一个内核读 `d_out` 生成输出 RGBA。全程在 GPU 上；插值器里唯一的 host 传输是每对一次的场景切换归约（几百个 float），没有任何整帧 H2D/D2H
- 按插值位置设 `t`（目标帧率超过源帧率时，每对源帧要产出多帧；整数倍率 ≥2 时 `t` 固定为 `i/k`，即 vs-mlrt 的 Interleave 约定），在共享 CUDA 流上 `enqueueV3`
- convert 内核还防御引擎的 NaN 输出（部分帧对会踩到模型的数值边界）：复制时间上更近的源像素，而不是输出黑帧

实际使用中还有几个值得注意的行为：

- **场景切换直通。** 帧对差异超过阈值（硬切）时，插值没有可用的运动信息——与其编一个不存在的混合帧，不如直接复制前一帧。vs-mlrt 生态也是这么干的。
- **优雅降级。** 每帧对的推理成本实测（一个滑动窗口），超过帧预算就把目标帧率逐档下调（60 → 48 → 40 → 30），全超了才直通。OSD 显示的是实际档位，不是请求的档位。
- **PTS 打内容时间——正确性的关键。** 输出的每一帧都带着它内容时间的 PTS：中间帧是 `t_prev + tval·(t_cur − t_prev)`，源帧副本在 `t_cur`。这样输出严格单调、无重复无空洞，任何源帧率都成立；每帧在它真实的时间点上显示（音频同步播放下，视频间隔严格等于源间隔/k，与音频时钟零漂移）。这很重要，因为 mpv 会拒绝时间戳不单调的帧：早先的绝对网格方案（`t0 + n/out_fps`，每对固定 k 帧）在源帧率不是网格整数倍时会错位——29.97→60（比例 2.002）就产出了重复和空洞的网格点，`Invalid video timestamp`、音画不同步、持续丢帧。内容时间没有网格可以错位。

## 把整条管线搬到 GPU 上

NVDEC 给你硬件帧、硬件 VO 负责输出——问题恰恰出在两者之间：VFX SDK 要的是 packed RGB，而本系统的 FFmpeg `scale_cuda` 缺半平面 YUV 内核（`CUDA_ERROR_NOT_FOUND`）。我们先用 CPU filter graph 起步（正确性验证过：相对 FFmpeg CLI 基线 46.5 dB PSNR），再用自研小内核（`yuv_to_rgba.c`，NVRTC）在 GPU 上直接做 NV12/P010→RGBA 取代它。每帧一次 CPU→GPU 往返，正是我们要消灭的。

**解码之后的一切现在都是纯 CUDA，分三步：**

1. **`vf_hwup`：全链唯一一次刻意为之的 H2D 拷贝。** 软解帧（任意 YUV）在 CPU 上转成 NV12/P010，用 `cuMemcpy2DAsync` H2D 上传（Y、UV 平面各一次，同一流）。这步免不了——软解帧本来就在 CPU 上。硬解帧原样直通。过了这个滤镜，之后每一帧都是 CUDA 帧。

2. **一个共享 CUDA 上下文，引用计数保活。** 整条链跑在同一个 CUDA 上下文上：硬解时用解码器的，软解时用 `vf_hwup` 自建的（下游滤镜借用）。上下文包在一个小引用计数结构里，塞进帧的 buffer opaque 数据，所以上下文比任何一个滤镜都活得久——包括输出帧比生产者活得久的场景（经典的 teardown double-free 靠数引用规避，而不是靠销毁顺序）。

3. **每一级交接都没有整帧拷贝。** `vf_hwup` 的上传 buffer 本身就是帧；YUV→RGBA 内核直接写 VFX 输入 buffer；VFX 输出 D2D 拷进滤镜自有 buffer 再包成 `mp_image`（pitch 归滤镜管，无需重排）；RIFE 的 assemble 内核直接写引擎 `d_in`，convert 内核生成输出帧。链内数据以引用、原地转换或 D2D 方式流转——从不经过主机。

**流纪律（血泪教训）。** 每个滤镜处理完只同步自己的 CUDA 流（`cuStreamSynchronize`），绝不设备级同步。设备级同步会连 VO 的 stream-0 拷贝一起等——这个死锁我们真踩过（VFX 销毁路径曾因渲染循环停滞永久卡在 `cuCtxSynchronize` 里，Xid 109 调试会话中观测到）。按流同步让滤镜彼此串行，同时永远不阻塞渲染侧。

全 GPU 化还带来一个好处：插值器的中间帧在**所有**输出位置都是 full-range RGBA，包括直通拷贝。如果某些帧是 limited-range NV12、另一些是 full-range RGBA，VO 每帧走不同的转换路径，画面就会闪。让整条链的输出保持一致不是审美问题，是正确性要求。

## 实测数据

RTX 5060 Ti、驱动 610、100 秒文件、无头 benchmark（没有 UI 和 OSD 开销）：

| 源 | 分辨率 | passthrough | VSR 2× |
|------|--------|-------------|--------|
| AV1 720p60 | 1280×720 | 1670 fps | 270 fps |
| H.264 1080p | 1920×1080 | 1303 fps | 120 fps |
| H.265 1080p | 1920×1080 | 1307 fps | 121 fps |

RIFE 推理（FP16）：768×1280 时 273 fps，1152×1920 时 90 fps。1080p 的 VSR 数字看起来不高，是因为 1080p 输出的像素量是 720p 的 4 倍。

分发用的引擎以 `--hardwareCompatibilityLevel=ampere+` 构建一次——一个引擎文件跑遍 compute capability ≥ 8.0 的 GPU：Ampere（RTX 30）、Ada（RTX 40）、Blackwell（RTX 50）、Hopper 及更新。实测代价：231.7 vs 原生构建 234.3 fps——约 1%，换来只分发一个引擎文件，划算。

插帧质量我们也用数值方法验证过（插出来的帧在时间上应该正好落在相邻两帧中间；用 repeat 检测器标出直接复制自某一侧的帧）。整部电影 13,439 个帧对上，运动内容的成功率约 96%——但那是 RIFE lite 时代测的，早于现在的 4.26/full 引擎；方法在仓库里，你可以拿自己的片源复测。

## mpv 管线注意事项

- **pull 模型**：滤镜每次调用出一帧；队列型滤镜（插帧器）要自己管 lookahead 和处理 flush。
- **所有权**：`mp_image` 引用；入队意味着持引用；double-free 要到 teardown 才暴露。
- **软解/硬解入口不对称**：硬解帧本来就是 CUDA 的；软解路径必须先有上传滤镜，否则下游的纯硬件滤镜会悄悄全部直通。
- **输出同构**：所有滤镜输出保持同一像素格式/range 家族，否则 VO 每帧转换路径不同会闪。
- **reconfig 信号**：滤镜会被询问渲染目标尺寸（`scale=auto` 就是基于它），尺寸变化尽量映射为热更新而不是重建（VFX 会话在输入尺寸不变时存活；RIFE 引擎任何尺寸变化都只是 `setInputShape`）。

## 踩过的坑

- **渲染进 Qt 窗口**：播放器以 `vo=libmpv` 运行，经 `mpv_render_context` 渲染到与 Qt 场景图共享的 Vulkan VkImage（CUDA-Vulkan 共享设备）——不需要任何窗口嵌入技巧，Wayland/X11 行为一致。
- **TensorRT 引擎版本锁定**：引擎只能用构建它的那个 TRT 版本反序列化，这是设计使然（11.1 vs 11.2 双向实测）。TRT 升级后要重建引擎——构建脚本在仓库里。
- **一个进程两个 TensorRT**：VFX SDK 捆绑 TRT 10，RIFE 用系统 TRT 11。TRT-10 链以 `RTLD_LOCAL` 预加载（符号绝不进全局命名空间、不会和 TRT 11 交叉绑定），RIFE 的 TRT 11 同样 `RTLD_LOCAL`；每个库只需一次 `dlsym`（其余全是 vtable）。
- **分发**：VFX SDK 许可禁止再分发，约 1.1 GB 的运行时不进 tarball——安装脚本从 NVIDIA 官方 PyPI wheel 拉取（curl + unzip，不调 pip、不改环境）。一个陷阱：VFX 代码按无版本名 dlopen（`libnppc.so`），wheel 里只有带版本名的（`.so.12`）——安装脚本负责建软链。
- **本系统的 ffmpeg `scale_cuda` 做不了半平面 YUV→RGB**（`CUDA_ERROR_NOT_FOUND`）；起步用的 CPU filter graph 相对 FFmpeg CLI 基线实测 46.5 dB PSNR（验证转换正确性），后来被 GPU 路径取代。

## 局限

- 只在单一 GPU 世代和少量文件上测过；代码从没在 RTX 20 系、其他驱动分支或原装发行版上跑过。
- GUI 需要 Qt ≥ 6.11（用了较新的 QML 特性）。
- 4K 输出的高帧率超分在现有硬件上不现实；播放器的自适应模式通常让 4K 源直通。
- 上面的插帧质量数字来自旧引擎；用现在的引擎重新测一遍还没做。
- 这是业余项目，bug 一定会被发现。仓库的结构让 AI 编码代理能快速上手——代码、mpv 覆盖层、设计记录都在仓库里，项目大部分就是这么开发出来的。

## 结语

这里没有任何深奥的技巧——而且大部分代码是 AI 编码代理写的，不是我。不变的是方法：读 NVIDIA 文档、所有东西实证验证、未经实测的结论一律存疑。正文里记下的坑，就是这些证据。

代码在 GitHub（GPLv2+）：[github.com/zhangmq/vsr-player](https://github.com/zhangmq/vsr-player)。欢迎 issue 和 PR。
