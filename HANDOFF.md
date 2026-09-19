# DeskBand 交接文档

> 写于 2026-09-19 凌晨（Hack the North 2026，提交截止：周日 08:00）。
> 读者：Hank（硬件线）、Richard（AI / 音乐 API 线），以及任何接手的人。
> 这份文档力求自包含。哪里看不懂，把**这份文档全文**（必要时加上相关源码文件）贴给任意 AI 助手提问即可，文档里的信息足够它回答。

---

## 0. 一页纸速览

**DeskBand 是什么**：把桌上的东西举到摄像头前，按一下快门，画面定格，每个被认出的物体变成一件乐器，组成一支永远不跑调的乐队。

**30 秒跑起来**（在 Aaron 的 MacBook 上，环境已经全部装好）：

```bash
cd ~/Desktop/DeskBand && .venv/bin/python main.py
```

或者直接双击 `dist/DeskBand.app`。操作：`空格` 拍照 / 重拍，点右侧乐器架上的缩略图（或 `1`–`8`）开关已保存的乐器，`p`（或快门右边的按钮）演奏 / 暂停，`m`（或快门左边的 φ 钮）数学旋律模式，`0` 全部取消选择，`s` 存当前画面，`d` 调试面板，`f` 全屏，`q` 退出。

**现在的状态**

| 模块 | 状态 |
|---|---|
| 音频引擎（采样 + 合成 + 混响 + 限幅） | 完成，有自动化测试，离线和实时都验证过无破音、无丢块 |
| 作曲（和弦循环、各乐器的演奏型） | 完成，听感已由 Aaron 认可方向（朦胧钢琴），细节可继续调 |
| 音色（音乐厅大钢琴弱奏层、国王十字弦乐等） | 完成，已从 Logic 音色库解包到 `cache/` |
| 界面（预览 / 拍照 / 定格演奏） | 完成 |
| `.app` 一键启动 + 摄像头权限 | 完成 |
| 物体识别 | **能用但不稳，是当前最大的未决问题**，见第 2 节和第 9 节 |
| 外部控制接口（给硬件和 AI 用的 UDP 口） | 完成，有测试、有模拟器，见第 10 节 |
| Zybo Z7-20 FPGA 实时指挥器（Hank） | **实时指挥器已扩展为自动生成每小节的硬件作曲引擎：LFSR + 七路 Euclidean/Bresenham 发生器、track lock、energy 和 fill；RTL/协议测试、100 MHz place-and-route、固件和新版 BOOT.BIN 已通过。旧版 UART/时序/LFO/envelope 已在真机通过并写入 QSPI；新版仍需重刷和跑 32-event smoke test，随后做 Mac 音频联调。** Mac 端 AI 必须先读 `MAC_AI_HANDOFF.md`，再按 `fpga/README.md` 操作。 |
| "拿起来晃动 → 演奏变密变亮"的交互 | **没做**（拍照模式下物体是定格的，这个交互需要重新设计，见第 15 节） |

**分工**

- **Hank（硬件线）**：胸牌 > Zybo 控制台 > LeLamp。全部通过第 10 节的 UDP 协议接入，不需要读懂音频代码。见第 11 节。
- **Richard（AI / 音乐 API 线）**：ElevenLabs > Gemini > OMNI，Baseten 可选。同样走 UDP 协议。见第 12 节。
- **Aaron**：主程序、音乐、识别、演示。

**三条铁律**

1. 所有代码必须是比赛期间新写的。不要从旧项目（包括 `~/Desktop/MusicDance`）复制代码。公开的库和模型可以用。
2. `cache/`、`weights/`、`*.pt`、`dist/`、`.venv/` **永远不进 git**（已在 `.gitignore`）。`cache/shots/` 里是带人脸的照片，更不能传。
3. API key 一律走环境变量，不写进任何会提交的文件。

---

## 1. 演示流程（评委看到的）

1. 启动后是实时预览：画面是低饱和的灰调，被认出的物体有一个很淡的细线圆角框，左下角毛玻璃卡片写着 "On the desk" 和当前看到的物体。此时**没有声音**（空桌 = 安静，这是 Aaron 明确要的）。
2. 按空格（或点屏幕下方的圆形快门）：画面闪白并定格。程序对定格的这一帧再做一次全分辨率精识别。
3. 定格画面里，每个物体的框内恢复彩色，框旁写着 `物体 · 乐器`，对应乐器开始演奏。某个乐器发声的瞬间，它的框会轻微放大、变亮（"呼吸"）。卡片标题变成 "Band"，右上角显示当前和弦。
4. 再按空格：回到预览，**音乐不停**。再拍下一样东西，它就加入乐队。乐队是一样一样拍出来的，不需要七样东西同时入镜。

**乐器架（画面右侧一列缩略图）**

- 每次拍照，照片里认出的物体会被裁成缩略图存进自己的槽，并且立刻点亮（开始演奏）。同一种物体重拍，新照片覆盖旧的。
- 乐器架一开始是**空的，什么都不显示**。第一样被认出并拍下的东西排在最上面，之后按拍到的先后往下排（每种乐器最多一格；同一种东西重拍只换图片，位置不变）。
- **乐队 = 乐器架上点亮的格子**。点一下（或按 `1`–`8`，从上往下数）开关这件乐器，物体不需要还在镜头前。每件乐器的缩略图叠着自己颜色的半透明滤镜（颜色在 `deskband/config.py` 的 `INSTRUMENTS[...]["tint"]`，滤镜在 `ui.tint()`）。点亮的是实的，发声时边框跟着闪；关掉的变成半透明。
- **演奏 / 暂停键**（快门右边的小圆钮，键盘 `p` 或回车）：总开关。暂停 = 全部静音，但乐器架上的选择保留，再按一下原样恢复。
- **一个物体只算一次**：同一个东西被读成两个名字（杯子同时被认成 cup 和 bottle）或者同类的大框套小框（整个杯子 + 杯把），只保留置信度最高的那个框；笔放在书上这种“在里面但框差很多”的情况两个都保留。逻辑在 `deskband/vision.py` 的 `same_thing()`。
- `0`：全部静音，但保存的东西都还在（换下一位评委时用）。
- 右键点槽，或鼠标悬停在槽上按 `x`：删除这个槽。
- 存在 `cache/shelf/`（每个槽一张 jpg + `shelf.json`），**重启后还在，选择状态也会恢复**。按 `0` 可清空当前选择。这个目录不进 git（缩略图里可能有人脸）。
- 代码：`deskband/shelf.py`（存取），`main.py` 的 `draw_dock / slot_at / select / forget / silence`。

**物体 → 乐器**（定义在 `deskband/config.py` 的 `INSTRUMENTS`）

| 物体（摄像头认的词） | 乐器 | 在乐队里的角色 |
|---|---|---|
| cup（cup / mug） | 音乐厅大钢琴，弱奏层 + 低通 | 每小节轻轻滚一个和弦，上面一条稀疏旋律 |
| pen（pen / pencil / marker） | 古典原声吉他 | 根音 + 分解和弦 |
| bottle（bottle / water bottle） | 低音提琴拨奏 | **只弹和弦根音**，3-3-2 节奏 |
| book（book / notebook） | Trap Heat 鼓机，弱奏 | 底鼓、rim、轻镲 |
| glasses（glasses / eyeglasses / sunglasses） | 国王十字弦乐（King's Cross） | 长音铺底 |
| cell phone | 铁琴 Glockenspiel | 高音点缀，每小节 1–2 个音 |
| laptop（laptop / tablet / ipad） | 柔和电钢琴（程序合成） | 钢琴和弦音高八度，附点八分的闪烁 |

每个物体对应的音色文件在哪、在 Logic 里叫什么，看 `INSTRUMENTS.txt`（中文，由 `tools/write_instruments_txt.py` 从 config 自动生成，改了 config 后重跑一次）。

---

## 2. 当前未决问题（接手的人先看这里）

### 2.1 物体识别不稳（最高优先级）

经过：
- 最初用 `yolov8s-worldv2`（YOLO-World 小模型）@640：杯子、手机、笔记本能认，**台灯认不出** → 换成耳机 → **入耳式耳机成功率也很低** → 换成眼镜。
- 为了提高准确率，换成了 `yolov8l-worldv2`（大模型）@960，拍照时再加一次 @1280 的精识别。
- **换完之后 Aaron 反馈"笔突然检测不出来了"**。这个回归**还没有查**。

