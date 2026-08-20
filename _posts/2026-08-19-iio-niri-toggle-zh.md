---
layout: post
lang: zh-CN
title: "iio-niri-toggle：给 niri 补上屏幕自动旋转"
date: 2026-08-19 12:00:00 +0800
categories: tech
tags: [niri, wayland, rust, tablet]
permalink: /zh/2026/08/19/iio-niri-toggle/
translation: /en/2026/08/19/iio-niri-toggle/
description: 为 niri Wayland 合成器补上屏幕自动旋转：x86 二合一平板专用守护进程，配合 DMS 面板一键锁定/解锁，root 运行 + 完整沙箱。
---

[English](/en/2026/08/19/iio-niri-toggle/)

本来我以为这个项目没有人会感兴趣，但是意外收到了 [FearlessSpiff](https://github.com/FearlessSpiff) 提交的 PR，非常感谢！既然有人用，说明目前功能是正常的，所以我打算完善后正式以 1.0 发布。

（因为对 release 流程不太熟悉，过程中版本号 bump 得略快了些，目前已经是 1.0.4 了。）

项目最初设想是基于 [iio-niri](https://github.com/Zhaith-Izaliel/iio-niri) 来实现，但 iio-niri 的设计范围是随 niri 会话运行（由 niri `spawn-at-startup` 或用户级 systemd 服务启动），不覆盖登录前（greetd 阶段）和跨会话场景；而我需要的是系统级的自动旋转守护进程，所以选择自行实现为单一二进制。

## 这是什么

`iio-niri-toggle` 是一个为 [niri](https://github.com/niri-wm/niri) Wayland 合成器提供**屏幕自动旋转**的守护进程，专为 x86 二合一平板设计。配合 [DankMaterialShell](https://danklinux.com/)（DMS）面板，可以在任务栏和控制中心里直接切换「自动旋转 / 锁定」。

## 用法

### 命令行

| 命令 | 说明 |
|------|------|
| `iio-niri-toggle daemon` | 启动守护进程（由 systemd 管理） |
| `iio-niri-toggle lock` | 锁定当前屏幕方向 |
| `iio-niri-toggle unlock` | 恢复自动旋转 |
| `iio-niri-toggle status` | 查看当前状态 |
| `iio-niri-toggle toggle` | 切换锁定/自动旋转 |

### DMS 控制中心开关

安装时 `install.sh` 会询问插件安装位置；装好后打开控制中心，点击编辑按钮进入编辑模式，在可用磁贴里找到「屏幕旋转」并添加，点击即可切换：

![DMS 控制中心旋转开关](/assets/img/dms-control-center.png)

磁贴图标会随状态变化：自动旋转时显示 `screen_rotation`，锁定时显示 `screen_lock_rotation`，文案也会跟随系统语言（简体中文 / English）。

## 原理

整体是**单个 Rust 二进制守护进程**，基于 poll 的事件循环（200ms 超时），单线程整合以下模块：

1. **检测内屏** — 启动时通过 sysfs（`/sys/class/drm/card*-*/status`）自动识别 eDP/DSI/LVDS 内置屏幕；找不到内屏直接退出报错
2. **订阅传感器** — 连接系统总线上的 [iio-sensor-proxy](https://gitlab.freedesktop.org/hadess/iio-sensor-proxy/)，订阅 `AccelerometerOrientation` 变化信号（ClaimAccelerometer 带重试）
3. **应用变换** — 方向变化时调用 `niri msg output <monitor> transform <tr>` 旋转屏幕
4. **状态机** — 两种模式：
   - *自动旋转*：变换由实时传感器方向驱动
   - *锁定*：变换固定为持久化值，忽略传感器变化
5. **状态持久化** — 写入 `/var/lib/iio-niri-toggle/state.json`，跨会话保持（greetd → 用户登录切换也不丢）
6. **健康检查** — 每 30 秒重新查询一次传感器方向，兜底丢失的信号

### 为什么以 root 运行

守护进程要进入登录用户的 `/run/user/<uid>`（0700 私有目录）找到 niri 的 IPC socket 才能发指令——这个动作只有 root 或该用户本人能做，而守护进程必须在任何用户登录**之前**启动（`Before=greetd.service`）。因此以 root 运行，但 systemd unit 配置了完整沙箱（`ProtectSystem`、`PrivateNetwork`、capability 裁剪到只剩 `CAP_DAC_OVERRIDE`/`CAP_DAC_READ_SEARCH` 两项），`systemd-analyze security` 评分 3.1/10。

## 安装与卸载

```bash
# 安装（自动下载最新 release、校验 SHA256SUMS、解压安装）
curl -LO https://raw.githubusercontent.com/zhangmq/iio-niri-toggle/main/deploy/install-release.sh
bash install-release.sh

# 卸载（移除服务、二进制、状态与 DMS 插件）
curl -LO https://raw.githubusercontent.com/zhangmq/iio-niri-toggle/main/deploy/uninstall.sh
bash uninstall.sh
```

Release 以 tarball 发布在 GitHub Releases（含二进制、systemd unit、安装/卸载脚本、DMS 插件与文档）。

## 参考资料

- GitHub：https://github.com/zhangmq/iio-niri-toggle
- [niri](https://github.com/niri-wm/niri)
- [iio-sensor-proxy](https://gitlab.freedesktop.org/hadess/iio-sensor-proxy/)
- [iio-niri](https://github.com/Zhaith-Izaliel/iio-niri)
- [DankMaterialShell](https://danklinux.com/)
