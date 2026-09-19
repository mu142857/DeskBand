"""Write INSTRUMENTS.txt: a plain-language map of object -> instrument -> where
the sound lives in Logic's library and on disk. Generated from deskband/config.py."""

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C

LOGIC = "/Library/Application Support/Logic"
OBJECT_CN = {"cup": "杯子", "pen": "笔", "bottle": "瓶子", "book": "书",
             "glasses": "眼镜", "cell phone": "手机", "laptop": "笔记本电脑 / 平板",
             "mouth": "张开的嘴"}
NOTE = "C C# D D# E F F# G G# A A# B".split()


def exists(path):
    return "有" if os.path.exists(path) else "没有"


def piano_info():
    for folder in C.CONCERT_GRAND:
        if os.path.exists(os.path.join(folder, "keymap.json")):
            soft = folder.endswith("_soft")
            return dict(
                name="音乐厅大钢琴 Concert Grand Piano" + ("（弱奏层，再加一点低通，做出朦胧感）" if soft else ""),
                logic="Logic 音色库 → 钢琴 → 音乐厅大钢琴",
                source=f"{LOGIC}/EXS Factory Samples/Studio Piano/Concert Grand Piano/",
                used=f"{folder}/   （88 个音，一个音一个 wav，由 tools/exs_extract.py 从上面的打包文件里解出来）")
    s = C.SAMPLE_SETS["piano"]
    return dict(name="Yamaha 大钢琴", logic="Logic 音色库 → 钢琴 → Yamaha Grand Piano",
                source=s["dir"] + "/", used=s["dir"] + "/" + s["glob"])


def strings_info():
    if os.path.exists(os.path.join(C.KINGS_CROSS, "keymap.json")):
        return dict(
            name="国王十字 King's Cross（录音室弦乐合奏，延音）",
            logic="Logic 音色库 → 录音室弦乐 → Section Instruments → 国王十字",
            source=f"{LOGIC}/EXS Factory Samples/Studio Strings/   （小提琴1、小提琴2、中提琴、大提琴、低音提琴五个打包文件）",
            used=f"{C.KINGS_CROSS}/   （由 tools/make_kings_cross.py 把五个声部叠在一起解出来）")
    s = C.SAMPLE_SETS["strings"]
    return dict(name="流行弦乐 EXS Strings 2（国王十字还没解包时的替代）",
                logic="Logic 音色库 → 管弦乐器 → 弦乐 → 流行弦乐",
                source=s["dir"] + "/", used=s["dir"] + "/" + s["glob"])


def simple(kind, name, logic):
    s = C.SAMPLE_SETS[kind]
    n = len(glob.glob(os.path.join(s["dir"], s["glob"])))
    return dict(name=name, logic=logic, source=s["dir"] + "/", used=f"{s['dir']}/{s['glob']}   （{n} 个文件）")


def info(voice):
    if voice == "piano":
        return piano_info()
    if voice == "strings":
        return strings_info()
    if voice == "guitar":
        return simple("guitar", "古典原声吉他 Classical Acoustic Guitar", "Logic 音色库 → 吉他 → 古典原声吉他")
    if voice == "bass":
        return simple("bass", "低音提琴拨奏 Double Bass (Pizzicato)", "Logic 音色库 → 管弦乐器 → 弦乐 → 流行弦乐 这一套里的低音提琴拨奏采样")
    if voice == "bells":
        return simple("bells", "铁琴 Glockenspiel", "Logic 音色库 → 管弦乐器 → 打击乐器 → 铁琴")
    if voice == "drums":
        return dict(name="困住热量 Trap Heat 鼓机（弱奏）", logic="Logic 音色库 → 鼓机 → 困住热量",
                    source=C.DRUM_DIR + "/", used="用到的：" + "、".join(f"{k}={v}" for k, v in C.DRUMS.items() if k in ("kick", "rim", "snap", "hat", "hat_open")))
    if voice == "keys":
        return dict(name="柔和电钢琴（程序合成，不用采样）", logic="无，代码在 deskband/synth.py 里的 keys 音色",
                    source="—", used="—")
    if voice == "sax":
        return dict(name="录音室上低音萨克斯 Studio Baritone Sax（主旋律）", logic="Logic 音色库 → 录音室管乐 → 单件乐器 → Studio Baritone Sax",
                    source="/Library/Application Support/Logic/EXS Factory Samples/Studio Horns/Studio Baritone Sax.caf",
                    used=f"{C.BARI_SAX}/   （tools/make_bari_sax.py 抽出来的 22 个单音；现在{exists(os.path.join(C.BARI_SAX, 'keymap.json'))}抽好的）")
    if voice == "vocal":
        return dict(name="人声 Voices（ElevenLabs 生成的 \"ooh\" 长音）", logic="无，不来自 Logic",
                    source="ElevenLabs 音效生成接口，提示词在 deskband/config.py 的 VOCAL_PROMPTS",
                    used=f"{C.VOCAL_DIR}/   （第一次启动时生成，测音高后微调到半音；现在{exists(os.path.join(C.VOCAL_DIR, 'keymap.json'))}生成好的）")
    return dict(name=voice, logic="", source="", used="")