已有的线索和工具：
- `cache/shots/` 里有 4 张 Aaron 刚拍的真实照片（`shot_20260919_0403xx.jpg` 等）。其中一张是他把一支蓝色的笔竖着举在脸前。注意：**物体是举在手里、挡在人脸前面的，不是平放在桌上**，这对检测器是更难的场景。
- 对比新旧模型、不同分辨率、不同提示词，只需要一条命令（不需要摄像头）：

```bash
cd ~/Desktop/DeskBand
.venv/bin/python tools/eval_prompts.py --model yolov8l-worldv2.pt --imgsz 640 960 1280 --conf 0.03
```

```bash
.venv/bin/python tools/eval_prompts.py --model yolov8s-worldv2.pt --imgsz 640 960 1280 --conf 0.03
```

```bash
.venv/bin/python tools/eval_prompts.py --prompts "pen,ballpoint pen,blue pen,pencil,stylus,marker" --conf 0.03
```

  输出里带 `*` 的是低于 app 阈值（`DETECT_CONF = 0.25`）的检测。看笔在哪个模型、哪个分辨率、哪个提示词下分数最高，然后改 `deskband/config.py`。
- 最可能的原因（按可能性排序，均未验证）：
  1. 大模型对 "pen" 这个词给的置信度整体偏低（不同模型的分数标定不一样），被 0.25 的阈值卡掉 → 降低 `DETECT_CONF`，或给笔换更具体的提示词。
  2. 实时识别从 1280 降到了 960，笔很细，像素不够 → 把 `DETECT_IMGSZ` 调回 1280（大模型 1280 每帧约 195ms，预览时框会更新得慢，但拍照模式可以接受）。
  3. 提示词变多（13 → 16 个）后，相近的词互相分走了检测。
- **一键回退到之前能认笔的配置**：把 `deskband/config.py` 里改成

```python
DETECT_MODEL = "yolov8s-worldv2.pt"
DETECT_IMGSZ = 1280
```

- 如果开放词汇检测始终不够稳，备选方案是换物体：优先选 COCO 数据集里有的类别（`mouse` 鼠标、`keyboard` 键盘、`backpack` 背包、`scissors` 剪刀、`banana`/`apple` 水果、`clock`），这些类别任何检测模型都认得很稳。换物体只需要改 `INSTRUMENTS` 里那一行的 key 和 `detect=[...]`。

### 2.2 眼镜、iPad 还没有在真实摄像头下验证过
提示词已经加了（`glasses / eyeglasses / sunglasses`，`laptop / tablet / ipad`），链路用假摄像头测过不报错，但识别率需要真人在镜头前试。按 `d` 打开调试面板，第三行会显示触发的词和置信度。

### 2.3 蓝牙耳机
Aaron 平时用一副叫 "🌵" 的蓝牙入耳式耳机输出。引擎已经做了适配（按设备原生采样率 48kHz 输出、大缓冲），实测无问题。但**演示时建议用 MacBook 扬声器或有线音箱**：蓝牙有约 180ms 的固有延迟，而且一旦有任何程序打开了耳机的麦克风，macOS 会把它切到通话模式，音质会变得极差，这与本程序无关。程序每次启动时读取系统默认输出设备，**切换输出设备后要重启 DeskBand**。

---

## 3. 运行环境（全部是实测值）

| 项目 | 值 |
|---|---|
| 机器 | MacBook Pro，Apple M2 Pro，10 核，16 GB 内存 |
| 系统 | macOS 26.6.2（Build 25G83） |
| Python | 3.11.9，来自 python.org 的安装包：`/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11` |
| 虚拟环境 | 项目内 `.venv/`（1.2 GB），**不要用系统自带的 Python 3.14**，torch 对它的支持不完整 |
| Logic Pro | 11.0.1（`/Applications/Logic Pro X.app`），并且下载了完整音色库 |
| 音色库位置 | `/Library/Application Support/Logic/`、`/Library/Application Support/GarageBand/`、`/Library/Audio/Apple Loops/`（都在内置硬盘；Aaron 的外置盘 `/Volumes/T7` 上有一份同样的拷贝，程序不依赖它） |
| 仓库 | `https://github.com/mu142857/DeskBand.git`，分支 `main` |

**Python 包版本**（`.venv/bin/pip list` 实测）

| 包 | 版本 | 用途 |
|---|---|---|
| ultralytics | 8.4.155 | YOLO-World 检测 |
| torch / torchvision | 2.14.0 / 0.29.0 | 推理，走 `mps`（Apple GPU） |
| clip | 1.0（ultralytics 自动装的） | YOLO-World 的文本编码器 |
| opencv-python | 5.0.0.93 | 摄像头、窗口、绘图 |
| sounddevice | 0.5.6 | 音频输出（PortAudio） |
| soundfile | 0.14.0 | 读 wav/aiff/caf（自带的 libsndfile 能直接读 ALAC 的 .caf） |
| numpy | 2.4.6 | |
| scipy | 1.17.1 | 滤波、重采样 |
| pillow | 12.3.0 | 用系统的 SF Pro 字体渲染文字 |
| certifi | 2026.7.22 | 修复 python.org 版 Python 下载模型时的 SSL 证书错误 |

**不在 git 里、但运行需要的文件**

| 路径 | 大小 | 是什么 | 怎么得到 |
|---|---|---|---|
| `.venv/` | 1.2 GB | Python 环境 | 见第 4 节 |
| `yolov8l-worldv2.pt` | 94 MB | 检测模型（大） | 首次运行自动下载，来源 ultralytics 官方 GitHub releases |
| `yolov8s-worldv2.pt` | 25 MB | 检测模型（小，备用） | 同上 |
| `weights/clip/ViT-B-32.pt` | 338 MB | CLIP 文本编码器 | 首次运行自动下载 |
| `cache/concert_grand_soft/` | 113 MB | 音乐厅大钢琴弱奏层，88 个 wav + keymap.json | `tools/exs_extract.py`，见第 8 节 |
| `cache/concert_grand/` | 88 MB | 同一架钢琴的中强层（备用） | 同上 |
| `cache/kings_cross/` | 72 MB | 国王十字弦乐，61 个 wav + keymap.json | `tools/make_kings_cross.py` |
| `cache/shots/` | 几 MB | 每次拍照存下的原图（**含人脸，勿外传**） | 运行时自动生成 |
| `cache/deskband.log` | | 从 `.app` 启动时的日志 | 自动 |
| `dist/DeskBand.app` | | 启动器 | `tools/build_app.sh` |

---

## 4. 在另一台 Mac 上从零搭环境

> 如果只是做硬件或 AI 脚本，**不需要搭这个环境**：用 `python3 tools/remote_sim.py` 起一个协议模拟器就能开发（任何系统、零依赖），见第 10.6 节。

前提：Apple Silicon Mac；装了 Logic Pro 或 GarageBand 并下载了音色库（没有的话，采样乐器会**静音但不会崩**，只有 laptop 的合成电钢琴有声音）。

```bash
git clone https://github.com/mu142857/DeskBand.git ~/Desktop/DeskBand
```

```bash
cd ~/Desktop/DeskBand && /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -m venv .venv
```

```bash
.venv/bin/pip install ultralytics opencv-python sounddevice soundfile numpy scipy certifi pillow
```

解包两个音色（各几分钟，只需一次）：

```bash
.venv/bin/python tools/exs_extract.py "/Library/Application Support/Logic/Sampler Instruments/z_Internal/Studio Piano/Concert Grand Piano.exs" "/Library/Application Support/Logic/EXS Factory Samples/Studio Piano/Concert Grand Piano" cache/concert_grand_soft --velocity 45 --max-seconds 8
```

```bash
.venv/bin/python tools/make_kings_cross.py
```

```bash
tools/build_app.sh
```

```bash
.venv/bin/python main.py
```

注意事项：
- `dist/DeskBand.app` 里**写死了项目的绝对路径**（编译进了启动器），所以项目文件夹移动或换机器后必须重新跑 `tools/build_app.sh`。它需要 Xcode Command Line Tools 里的 `clang`。
- 第一次运行会下载模型（共约 460 MB）并弹摄像头权限。从终端运行时权限记在"终端"名下；从 `.app` 运行时记在 "DeskBand" 名下，是两份独立的授权。
- 路径不在桌面也可以，代码里没有写死 `~/Desktop`，只有 `.app` 启动器写死了构建时的路径。

---

## 5. 日常使用

