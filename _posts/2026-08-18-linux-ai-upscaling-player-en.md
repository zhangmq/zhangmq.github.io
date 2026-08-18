---
layout: post
title: "Real-time AI upscaling in a Linux video player"
date: 2026-08-18 12:00:00 +0800
categories: ai
permalink: /en/2026/08/18/linux-ai-upscaling-player/
translation: /zh/2026/08/18/linux-ai-upscaling-player/
---

> 🌐 [阅读中文版](/zh/2026/08/18/linux-ai-upscaling-player/)

NVIDIA's RTX Video Super Resolution is a great feature — it makes old 720p content look genuinely better. But on Linux it doesn't exist: the driver-level interface behind RTX VSR is Windows-only, and I couldn't find a Linux media player that uses the underlying SDK either. So I had an AI coding agent write one.

This post covers how the AI stages (VFX super-resolution and RIFE frame interpolation) are actually hooked into the player, how the whole pipeline got moved onto the GPU, and what to watch out for when extending the mpv video pipeline. The project: a Linux desktop player built on libmpv + Qt 6/QML, open source (GPLv2+), at [github.com/zhangmq/vsr-player](https://github.com/zhangmq/vsr-player).

## Where the AI runs: custom mpv video filters

mpv has a user-filter mechanism, but our filters need to link against the VFX SDK and TensorRT at build time, so they're compiled into a patched mpv. The repo keeps the pristine mpv 0.41 source as the base and an overlay tree (`src/mpv/`) with only the modified files; a script merges them and builds. That's the patch scheme — it keeps upgrades and diffing sane.

```
demux → decode → [vf_hwup] → [vf_rife] → [vf_vsr] → VO (libmpv) → Qt scene graph
                  ↑            ↑             ↑
             SW→CUDA upload  RIFE (TRT)   VFX SDK + CUDA
```

Three custom filters:

- `vf_hwup` — software-decoded frames uploaded to CUDA, so downstream filters only ever see hardware frames
- `vf_rife` — RIFE interpolation on TensorRT at source resolution (before upscaling)
- `vf_vsr` — super-resolution via CUDA + VFX SDK

**How mpv drives filters (the part that bites).** mpv filters are pull-driven: the pipeline calls the filter's process function repeatedly, and each call may produce *at most one* output frame — return NULL and the pipeline asks again later. For frame-interpolating filters this shapes everything: you maintain an internal queue of ready frames, and the process function is where you emit one per call, with each frame's PTS explicitly set by you. There is no push API, no "here's a batch of frames" — you hold back frames until you can interpolate them, which means the filter *owns* a small lookahead buffer and must handle the flush case at EOF.

A second contract: every frame in mpv is a `mp_image` with refcounted planes and metadata (colorspace, levels, transfer). Your filter must respect ownership — when you queue a frame for later, you hold a reference (talloc ref); when you emit one, you hand ownership over. Getting this wrong shows up as double-frees or canary asserts on teardown, not at the moment of the mistake.

## VSR integration

`vf_vsr` receives a hardware frame (NV12/P010, 8 or 10 bit) and outputs an upscaled RGBA frame.

The VFX SDK is a C API reached through `dlopen` (the project links nothing against it — the SDK's own copy of TensorRT 10 must never touch our link namespace; more below). Per-player-lifecycle we create one VFX session (`NvVFX_CreateEffect("VideoSuperRes")`), then configure it per load: bind the input/output RGBA buffers and set the quality level (`SetU32("QualityLevel", …)`).

Per frame:

1. Convert YUV → RGBA (see "moving everything to the GPU" for why this is on-GPU).
2. Push the RGBA frame into the session's input buffer, run on the shared CUDA stream.
3. Copy the output buffer into the filter-owned output buffer (one D2D copy, pitch is owned) and wrap it in an `mp_image` (RGBA, full range).

Two details worth knowing:

- **Color metadata must follow the frame.** The conversion matrix/range come from the `mp_image` color parameters (BT.601/709/2020, limited/full), guessed by resolution when the container doesn't declare them. The VFX model expects consistent input; feeding it mismatched colors is how you get "works but colors are subtly wrong".
- **Size changes are hot updates, not rebuilds.** The session survives as long as the input size is unchanged: changing the output size just re-binds the output buffer (`SetImage`) — that's the path fullscreen toggles take. Only an input-size change tears the session down (a new file rebuilds the whole filter chain anyway, so this is rare). Quality changes are a single `SetU32`.

## RIFE integration

RIFE is a neural frame interpolation model. Our engine is RIFE 4.26 ONNX, compiled to a TensorRT engine with **dynamic shapes** (min 128×128, opt 1152×1920, max 2176×3840) — one engine file serves any video resolution up to 4K. The filter reads the engine's profile at load, and on resolution change just calls `setInputShape`; buffers are allocated once at profile max and never move.

The model input is 7 channels: `[imgA(RGB), imgB(RGB), t]`. The filter:

- holds the current source frame in a queue; when the next frame arrives, that's a pair
- runs a custom CUDA kernel that *assembles the 7-channel input directly in the engine's device buffer* — the engine owns its `d_in`/`d_out` device pointers, the assemble kernel writes into `d_in` (with reflect padding), and a second kernel reads `d_out` and produces the output RGBA. All on the GPU; the only host transfer in the interpolator is the per-pair scene-change reduction (a few hundred floats), no full-frame H2D/D2H anywhere.
- sets `t` per interpolated position (we emit multiple intermediate frames per source pair when the target fps exceeds the source; for integer factors ≥ 2, `t` is fixed at `i/k` — the vs-mlrt Interleave convention), calls `enqueueV3` on the shared CUDA stream
- the convert kernel also guards against NaN engine outputs (a model numerical boundary on some pairs) by copying the temporally nearer source pixel instead of emitting black

Two behaviors that matter in practice:

- **Scene-change passthrough.** When a frame pair differs beyond a threshold (hard cut), interpolation has nothing to work with — the previous frame is passed through at the interpolated position instead of hallucinating a blend. This is also what the vs-mlrt ecosystem does.
- **Graceful degradation.** Inference cost is measured per frame pair (a short sliding window); when it exceeds the frame budget, the target fps steps down (60 → 48 → 40 → 30) before falling back to passthrough. The OSD shows the actual mode, not the requested one.
- **Content-time PTS — the correctness part.** Each emitted frame gets the PTS of its *content* time: midpoints at `t_prev + tval·(t_cur − t_prev)`, the source-frame copy at `t_cur`. The output is then strictly monotonic with no duplicates or gaps for any source rate, and every frame displays at its true time (in audio-sync playback the video interval is exactly source-interval/k — zero drift against the audio clock). This matters because mpv rejects non-monotonic timestamps: an earlier absolute-grid scheme (`t0 + n/out_fps`, exactly k frames per pair) misaligned whenever the source rate isn't an integer multiple of the grid — 29.97→60 (ratio 2.002) produced duplicate and gapped grid points, `Invalid video timestamp`, desync, and continuous drops. Content time has no grid to misalign.

## Moving the whole pipeline onto the GPU

The baseline architecture gives you hardware frames from NVDEC and a hardware VO. The pipeline between them was the problem: the VFX SDK consumes packed RGB, and FFmpeg's `scale_cuda` on this system lacks the kernels for semiplanar YUV (`CUDA_ERROR_NOT_FOUND`). We started with a CPU filter graph (correct, verified 46.5 dB PSNR against an FFmpeg CLI baseline) — and then replaced it with our own small NVRTC kernel (`yuv_to_rgba.c`) that converts NV12/P010 → RGBA directly on the GPU. That CPU→GPU round-trip per frame is exactly what was eliminated.

**Everything downstream of decode is now CUDA-only, in three steps:**

1. **`vf_hwup`: the only intentional H2D copy.** Software-decoded frames (any YUV) are converted on CPU (swscale) to NV12/P010 and uploaded with `cuMemcpy2DAsync` (Y and UV plane copies on one stream). That's the single, unavoidable host→device transfer in the whole chain — it exists because soft-decoded frames *start* on the CPU. Hardware-decoded frames pass through untouched. After this filter, every frame is a CUDA frame.

2. **One shared CUDA context, refcounted.** The whole chain runs on a single CUDA context: the decoder's when hardware-decoded, or `vf_hwup`'s own (software decode — the downstream filters borrow it). The context is wrapped in a small refcounted struct stashed in the frame's buffer opaque data, so the context outlives any individual filter — including the case where an output frame outlives its producer (the classic teardown double-free, avoided by counting, not by ordering).

3. **Every stage hands over without full-frame copies.** `vf_hwup`'s upload buffer *is* the frame; the YUV→RGBA kernel writes directly into the VFX input buffer; VFX's output is copied D2D into the filter's own buffer and wrapped in an `mp_image` (pitch is owned, so no re-striding); RIFE's assemble kernel writes the engine's `d_in` directly and its convert kernel produces the output frame. Within the chain, data moves by reference, in-place conversion, or D2D — never through the host.

**Stream discipline (a hard-won lesson).** Every filter synchronizes its own CUDA stream after processing (`cuStreamSynchronize`), never the device. A device-level sync would also wait for the VO's stream-0 copies — a deadlock we hit in practice (the VFX teardown path once blocked forever inside `cuCtxSynchronize` with the render loop stalled; observed in the Xid-109 debugging sessions). Per-stream sync keeps the filters serialized without ever blocking the render side.

One more thing the GPU-only design buys: the interpolator's intermediate frames are full-range RGBA at *every* output position, including passthrough copies. If some frames carry limited-range NV12 and others full-range RGBA, the VO picks different conversion paths per frame and you get visible flashing. Keeping the chain's output homogeneous is a correctness requirement, not a style choice.

## What we measured

RTX 5060 Ti, driver 610, 100 s files, headless benchmark (no UI, no OSD work):

| Source | Resolution | passthrough | VSR 2× |
|--------|-----------|-------------|--------|
| AV1 720p60 | 1280×720 | 1670 fps | 270 fps |
| H.264 1080p | 1920×1080 | 1303 fps | 120 fps |
| H.265 1080p | 1920×1080 | 1307 fps | 121 fps |

RIFE inference (FP16): 273 fps at 768×1280, 90 fps at 1152×1920. The 1080p VSR numbers look modest because 1080p output is 4× the pixels of 720p.

For distribution the engine is built once with `--hardwareCompatibilityLevel=ampere+`, which makes one engine file run on any GPU with compute capability ≥ 8.0 — Ampere (RTX 30), Ada (RTX 40), Blackwell (RTX 50), Hopper, and newer. Measured cost: 231.7 vs 234.3 fps compared to a natively-built engine — about 1%, worth it to ship a single engine.

Interpolation quality was validated numerically (interpolated frames should sit temporally midway between their neighbors; a repeat detector flags frames copied from either side). On a full movie (13,439 frame pairs) the motion-content success rate was ~96% with RIFE lite. That measurement predates the current 4.26/full engine — the methodology is in the repo if you want to repeat it on your content.

## Notes on the mpv pipeline

- **Pull model**: filters produce one frame per call; queue-based filters (interpolators) must own their lookahead and handle flush.
- **Ownership**: `mp_image` refs; queueing means ref-holding; double-frees surface at teardown.
- **hwupload asymmetry**: hardware-decode frames are already CUDA; software paths need an upload filter first, or downstream hw-only filters silently pass everything through.
- **Output homogeneity**: one pixel format/range family across all filter outputs, or the VO's per-frame conversion path flashes.
- **Reconfig signals**: filters get queried for the render-target size (that's what `scale=auto` is based on), and size changes should map to hot updates rather than rebuilds where possible (the VFX session survives output-size changes; the RIFE engine survives any size via `setInputShape`).

## Sharp edges we hit

- **Rendering into the Qt window**: the player runs mpv with `vo=libmpv` and renders via `mpv_render_context` into a Vulkan VkImage shared with Qt's scene graph (CUDA-Vulkan shared device) — no window-embedding tricks, identical behavior on Wayland and X11.
- **TensorRT engines are version-locked**: by design, an engine deserializes only with the exact TRT version that built it (verified both directions, 11.1 vs 11.2). Rebuild the engine after TRT upgrades — the build script ships in the repo.
- **Two TensorRT versions in one process**: VFX SDK bundles TRT 10, RIFE uses system TRT 11. The TRT-10 chain is preloaded `RTLD_LOCAL` (so its symbols never enter the global namespace and cross-bind with TRT 11), and RIFE's TRT 11 is also `RTLD_LOCAL`; only one `dlsym` per library is needed (everything else is vtable).
- **Distribution**: the VFX SDK's license forbids redistribution, so the ~1.1 GB runtime isn't in the tarball — the installer pulls it from NVIDIA's official PyPI wheel (curl + unzip, no pip, no environment changes). One trap: the VFX code dlopens unversioned names (`libnppc.so`), the wheel ships versioned ones (`.so.12`) — the installer creates the symlinks.
- **ffmpeg `scale_cuda` on this system cannot do semiplanar YUV→RGB** (`CUDA_ERROR_NOT_FOUND`); the CPU filter graph we started with measured 46.5 dB PSNR against an FFmpeg CLI baseline before being replaced by the GPU path.

## Limitations

- Tested on one GPU generation and a handful of files. The code has never been run on an RTX 20-series, a different driver line, or a stock distribution.
- GUI requires Qt ≥ 6.11 (recent QML features).
- 4K output upscaling at high frame rates is not realistic on current hardware; the player's adaptive mode usually passes 4K sources through untouched.
- Interpolation quality numbers above are from an earlier engine version; re-validating with the current engine is on the todo list.
- This is a hobby project. Bugs will be found. The repo is structured so that an AI coding agent can get up to speed quickly — the code, the mpv overlay, and the design records are all in-tree, which is how much of this was developed.

## Closing

There's no deep trick to any of this — and most of the code was written by an AI coding agent, not by me. What that doesn't change is the method: read the NVIDIA docs, verify everything empirically, and distrust any claim until it's measured. The pitfalls above are exactly that kind of evidence.

The code is on GitHub (GPLv2+): [github.com/zhangmq/vsr-player](https://github.com/zhangmq/vsr-player). Issues and pull requests welcome.