def main():
    L = []
    L.append("DeskBand 乐器对照表")
    L.append("=" * 60)
    L.append("")
    L.append(f"速度 {C.BPM} BPM，每个和弦 {C.BARS_PER_CHORD} 小节，循环：")
    for name, root, voicing in C.CHORDS:
        L.append(f"    {name:10s} 钢琴排列 {' '.join(NOTE[m % 12] for m in voicing):10s} 贝斯根音 {NOTE[root]}")
    L.append("旋律音只用 C 大调五声音阶（C D E G A），所以怎么随机都不跑调。")
    L.append("")
    L.append("一、什么东西对应什么乐器")
    L.append("-" * 60)
    for obj, spec in C.INSTRUMENTS.items():
        i = info(spec["voice"])
        L.append(f"【{OBJECT_CN.get(obj, obj)} {obj}】 → {i['name']}")
        L.append(f"    摄像头认这些词：{' / '.join(spec['detect'])}" if spec["detect"] else
                 "    怎么认：MediaPipe 人脸关键点，最大的那张脸张着嘴拍照（deskband/face.py）")
        L.append(f"    在 Logic 里：{i['logic']}")
        L.append(f"    原始音色库：{i['source']}")
        L.append(f"    程序实际读：{i['used']}")
        L.append("")
    L.append("二、想换音色，库里还有这些")
    L.append("-" * 60)
    L.append("钢琴（都在 Logic 音色库 → 钢琴 里）：")
    for cn, exs in [("音乐厅大钢琴 Concert Grand", "z_Internal/Studio Piano/Concert Grand Piano.exs"),
                    ("工作室大钢琴 Studio Grand", "z_Internal/Studio Piano/Studio Grand Piano.exs"),
                    ("复古立式钢琴 Vintage Upright", "z_Internal/Studio Piano/Vintage Upright Piano.exs"),
                    ("施坦威大钢琴 Steinway Grand", "01 Acoustic Pianos/Steinway Grand Piano 2.exs")]:
        path = f"{LOGIC}/Sampler Instruments/{exs}"
        L.append(f"    {cn:32s} {exists(path)}   {path}")
    L.append("弦乐（Logic 音色库 → 录音室弦乐 → Section Instruments）：")
    for cn, exs in [("国王十字 King's Cross = String Ensemble", "String Ensemble.exs"), ("迪斯科弦乐 Disco Strings", "Disco Strings.exs"),
                    ("唱作人 Singer Songwriter", "Singer Songwriter.exs"), ("小型弦乐组 Small Section", "Small Section.exs")]:
        path = f"{LOGIC}/Sampler Instruments/Studio Strings/Section Instruments/{exs}"
        L.append(f"    {cn:40s} {exists(path)}   {path}")
    L.append("")
    L.append("怎么换：这些都是 Logic 的打包音色（.exs + .caf）。先用工具解成一个音一个 wav：")
    L.append('    .venv/bin/python tools/exs_extract.py "<上面的 .exs 路径>" "<对应的采样文件夹>" cache/<名字> --velocity 45')
    L.append("然后把 deskband/config.py 里的 CONCERT_GRAND（钢琴）或 KINGS_CROSS（弦乐）指到那个文件夹。")
    L.append("--velocity 是力度层：45 左右是弱奏（朦胧），84 左右是中强。")
    L.append("")
    L.append("三、效果")
    L.append("-" * 60)
    L.append(f"    大厅混响（deskband/fx.py）：room {C.REVERB['room']}，damp {C.REVERB['damp']}，预延迟 {C.REVERB['predelay_ms']:.0f} ms")
    L.append(f"    钢琴低通：{C.PIANO_LOWPASS_HZ} Hz（调低更闷、更远；0 = 关）")
    on = lambda k: "开" if C.BACKING[k] else "关"
    L.append(f"    背景层：黑胶噪声 {on('vinyl')}，沙锤/rim {on('perc')}，低音铺底 {on('sub')}（开关在 deskband/config.py 的 BACKING）")
    L.append("")
    L.append("所有声音都来自这台 Mac 上 Logic Pro / GarageBand 自带的音色库，原地读取，不进代码仓库。")
    path = os.path.join(C.ROOT, "INSTRUMENTS.txt")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