| 按键 | 作用 |
|---|---|
| `空格` 或点击快门 | 预览 → 拍照定格，照片里的物体存进乐器架并开始演奏；再按 → 回到预览（音乐不停） |
| 点击乐器架上的缩略图，或 `1`–`8`（从上往下数） | 开关一件已保存的乐器 |
| `p` / 回车 / 点快门右边的小圆钮 | 演奏 / 暂停（总开关，选择保留） |
| `m` / 点快门左边的 φ 钮 | 数学旋律模式开 / 关（点亮 = 开），从下一小节生效，见 7.2 |
| `tab` / 点最左边的钮 | 摄像头画面 ↔ 舞台（stage）。舞台是一个平面：纵轴响度、横轴复杂度。把右边乐器架上的缩略图拖进去 = 加入乐队，把圆形的 token 拖出平面（或右键）= 移出乐队；在平面里拖动就是调响度和复杂度。舞台上按空格回到摄像头。见 7.2 末尾 |
| `0` | 乐器架全部取消选择，保存的东西不丢 |
| 右键点槽，或悬停在槽上按 `x` | 删除这个槽里保存的乐器 |
| `s` | 把当前实时画面存到 `cache/shots/frame_时间.jpg`（屏幕轻闪一下）。用于收集"认不出来"的样本 |
| `d` | 调试面板开关 |
| `f` | 全屏开关 |
| `q` 或 `Esc` | 退出 |

**调试面板各行的含义**
1. `display` 界面帧率；`camera` 摄像头帧率；`detector <模型名>` 识别帧率和单帧耗时；`audio` 音频回调占用的时间比例（超过 80% 才需要担心）；`xruns` 音频丢块次数（应该一直是 0）。
2. 当前和弦、小节内第几个十六分音符、第几小节。
3. 此刻检测到的词和置信度，例如 `mug 0.62  tablet 0.41`。
4. 各声部当前音量（0–1，淡入淡出中会是中间值）。
5. 已加载的采样集。

**日志**：从终端运行时直接打印；从 `.app` 运行时在 `cache/deskband.log`（每次启动清空）。

---

## 6. 软件架构

### 6.1 线程

```
主线程 (main.py: App.run)
  ├─ 打开摄像头（必须在主线程，否则 macOS 不弹权限窗）
  ├─ 每帧：处理远程指令 → 渲染界面 → imshow → 读键盘
  └─ 拍照时：对定格帧调用一次 vision.detect(frame, 1280)

取帧线程 (vision.py: Vision._capture_loop)     摄像头帧率，只负责把最新一帧放好
识别线程 (vision.py: Vision.run)               YOLO-World，拿最新帧推理，约 6–9 次/秒
音频回调 (synth.py: Engine._callback)          PortAudio 的实时线程，每 1024 采样调用一次
采样加载线程 (Engine.load_instruments)         启动时一次，约 2 秒
远程端口线程 (remote.py: Remote.run)           收 UDP 指令入队、向订阅者推状态
```

关键约束：**音频回调里不能有任何阻塞**。它只做数组切片和 numpy 运算；文件读取、模型推理、网络都在别的线程。识别再慢也只会让框更新得慢，不影响声音。模型推理有一把锁（`Vision.model_lock`），保证实时识别和拍照精识别不会同时跑。

### 6.2 数据流

```
摄像头 → 取帧线程 → 最新帧 ─┬→ 界面（预览）
                            └→ 识别线程 → detections / last_seen
按快门 → App.shoot():
    定格帧 + 实时检测结果 + 1280 精识别 + 最近 0.5 秒见过的物体  → 合并去重
    → 每个物体裁缩略图存进乐器架 (Shelf.add) 并点亮
    → 乐队 = 乐器架上点亮的槽 (Shelf.selected) → 再叠加远程强制开关 (manual)
    → engine.set_active(声部, 开/关)     （音量在约 2 秒内平滑过渡）

音频回调每个块：
    走步进时钟（十六分音符）→ 每一步向 Composer 要这一步的音符事件
    → 为每个事件创建一个 Voice（采样或合成）
    → 所有 Voice 渲染并按声部增益混合 → 干声总线 + 混响发送总线
    → 混响 → 补偿增益 → 限幅器 → 输出
```

### 6.3 文件说明

| 文件 | 行数级别 | 职责 |
|---|---|---|
| `main.py` | ~330 | App：状态机（preview / show）、拍照、界面绘制、键盘、远程指令处理、`state_dict()` |
| `deskband/config.py` | ~140 | **所有可调参数**：速度、和弦、物体→乐器表、提示词、音色路径、混响、限幅、识别模型与分辨率、远程端口 |
| `deskband/vision.py` | ~150 | 摄像头、YOLO-World、提示词→声部映射、重复框合并 |
| `deskband/music.py` | ~260 | Composer：和弦循环，每种乐器一个 Pattern 类，逐小节生成音符事件 |
| `deskband/synth.py` | ~330 | Engine：步进时钟、Voice（采样/合成）、声部增益、混响发送、补偿增益、限幅器、一次性音效、变速 |
| `deskband/sampler.py` | ~180 | 读音频、从文件名解析音高、KeyMap（就近取样 + 变调比率）、各音色集的加载 |
| `deskband/fx.py` | ~100 | 大厅混响（Freeverb 结构，按 256 采样的子块向量化） |
| `deskband/ui.py` | ~200 | 绘图原语：双色调底图、保留彩色区域、细线圆角框、SF Pro 文字、毛玻璃卡片、乐器架的颜色滤镜 |
| `deskband/remote.py` | ~110 | UDP/JSON 远程端口 |
| `deskband/stage.py` | ~260 | 舞台：响度 × 复杂度平面，拖放、位置 → 引擎增益和作曲复杂度 |
| `deskband/cloud.py` | ~120 | Gemini 看照片写描述（后台线程，只显示）、ElevenLabs 生成音效；只用 urllib，key 只从环境变量读 |
| `deskband/vocals.py` | ~110 | 人声采样：ElevenLabs 生成 → 测音高 → 微调到半音 → keymap |
| `tools/exs_extract.py` | ~770 | 把 Logic 的"打包"采样器乐器（.exs + consolidated .caf）解成一个音一个 wav |
| `tools/make_kings_cross.py` | | 国王十字：五个弦乐声部叠成合奏 |
| `tools/render_demo.py` | | **离线把乐队渲染成 wav**，不需要摄像头，调音乐时最常用 |
| `tools/eval_prompts.py` | | 用存下的照片对比模型/提示词/分辨率/阈值 |
| `tools/check_pitch.py` | | 检查每个采样的实际音高是否和文件名一致 |
| `tools/write_instruments_txt.py` | | 重新生成 `INSTRUMENTS.txt` |
| `tools/remote_test.py` | | 远程端口的命令行客户端 |
| `tools/remote_sim.py` | | **远程端口模拟器**，零依赖，给硬件和 AI 脚本开发用 |
| `tools/build_app.sh` + `tools/launcher.c` + `tools/make_icon.py` | | 生成 `dist/DeskBand.app` |
| `tests/test_reverb.py` | | 向量化混响 vs 逐采样参考实现，误差须 < 1e-4 |
| `tests/test_voice.py` | | 采样播放器跨块播放须与原始采样逐位一致 |
| `tests/test_remote.py` | | 远程端口端到端：指令、强制开关、变速、换和弦、音效、状态推送 |
| `tests/test_stage.py` | | 舞台：响度映射单调、复杂度中间不变/左稀右密/不跑调、位置存盘 |
| `styles/*.json` | | 和弦循环的示例文件（给 `style` 指令用） |

**跑全部测试**（不需要摄像头、不出声）：

```bash
cd ~/Desktop/DeskBand && .venv/bin/python tests/test_reverb.py && .venv/bin/python tests/test_voice.py && .venv/bin/python tests/test_remote.py
```

### 6.4 音符事件的格式

`Composer.step(step)` 返回一个列表，每个元素是：

```
(part, voice, midi_or_hit, velocity, duration_steps, delay_steps)
```

- `part`：声部名（= `INSTRUMENTS` 的 key，或 `"backing"`）
- `voice`：`piano / guitar / bass / strings / bells`（采样）、`drums`（此时第三项是 `"kick"` 这样的名字）、`keys / arp / sub`（合成）
- `velocity`：0–1
- `duration_steps`：时值，单位是十六分音符；到点后进入释音（各乐器的释音时间在 `synth.py` 的 `RELEASE`）
- `delay_steps`：不足一步的延迟（0–1），用来把钢琴和弦"滚"出来

### 6.5 时间与同步

- 120 BPM，内部网格是十六分音符（一步 = 125 ms = 6000 采样 @48kHz），一小节 16 步，一个和弦一小节。
- 音符起点是**采样级精确**的：一个块里跨过步进边界时，Voice 从块内的准确偏移开始渲染。
- 界面的"呼吸"和远程状态包里的 `beat_phase` 都**减去了输出延迟**（`Engine.latency`，蓝牙约 0.18 秒），所以它们对应的是"此刻听到的"，不是"此刻刚生成的"。

---

## 7. 音乐设计

### 7.1 和声

一小节一个和弦，四小节循环（8 秒一圈）。Aaron 指定的密集排列：

| 和弦 | 钢琴排列 | MIDI | 贝斯根音 |
|---|---|---|---|
| Fmaj7 | F A C E | 53 57 60 64 | F |
| G6 | G B D E | 55 59 62 64 | G |
| Em7 | E G B D | 52 55 59 62 | E |
| Am(add9) | E A B C | 52 57 59 60 | A |

四个排列的内声部是级进、共同音保持，这是"朦胧、悬浮"感的主要来源（参考对象：坂本龙一的钢琴）。MIDI 编号用 Logic 的约定：**C3 = 60**。

**永不跑调的原理**（学自 Mikutap）：旋律音只从 C 大调五声音阶（C D E G A）里选，这五个音对这四个和弦都成立；落在重音上的音再吸附到"既是和弦音又是五声音阶音"的音上。所以无论随机成什么样都和谐。Mikutap 的另一个做法，所有声音对齐到统一的节拍网格，这里同样采用。

### 7.2 各乐器的演奏型（`deskband/music.py`）

- **Piano（cup）**：第 0 步把排列从低到高滚出来（每个音隔 0.22 步 ≈ 27ms，最高音略响），时值拖到下一小节第 6 步，形成踏板式的模糊重叠；45% 的概率在第 10 步弱弱地重复上面两个音。旋律：每轮和弦循环生成一个"动机"（2–3 个八分音符位置 + 一条在五声音阶梯子上的走向），在四个和弦上各陈述一遍，起点锚在离音区中心最近的和弦音上。
- **Keys（laptop）**：排列提高八度，在第 2、5、8、11、14 步（附点八分的间距）上下行，和钢琴的正拍错开。
- **Guitar（pen）**：第 0 步弹根音，第 4、6、10、12、14 步从上往下拨排列里的音。
- **Bass（bottle）**：**只弹根音**，在第 0、6、12 步（3-3-2）。音区 C1–B1（MIDI 36–47），每个和弦在这个八度里恰好只有一个根音，小喇叭上也能听清音高。这是 Aaron 特别要求的，已经从渲染出的音频里实测过音高正确。
- **Drums（book）**：底鼓第 0、10 步，rim（30% 概率换成 snap）在第 4、12 步，闭镲每个八分音符，25% 概率第 14 步一个开镲。整体很轻。
- **Strings（glasses）**：低八度根音 + 排列的最低、中间、最高音，整小节长音，时值 19 步（略拖过小节线，和下一个和弦叠一下，因为国王十字的弓弦起音很慢，约 0.4 秒才到一半音量）。
- **Bells（cell phone）**：每小节 1–2 个高音区和弦音，只落在第 2、6、10、14 步（反拍）。
- **Vocal（headphones）**：ElevenLabs 生成的 "ooh" 人声采样（`deskband/vocals.py`）。每小节一到两个长音，落在和弦音上、就近移动，下面再叠一个轻一点的和弦音（两声部）。第一次启动且设了 `ELEVENLABS_API_KEY` 时，用 `config.VOCAL_PROMPTS` 里的每句提示词各生成一条几秒的长音，自动测音高，音高飘的丢掉，稳的微调到最近的半音，存成 `cache/vocal/<midi>.wav + keymap.json`，之后就和其他采样乐器一样按和弦变调播放。想重新生成就删掉 `cache/vocal/`，或运行 `.venv/bin/python -m deskband.vocals`。没有 key 时这件乐器不出声，其他一切照常。
- **数学模式**（`m`，`music.Sequence` 和各声部的 `plan_math`）：钢琴旋律、吉他、电钢琴、钟琴、人声不再重复固定的型，每小节现算，永不循环。节奏用欧几里得节奏（k 个音尽量均匀地铺在一小节里再旋转；E(3,8) 就是 3-3-2），k 和旋转量由混沌区的 logistic 映射 x→r·x·(1−x)（r=`config.LOGISTIC_R`）决定。音高朝一条 1/f 走向（Voss 算法，每一行是一个无理数旋转 frac(n·α)，所以永远不会回到同一个值）以级进为主地移动。音仍然只取五声音阶，强拍落在和弦音上，所以不会跑调。从下一小节线开始生效；贝斯、鼓、弦乐不变。
- **舞台（stage，`tab`，`deskband/stage.py`）**：每件乐器在平面上的位置决定两件事。**纵轴 = 响度**：在声部自己的 `level` 上再乘一个增益，正中间 0 dB，最下 −24 dB，最上 +9 dB（`config.STAGE_DB`，上下两半各自按 dB 线性），引擎里约 50ms 平滑（`Part.trim`），拖的时候立刻听到。**横轴 = 复杂度**（`Pattern.arrange`，每小节在 `plan`/`plan_math` 之后执行，所以从下一小节线生效）：中间一条（`config.STAGE_AS_WRITTEN`，0.4–0.6）原样演奏；往左按拍位强弱（`music.weight`：正拍 4、3-3-2 的另两个重音 3、四分拍 2、八分 1、十六分 0）从弱到强删音，最左只剩第 0 步，但永远不会删空；往右在空着的八分（弦乐和人声是四分）上加经过音，从前一个音朝后一个音级进，连着加就成了音阶跑动，过了一半还会给部分音加十六分倚音；鼓是加十六分闭镲、重音前的轻 rim、第 6 步底鼓。加的音只取五声音阶（吉他、贝斯、弦乐、人声取和弦音），所以不会跑调。加花用每个声部自己的随机数（`Pattern.orn`），所以放在中间时和原来的演奏一模一样。位置存在 `cache/shelf/shelf.json` 的 `pos` 里，重启后还在；拍照或点乐器架加入、但从没放过位置的乐器，会自动放在中线上靠中间的空位。
- **Backing**：可选的背景层（黑胶噪声、沙锤、低音铺底），**默认全关**，因为 Aaron 觉得它"诡异"。开关在 `config.BACKING`。

### 7.3 电平与总线（踩过坑，别乱动）

- 每个声部的 `level` 是按"单独演奏时峰值 0.2–0.45"校准的。七个全开时限幅前峰值约 0.9。
- `MAKEUP`：乐器少的时候整体抬一点（1 个 ×1.5，2 个 ×1.3，3 个 ×1.15，4 个以上 ×1.0）。
- 限幅器是**增益骑行式**的（整体拉低音量，不改变波形），上限 `CEILING = 0.89`，释放 0.5 秒。最后还有一道硬限幅只是保险，正常情况下碰不到。
- **换了音色或改了演奏型之后必须重新量电平**，否则会回到"破音"的状态。量法：

```bash
.venv/bin/python tools/render_demo.py /tmp/x.wav "cup,pen,bottle,book,glasses,cell phone,laptop,,"
```

  看输出的 `peak`（应 < 0.9）。想单独量某个声部，脚本参数里只写它。

### 7.4 混响

Freeverb 结构：每声道 8 个带阻尼的梳状滤波器 + 3 个全通，右声道延迟长度 +23 采样做立体声展开，预延迟 25ms。参数在 `config.REVERB`（room 0.92、damp 0.45、wet 1.0）。各声部送混响的量是 `INSTRUMENTS` 里的 `send`。延迟长度按 44.1kHz 设计，运行时按实际采样率缩放。

### 7.5 常见修改怎么做

| 想改什么 | 改哪里 |
|---|---|
| 速度 | `config.BPM`；运行时用远程指令 `bpm` |
| 和弦 / 排列 | `config.CHORDS`；运行时用远程指令 `style` |
| 某个乐器的音量、混响量、音区 | `config.INSTRUMENTS` 里那一行的 `level` / `send` / `lo` `hi` |
| 某个乐器怎么演奏 | `music.py` 里对应的 Pattern 类的 `plan()` |
| 钢琴更闷 / 更亮 | `config.PIANO_LOWPASS_HZ`（调低更闷；0 关闭） |
| 钢琴力度层 | 重新解包：`--velocity 45` 是弱奏，`84` 是中强 |
| 物体换一个 | `INSTRUMENTS` 的 key 和 `detect=[...]`，然后更新 `tools/write_instruments_txt.py` 里的 `OBJECT_CN` 和 README 的表 |
| 加第八个乐器 | `INSTRUMENTS` 加一行；如果是新的 `voice`，在 `music.py` 的 `PATTERNS` 注册一个 Pattern，在 `synth.py` 的 `_trigger` 里能路由到（采样的话在 `config.SAMPLE_SETS` 加一项即可） |

**调音乐的工作方式**：不要开摄像头，用 `tools/render_demo.py out.wav "脚本"` 离线渲染来听。脚本是逗号分隔的列表，每一项占一整圈和弦循环（8 秒）：写物体名 = 这一圈加入它，`-物体名` = 撤掉，空 = 保持。例：`"cup,,laptop,glasses,bottle,,-laptop"`。

---

## 8. 音色来源

全部来自这台 Mac 上 Logic Pro / GarageBand 自带的音色库，**原地读取，不拷进仓库**（授权上可以用于自己的作品，但不能再分发原始采样）。

| 音色 | 在 Logic 音色库里的位置 | 程序实际读的 |
|---|---|---|
| 音乐厅大钢琴 | 钢琴 → 音乐厅大钢琴 | `cache/concert_grand_soft/`（解包得到）；没有则 `cache/concert_grand/`；再没有则退回 Yamaha Grand 散装采样 |
| 国王十字弦乐 | 录音室弦乐 → Section Instruments → 国王十字（King's Cross，底层是 String Ensemble.exs） | `cache/kings_cross/`；没有则退回"流行弦乐" EXS Strings 2 |
| 古典原声吉他 | 吉他 → 古典原声吉他 | GarageBand 采样文件夹里的 `50A-1GA2-*.aif`（23 个） |
| 低音提琴拨奏 | 管弦乐器 → 弦乐 → 流行弦乐这一套 | `Cbs pizz f*.aif`（10 个） |
| 铁琴 | 管弦乐器 → 打击乐器 → 铁琴 | `GLS2_Pla_mf_*.wav`（17 个） |
| Trap Heat 鼓 | 鼓机 → 困住热量（Trap Heat） | 9 个单独的 aif |
| 柔和电钢琴 | 无（程序合成：FM，正弦载波，调制指数衰减） | `synth.py` 的 `keys` |

**关于"打包"格式**：钢琴和弦乐在 Logic 里是一个 `.exs` 文件（键位映射）加上几个巨大的 `_consolidated.caf`（所有采样首尾相接压成一个 ALAC 文件，每个几百 MB）。`tools/exs_extract.py` 解析 `.exs` 的二进制结构（84 字节块头，块类型在签名的第 24–27 位；zone 块里 +85 根音、+90/91 键位范围、+93/94 力度范围、+96/+100 在 caf 里的起止帧、+172 组号、+176 采样文件序号），按力度层切出每个音。常用参数：`--list` 只看结构不解音频；`--velocity N` 选覆盖该力度的层；`--group` 选奏法组；`--verify` 做音高核对。

国王十字的注意点：要用 "`<声部> Sustain`" 组而不是 "`Sustain Dest`" 组（后者起点晚约 235ms，跳过了弓弦起音，直接用会有咔哒声）；小提琴 1 和 2 在 6 个根音上共用同一份录音；低音区有几个音原始录音偏左约 8dB，加载时已做左右拉平（`sampler.load_kings_cross`）。

**音名约定的坑**：Logic 把中央 C 叫 C3（=60），GarageBand 的部分采样文件名用科学音高（C4=60）。`config.SAMPLE_SETS` 里每个音色集有一个 `pitch` 字段说明它的文件名用哪种约定；加新音色后用 `tools/check_pitch.py <名字>` 实测核对。

---

## 9. 物体识别

### 9.1 为什么用 YOLO-World
它是开放词汇检测器：类别用文字给（`model.set_classes([...])`），不需要训练，所以 pen、glasses、tablet 这些 COCO 里没有的类别也能直接用。代价是比封闭集检测器（如 YOLO11 的 COCO 模型）在常见类别上更不稳，置信度整体偏低。

### 9.2 模型的速度 / 准确度取舍（本机 M2 Pro，`mps`，实测每帧毫秒数）

| 模型 | 权重大小 | @640 | @960 | @1280 | 说明 |
|---|---|---|---|---|---|
| `yolov8s-worldv2` | 25 MB | 15 | 24 | 38 | 很快，全分辨率也能实时；开放词汇能力最弱 |
| `yolov8l-worldv2` | 94 MB | 69 | 116 | 195 | **当前使用**。官方指标明显更好；实时识别约 6–9 次/秒 |

（还有 m 和 x 两个尺寸没下载；x 约 140MB，会比 l 再慢约一半。）

输入分辨率同样关键：摄像头是 1280×720，缩到 640 后一支笔只剩几个像素宽。当前策略是**预览用 960，按快门时对定格帧再跑一次 1280**（约 0.35 秒，正好藏在快门闪白里），两次结果合并。

### 9.3 相关参数（`deskband/config.py`）

```python
DETECT_MODEL = "yolov8l-worldv2.pt"            # 找不到这个文件就用下面的备用
DETECT_MODEL_FALLBACK = "yolov8s-worldv2.pt"
DETECT_IMGSZ = 960        # 实时预览
SHOOT_IMGSZ = 1280        # 拍照时的精识别
DETECT_CONF = 0.25        # 低于这个分数的检测丢弃
```

每个乐器的 `detect=[...]` 是一组同义提示词，任何一个触发都算；`ALIASES` 把提示词映射回声部；`SHOW_AS` 决定屏幕上显示的名字（iPad 显示为 tablet）。同一声部的两个重叠框（IoU > 0.5）只保留分数高的（`vision.merge_duplicates`）。拍照时还会把"最近 0.5 秒内见过但这一帧没认出来"的物体补进去，用来对抗闪烁。

### 9.4 怎么调
1. 在 app 里把认不稳的物体放到镜头前，按几次 `s` 存图。
2. 跑 `tools/eval_prompts.py`（用法见第 2.1 节），对比提示词、阈值、分辨率、模型。
3. 改 config，重启。

画面在识别前做了水平镜像（像照镜子），检测和显示用的是同一份镜像后的帧。

---

## 10. 外部控制接口（硬件线和 AI 线都从这里接入）

### 10.1 总览

DeskBand 启动后在 **UDP 9000 端口**监听（`config.REMOTE_HOST = "0.0.0.0"`，同一局域网内的设备都能连；只想本机可连就改成 `"127.0.0.1"`）。

- **一个 UDP 包 = 一个 JSON 对象**，UTF-8。
- 每条指令都会向发送方回一个 JSON。
- 指令在端口线程里只是入队，由主循环在下一帧执行（延迟 ≤ 33ms），所以发什么都不会干扰音频。坏包只会得到一个 `{"ok": false, "error": ...}`，不会让程序崩。

### 10.2 指令

| 指令 | 作用 |
|---|---|
| `{"cmd":"ping"}` | 回 `{"ok":true,"pong":<时间戳>}`，用来测连通 |
| `{"cmd":"shoot"}` | 拍照（仅在预览状态有效） |
| `{"cmd":"retake"}` | 回到预览（仅在定格状态有效） |
| `{"cmd":"toggle"}` | 等同于按空格 |
| `{"cmd":"play","on":true}` | 演奏 / 暂停总开关，等同于快门右边的按钮。不带 `on`（或 `null`）= 切换。暂停时所有 `parts[x].on` 都是 false，但 `selected` 不变。Zybo mixer 模式下 BTN1 默认 mute 选中轨；桥接程序加 `--btn1-master` 可恢复旧的总开关映射。 |
| `{"cmd":"math","on":true}` | 数学旋律模式开 / 关，等同于 `m`。不带 `on`（或 `null`）= 切换。从下一小节生效 |
| `{"cmd":"place","name":"cup","complexity":0.7,"loudness":0.4}` | 把一件**已保存**的乐器移到舞台上的某个位置，两个值都是 0–1，可以只给一个。响度 0.5 = 声部原音量，复杂度 0.5 = 原样。只移动位置，不开关乐器（开关用 `select`） |
| `{"cmd":"view","stage":true}` | 切到舞台 / 摄像头画面，等同于 `tab`。不带（或 `null`）= 切换 |
| `{"cmd":"select","name":"cup","on":true}` | 开关乐器架上一件**已保存**的乐器，等同于点击那个槽。不带 `on`（或 `null`）= 切换。没保存过的会被忽略。**硬件按键选乐器用这个** |
| `{"cmd":"silence"}` | 乐器架全部关掉，保存的东西不丢（等同于按 `0`） |
| `{"cmd":"part","name":"cup","on":true}` | **强制**某个声部开/关，不管有没有保存过。`"on": null` = 取消强制，重新听乐器架的。`name` 必须是 `INSTRUMENTS` 的 key：`cup pen bottle book glasses "cell phone" laptop headphones` |
| `{"cmd":"sfx","file":"/绝对路径.wav","gain":0.6}` | 播放一个声音文件。**会等到下一个八分音符才响**（和 Mikutap 一样，所以永远在拍子上），经过混响和限幅器。支持 wav/aiff/flac 等 libsndfile 能读的格式，最长 20 秒，任意采样率。文件必须在**运行 DeskBand 的那台 Mac 上** |
| `{"cmd":"bpm","value":110}` | 改速度，60–180，立即生效 |
| `{"cmd":"style","chords":[...],"bpm":120}` | 换和弦循环，**在当前循环走完、回到开头时**生效，所以永远落在强拍上。格式见 10.4 |
| `{"cmd":"state"}` | 回一个状态包 |
| `{"cmd":"subscribe","hz":20}` | 之后 10 秒内以指定频率（1–60Hz）向发送方推状态包。要持续接收就每隔几秒重发一次 |

### 10.3 状态包

```json
{"type":"state","mode":"show","bpm":120.0,"bar":12,"step":6,"beat":1,"beat_phase":0.5,
 "chord":"G6","chord_index":1,
 "parts":{"cup":{"on":true,"glow":0.83},"pen":{"on":false,"glow":0.0}, "...":{}},
 "detected":["cup","tablet"],
 "playing":true,"math":false,"description":"A white ceramic mug with a chipped rim.",
 "saved":["pen","cup"],"selected":["cup"],
 "view":"camera","placed":{"cup":{"complexity":0.5,"loudness":0.5}}}
```

- `mode`：`preview`（实时预览）或 `show`（照片定格中）。两种状态下乐队都可能在演奏，是否有声看 `parts`
- `bar`：从启动起的小节数；`step`：小节内第几个十六分音符（0–15）；`beat`：第几拍（0–3）；`beat_phase`：当前这一拍走到哪（0–1）
- 以上时间量**已经扣掉了输出延迟**，对应"此刻耳朵听到的"
- `parts[x].on`：这个声部是否在乐队里；`parts[x].glow`：它刚发过声的程度，发声瞬间为 1，之后按约 0.22 秒的时间常数衰减，**直接拿去驱动 LED 亮度就是"跟着音乐闪"**
- `detected`：当前画面（或定格照片）里认出的东西，用的是屏幕上显示的名字
- `playing`：演奏 / 暂停总开关的状态
- `math`：数学旋律模式是否打开
- `view`：当前显示的是 `camera` 还是 `stage`；`placed`：每件已保存、放过位置的乐器在舞台上的坐标（0–1，和 `place` 指令一样）
- `description`：Gemini 对当前定格照片的描述；还没回来、出错、没设 `GEMINI_API_KEY` 或已回到预览时为 `null`
- `saved`：乐器架上已经保存的乐器，**顺序就是乐器架从上到下的顺序**（先拍到的在前）；`selected`：其中点亮的。两者用的都是 `INSTRUMENTS` 的 key
- 判断“现在有没有声音”看 `parts[x].on`（= 被选中 **且** 没有暂停），不要看 `mode`：预览状态下乐队也可以在演奏

**做灯光同步的建议**：UDP 有几毫秒到几十毫秒的抖动。要求不高就直接用 `glow` 和 `beat`。要求高（比如 LED 严格卡拍）就在设备端自己跑一个相位累加器：`phase += dt * bpm / 60`，每收到一个状态包用 `beat_phase` 轻轻校正一次，而不是每包硬跳。

### 10.4 style 的格式

```json
{"cmd":"style","bpm":120,"chords":[
  ["Fmaj7", 5, [53,57,60,64]],
  ["Em7",   4, [52,55,59,62]],
  ["Dm7",   2, [50,53,57,60]],
  ["Cmaj7", 0, [48,52,55,59]]
]}
```

每个和弦是 `[名字, 根音的音级, 排列]`：
- 名字：显示用，任意字符串
- 根音的音级：0–11，**0=C，1=C#，2=D，3=D#，4=E，5=F，6=F#，7=G，8=G#，9=A，10=A#，11=B**。贝斯弹的就是它
- 排列：3–5 个 MIDI 音符，每个必须在 40–76 之间（C3=60；即大约 E1 到 E4），钢琴滚的、吉他拨的、弦乐拉的都来自它
- 1–16 个和弦，每个占一小节

不合规会被拒绝并告诉你原因。`styles/default.json` 和 `styles/descending.json` 是两个现成的例子。

**重要的乐理约束**：旋律音始终来自 C 大调五声音阶，所以 `style` 给的和弦**必须是 C 大调（或 A 小调）里的和弦**才会好听：C、Dm、Em、F、G、Am 及其七和弦、加音和弦、挂留和弦。给一个带升降号的和弦（比如 Bb、E 大三和弦）旋律会和它打架。要支持转调需要改 `config.PENTATONIC`，目前不能在运行时改。

### 10.5 客户端示例

**Python（任何电脑）**

```python
import json, socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(2)
ADDR = ("192.168.x.x", 9000)          # 运行 DeskBand 的 Mac 的 IP；本机就写 127.0.0.1
def ask(obj):
    s.sendto(json.dumps(obj).encode(), ADDR)
    return json.loads(s.recvfrom(65535)[0])
print(ask({"cmd": "ping"}))
ask({"cmd": "shoot"})
ask({"cmd": "subscribe", "hz": 20})
while True:
    st = json.loads(s.recvfrom(65535)[0])
    print(st["beat"], st["chord"], st["parts"]["cup"]["glow"])
```

**命令行**

```bash
.venv/bin/python tools/remote_test.py watch
```

```bash
.venv/bin/python tools/remote_test.py style styles/descending.json
```

其它子命令：`ping / shoot / retake / toggle / silence / state / select cup [on|off] / part cup on|off|auto / sfx 文件 [增益] / bpm 110`。连别的机器：`DESKBAND_HOST=192.168.x.x .venv/bin/python tools/remote_test.py ping`。

**MicroPython（ESP32 一类带 WiFi 的板子）**

```python
import socket, json
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ADDR = ("192.168.x.x", 9000)
s.sendto(b'{"cmd":"subscribe","hz":20}', ADDR)
s.settimeout(0.2)
while True:
    try:
        st = json.loads(s.recv(2048))
        led.duty(int(st["parts"]["cup"]["glow"] * 1023))
    except OSError:
        s.sendto(b'{"cmd":"subscribe","hz":20}', ADDR)     # 超时就重新订阅
```

**没有网络、只有串口的板子（Zybo 的 UART、USB 串口的胸牌）**：在 Mac 上跑一个十几行的桥接脚本，把串口的每一行转成 UDP 包，把状态包转回串口。需要先 `.venv/bin/pip install pyserial`。

```python
import json, socket, serial                      # tools 目录下自己建一个 serial_bridge.py
ser = serial.Serial("/dev/tty.usbserial-XXXX", 115200, timeout=0.01)
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); udp.settimeout(0.01)
ADDR = ("127.0.0.1", 9000)
udp.sendto(b'{"cmd":"subscribe","hz":20}', ADDR); last = 0
import time
while True:
    line = ser.readline().strip()                # 板子发来一行，例如 SHOOT 或 PART cup 1
    if line == b"SHOOT": udp.sendto(b'{"cmd":"toggle"}', ADDR)
    try:
        st = json.loads(udp.recv(65535))
        if st.get("type") == "state":            # 压成板子好解析的短格式：拍号,相位,7 个声部的亮度
            glows = ",".join(str(int(p["glow"] * 255)) for p in st["parts"].values())
            ser.write(f"{st['beat']},{int(st['beat_phase']*255)},{glows}\n".encode())
    except socket.timeout:
        pass
    if time.time() - last > 5: udp.sendto(b'{"cmd":"subscribe","hz":20}', ADDR); last = time.time()
```

### 10.6 模拟器（不需要 DeskBand、不需要 Mac）

```bash
python3 tools/remote_sim.py
```

零依赖，任何系统的 Python 3 都能跑。它实现了同样的协议：假的 120BPM 时钟、循环走四个和弦、接受所有指令并打印出来，`shoot` 之后假装照片里有 cup、bottle、glasses。**硬件和 AI 脚本先对着它开发，最后把 IP 换成真机即可。**

---

## 11. 硬件线（Hank）

目标：让评委第一眼看到"这是一个有硬件的项目"。优先级：**胸牌 > Zybo > LeLamp**，QNX 不建议做。

### 11.1 Solana：Best Badge Hack（$2500，单项最高）
改造 Hack the North 的胸牌。规则明说可以和主项目无关，但做成 DeskBand 的无线小控制器，或者让胸牌的屏幕和灯跟着节拍跳，就正好能串进 demo。
- 如果胸牌能联网：直接用第 10.5 节的 MicroPython 示例。按键 → `{"cmd":"toggle"}`；订阅状态 → 用 `beat`、`beat_phase` 让灯卡拍，用 `parts[...].glow` 让每个乐器对应一颗灯，用 `chord` 在屏幕上显示当前和弦。
- 如果只能走 USB 串口：用第 10.5 节的串口桥。
- 先确认的事：胸牌是什么芯片、能不能刷固件、有没有 WiFi、有什么外设（屏、LED、按键）。

### 11.2 Zybo 控制台（不对应具体奖项，但决定主奖评委对硬件的印象）

> 2026-09-19 Hank 更新：原来的“PL 只做按键消抖”方案已被完整的 FPGA 实时音乐引擎取代。

- PL 端拥有 100 MHz 主时钟、可编程 BPM/十六分音符时钟、七轨 16-step sequencer、step/beat/bar 量化、事件 FIFO、七路 envelope、七路 triangle LFO，以及 16-bit maximal LFSR + 七路无除法 Euclidean/Bresenham bar generator。发生器每小节自动工作，只会从 Mac 给出的合法事件中选取 1/2、3/4 或全部，保留下拍并固定 bass/strings，因此变化可控且不会生成错误音高。
- Cortex-A9 bare-metal 固件通过 AXI-Lite 控制 PL，并经 UART1/J12 和 Mac 双向通信。Mac 只保留视觉、作曲和音频合成；音符何时触发由 FPGA 决定。
- BTN0 控制拍照/重拍；乐队由保存架决定，重拍返回摄像头后音乐继续。SW3=0 是 mixer：SW2:0 选轨，BTN1 下一拍 mute、BTN2 硬件 fade、BTN3 LFO。SW3=1 是 performance：BTN1 下一小节 lock/unlock 该轨生成结果、BTN2 下一小节切换 sparse/normal/full、BTN3 排队一个 full-density fill bar；fill 后自动生成继续。运行时 LED 显示十六步位置。
- RTL、AXI、固件协议和 Mac 协议测试均已通过；完整 Zybo implementation 在 100 MHz 下 timing/DRC 通过（setup WNS +0.116 ns、hold WHS +0.039 ns、0 unrouted nets），并已生成 4,213,968-byte `fpga/build/BOOT.BIN`。
- **旧版 2026-09-19 真机验证通过**：Zybo Z7-20 的双向 UART、PL ID、16 个连续 sequencer event、各轨 event mask、envelope endpoint 和 LFO movement 全部通过。旧镜像已写入 QSPI 并回读验证；它不包含本次自动 bar generator。
- 新版 PL ID 是 `44420101`，`tools/zybo_smoke.py` 会检查 32 个 event：第一小节必须等于 base pattern，第二小节必须逐位等于主机镜像的 LFSR/Euclidean 结果，并继续检查 envelope/LFO。
- 新版 `BOOT.BIN` SHA-256：`7c45b9c5c9ed8483f13b09867c2b388ea42623f7445737145fd5866e097bd5da`。当前 WSL 没看到 `/dev/bus/usb` 或串口设备，因此尚未覆盖 QSPI。
- **剩余工作**：把新版 `BOOT.BIN` 重刷 QSPI并通过新版 smoke test；拿到 Mac 后运行 DeskBand 和 `tools/zybo_bridge.py`，检查自动小节变化、两种按钮模式和长时间无 FIFO overflow。J12 板载 FT2232 已是 USB-UART，不需要 TTL 串口模块或网线。接线及命令见 `fpga/README.md`。

### 11.3 Human Computer Lab：LeLamp / Bracket Bot
去展台借硬件：让台灯机器人跟着节奏点头、转向正在发声的物体。画面很出效果。先去问一句能不能借到，借到再决定做不做。
- 点头：用 `beat_phase`（每拍一次）或 `bar`（每小节一次）。
- 转向正在发声的物体：状态包目前**只有声部的发声程度，没有物体在画面里的位置**。需要的话在 `main.py` 的 `state_dict()` 里给 `parts[n]` 加一个 `"x"` 字段（该物体框中心的横坐标 / 1280），数据在 `self.captured[1]` 的每个 `Detection.box` 里，是五分钟的改动。

### 11.4 QNX（嵌入式 + AI）
硬性要求是 QNX 系统加上他们的 AI 模块，36 小时内风险很大。**不建议做**，除非已经有 QNX 经验。

---

## 12. AI / 音乐 API 线（Richard）

> 已接入 DeskBand 本体：ElevenLabs 人声乐器（headphones，见 7.2）和 Gemini 照片描述（定格时显示在标题下面，只显示、不影响音乐），key 用环境变量 `ELEVENLABS_API_KEY` / `GEMINI_API_KEY`。下面是最初的分工计划。

优先级：**ElevenLabs > Gemini > OMNI**，Baseten 可选。所有 API key 放环境变量，脚本放 `tools/` 或新建 `integrations/`，不要碰 `deskband/` 里的音频代码，全部通过第 10 节的 UDP 指令接入。

### 12.1 MLH：ElevenLabs（和音乐最贴合）
两个方向，可以都做：
- **按物体生成专属音效**：识别到杯子 → 调 ElevenLabs 的音效生成接口生成一个"叮" → 存成 wav → 发 `{"cmd":"sfx","file":"...","gain":0.5}`。DeskBand 会把它对齐到下一个八分音符、过混响播出来。脚本的触发条件：订阅状态包，发现 `mode` 从 `preview` 变成 `show` 时，读 `detected` 列表，为每个物体播一次。生成有延迟，建议**提前为七种物体各生成几个并缓存**到 `cache/sfx/`，演示时只播不生成。
- **AI 主持人**：用 TTS 报出当前段落（"现在加入的是大提琴……"），同样用 `sfx` 指令播。人声建议 `gain` 0.8 左右，并且挑乐器少的时候播。
- 限制：`sfx` 是一次性播放，没有音高概念。如果想让生成的"叮"**作为一件有音高的乐器**被作曲器演奏，需要生成一组不同音高的采样，放进一个文件夹，在 `config.SAMPLE_SETS` 里加一项（参考 `bells` 那一项：`dir`、`glob`、`pitch` 文件名音高约定），再把某个物体的 `voice` 指过去。

### 12.2 MLH：Gemini API
根据当前桌面布局让 Gemini 生成和弦进行或编曲建议，切换"风格"时用。
- 输入：状态包里的 `detected`（桌上有什么），可以再加上 `cache/shots/` 里最新那张照片。
- 输出：要求 Gemini **只返回第 10.4 节格式的 JSON**。提示词里必须写清楚：调性固定为 C 大调 / A 小调；只能用 C Dm Em F G Am 及其七和弦、加音、挂留；每个和弦给 `[名字, 根音音级 0–11, 3–5 个 MIDI 音符(40–76, C3=60)]`；4 或 8 个和弦；相邻和弦的排列尽量保留共同音、声部级进。把 `styles/default.json` 贴进去当示例。
- 拿到后直接发 `style` 指令。服务端会校验格式，不合规会返回错误原因，可以把错误原样喂回给 Gemini 让它改。
- 也可以让它顺便给一个 `bpm`（建议限制在 90–130）。

### 12.3 Huawei：OMNI Live
要求视觉、音频、语言三种模态都用上，恰好是 DeskBand 本来就有的结构：摄像头、音乐，再加一个语音指令（比如说一句"来点爵士"）。要换成他们的模型 API。
- 最小实现：麦克风 → 他们的语音/多模态接口 → 解析出意图 → 映射成指令。"拍照"→`shoot`；"重来"→`retake`；"快一点/慢一点"→`bpm`；"不要鼓"→`{"cmd":"part","name":"book","on":false}`；"来点爵士"→发一个预先写好的 `styles/jazz.json`。
- 注意：**如果 Aaron 用蓝牙耳机听，任何程序打开耳机的麦克风都会让耳机音质崩掉**。语音输入请用 MacBook 内置麦克风，并且演示时用扬声器输出。

### 12.4 Baseten
把 YOLO-World 推理部署到 Baseten 上。注意延迟，只作备选方案，本地推理继续保留。
- 接入点只有一个函数：`deskband/vision.py` 的 `Vision.detect(frame, imgsz)`，输入一帧 BGR 图像，返回 `Detection(name, conf, [x0,y0,x1,y1], alias)` 的列表。远端版本可以只用在**拍照时的那一次精识别**（`main.py` 的 `shoot()` 里调用 `self.vision.detect(frame, C.SHOOT_IMGSZ)` 的地方），这样网络延迟藏在快门动画里，预览仍然走本地。
- 它顺便可能解决第 2.1 节的识别问题：云上可以跑 x 尺寸的模型。

### 12.5 OpenAI
评审要求讲清楚 Codex 怎么帮助了开发，我们没有用它，讲不出真实的故事，**不建议报**。

### 12.6 顺手的
- **MLH：GoDaddy 域名**：注册一个 deskband.xxx，花 5 分钟，谁有空谁做。
- **Aramco 新手奖**：如果三个人参加过的黑客松都不超过 1 次，自动有资格参评。

---

## 13. Git 与协作约定

- 仓库：`https://github.com/mu142857/DeskBand.git`，分支 `main`。目前的提交都是 Aaron 用 GitHub Desktop 做的。
- GitHub Desktop 流程：左侧 Changes 勾选文件 → 填 Summary → Commit to main → 顶部 Push origin。如果 Changes 是空的但明明改过文件，看左下角有没有 **Stashed Changes**，点进去 Restore。
- **每个人用自己的 GitHub 账号提交自己写的部分**。
- 提交前扫一眼 Changes 列表，不应该出现 `cache/`、`weights/`、`*.pt`、`*.wav`、`dist/`、`.venv/`。如果出现了，说明 `.gitignore` 被改坏了，先修它。单个文件超过 100MB GitHub 会直接拒绝。
- `cache/shots/` 里的照片有人脸，只在本机用。

---

## 14. 故障排查（全部是这次真实踩过的坑）

| 现象 | 原因 | 处理 |
|---|---|---|
| 首次运行下载模型报 `SSL: CERTIFICATE_VERIFY_FAILED` | python.org 版 Python 不带 CA 证书 | `main.py` 开头已经把 `SSL_CERT_FILE` 指向 certifi；单独跑脚本时手动 `export SSL_CERT_FILE=$PWD/.venv/lib/python3.11/site-packages/certifi/cacert.pem` |
| 双击 `.app` 一闪就没，日志里 `have 'arm64', need 'x86_64'` | 启动器如果是 shell 脚本，Finder 会用 Rosetta（Intel 模式）启动它，而 venv 里的库只有 arm64 | 已解决：启动器是 `tools/launcher.c` 编译出的 arm64 原生程序。重新 `tools/build_app.sh` |
| 从 `.app` 启动后窗口里一直 "waiting for camera access"，也不弹权限窗 | ① 摄像头必须在**主线程**打开，macOS 才会弹窗；② 如果 app 的主程序是脚本，系统看到的进程身份是 `/bin/bash`，无法把权限算到 DeskBand 头上 | 两个都已解决（`vision.open_camera()` 在主线程调用；原生启动器 + ad-hoc 签名）。若仍不行：系统设置 → 隐私与安全性 → 摄像头 里打开 DeskBand；或者从终端运行 |
| `open dist/DeskBand.app` 报 `error -600` | 刚杀掉旧进程，系统还没回收 | 等一两秒再开 |
| 严重破音，但峰值没超 | **混响延迟线的 bug**：`Delay.read()` 返回了缓冲区的视图，紧接着的 `write()` 覆盖了它，输出在对错两种状态间跳变 | 已解决（`.copy()`）。`tests/test_reverb.py` 专门防它复发。**教训：用 numpy 切片做环形缓冲时，读出来的东西如果之后还要用，必须拷贝** |
| 破音，且乐器越多越严重 | 总线过载：每个声部单独就接近满幅，叠加后被 `tanh` 硬压 | 已解决（见 7.3）。**教训：量电平要量限幅器之前的，不能只看输出峰值** |
| 只在蓝牙耳机上有毛刺 | 引擎 44.1kHz、设备 48kHz，PortAudio 在低延迟模式下做实时变采样 | 已解决：`config._device_rate()` 启动时读设备原生采样率；`latency="high"`、块大小 1024 |
| 蓝牙耳机音质突然变得像电话 | 有程序打开了耳机的麦克风，macOS 切到了通话模式 | 与本程序无关。关掉占用麦克风的程序，或者换扬声器 |
| 刚启动的头几十毫秒卡一下 | numpy / scipy 首次调用的预热 | 已解决：`Engine.warm_up()` |
| 改了输出设备后没声音或音调不对 | 采样率在 import 时读一次 | 重启 DeskBand |
| 某个采样乐器没声音，其它正常 | 这台机器上没有对应的音色库或 `cache/` | 看启动日志里 `[sampler]` 那几行各加载了多少个音；0 个就是没找到。程序会静音该声部而不是崩溃 |
| 远程端口没反应 | 端口被占用（日志里会有 `remote control disabled`）；或者 macOS 防火墙拦了外部连接；或者 IP 写错 | 先在本机 `tools/remote_test.py ping`；再查防火墙；`config.REMOTE_PORT` 可改 |
| 某个物体认不出来 | 见第 2.1 和第 9 节 | `s` 存图 → `tools/eval_prompts.py` |

---

## 15. 待办清单（按建议的优先级）

1. **查清并修复"换大模型后笔认不出来"**（第 2.1 节，工具和样本照片都已就位，预计半小时内）。
2. 在真实摄像头下验证眼镜、iPad、笔、书、瓶子的识别率，必要时换提示词或换物体。
3. Hank：Zybo Z7-20 的真机 UART/FPGA 验收和 QSPI 写入已完成；按 `fpga/README.md` 完成 QSPI 冷启动，再在 Mac 上做音频闭环验收。
4. Richard：先做 ElevenLabs 的预生成音效 + `sfx`，再做 Gemini → `style`。
5. 调试面板加上限幅前电平（`engine.pre_peak`）和限幅量（`engine.gain_reduction_db`）的显示，这两个值引擎里已经有了，只差画出来（`main.py` 的 `draw_debug`）。
6. "晃动交互"：最初的设想是拿起物体摇晃 → 该声部变密、变亮。改成拍照模式后物体是定格的，这个交互没有了。可选的替代：定格演奏期间**继续看实时画面**，如果某个物体在实时画面里的移动速度大，就给它的声部加密度和亮度（`Pattern` 需要一个 `energy` 参数；`Vision.last_seen` 里有每个物体最新的框，前后两次的位移除以时间就是速度）。没时间就不做。
7. README 里的截图 / 演示视频；Devpost 文案。
8. 演示前检查表：
   - 输出设备切到扬声器或音箱，**然后**再启动 DeskBand
   - 音量调好；环境光足够；摄像头对着的背景尽量干净
   - 用 `dist/DeskBand.app` 启动，按 `f` 全屏
   - 按 `d` 确认 `xruns 0`、识别帧率正常，再按 `d` 关掉
   - 准备好一套确定能认出来的物体，提前试拍
   - 硬件和 AI 脚本先 `ping` 通

---

## 16. 给 AI 助手提问的方式

把这份文档全文贴进去，再贴上你关心的那个源码文件，然后直接问。几个好用的问法：

- "我要让一块 ESP32 的 8 颗 LED 分别跟着 7 个声部和节拍闪，按第 10 节的协议帮我写 MicroPython。"
- "按第 10.4 节的约束，写一段给 Gemini 的提示词，让它根据桌上的物体列表返回一个 style JSON。"
- "`tools/eval_prompts.py` 的输出是这样的：……，我该怎么改 `config.py` 里的提示词和阈值？"
- "我想加第八个物体 `mouse`，乐器用 Logic 里的某个采样，按第 7.5 和第 8 节告诉我每一步改哪里。"
