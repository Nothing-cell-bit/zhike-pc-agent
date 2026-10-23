"""Re-cut the real demo around speech, adding chat-to-marketing evidence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tmp/tooldeps/edge-tts-7.3.1'))
import edge_tts

OUT = ROOT / 'output/competition-video-tight-20261023'
PREVIOUS = ROOT / 'output/competition-video-natural-20261023'
ORIGINAL = ROOT / 'output/competition-video-voice-20261023'
FFMPEG, FFPROBE = shutil.which('ffmpeg'), shutil.which('ffprobe')
OUT.mkdir(parents=True, exist_ok=True)
base = json.loads((ORIGINAL / 'voice-plan.json').read_text(encoding='utf-8'))
sources = json.loads((ROOT / 'output/competition-video-full-20261023/edit.json').read_text(encoding='utf-8'))
fresh = {p['name']: p for p in json.loads((OUT / '新补录.json').read_text(encoding='utf-8'))}


def command(args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                          encoding='utf-8', errors='replace')


def duration(path):
    return float(command([FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'default=nw=1:nk=1', str(path)]).stdout)


def original(p):
    return {**p, 'source': sources[p['source_chapter']], 'source_length': p['duration'],
            'audio': str(PREVIOUS / f'voice-{p["index"]:02}.mp3')}


plan = [original(p) for p in base[:21]]
extra = [
    ('chat-to-marketing', '从对话到营销创作', '咨询结束后，仍能把这次聊天转为营销创作任务。'),
    ('import-chat-needs', '自动带入已确认的客户需求', '产品、场景和预算自动带入；未确认的人群，仍需补充。'),
    ('selected-chat-materials', '勾选具体聊天作为创作素材', '还可以勾选具体聊天，让文案回应客户真实的用途和顾虑。'),
    ('three-platform-overview', '同一份需求 · 三类文案', '同一份需求，支持三类文案，分别适配不同发布平台。'),
    ('wechat-selection', '公众号 · 深度文章', '公众号生成深度文章，分节讲清选购依据和适用条件。'),
    ('xiaohongshu-selection', '小红书 · 场景笔记', '小红书生成场景笔记，把出差办公等需求转成场景建议。'),
    ('moments-selection', '朋友圈 · 自然短文', '朋友圈生成自然短文，保留重点，搭配产品和场景图片。'),
]
for name, title, narration in extra:
    source = fresh[name]
    # Skip a few initial frames before the selected radio has settled.
    start = .3 if name.endswith('selection') else 0
    plan.append({'source': source, 'source_in': start,
                 'source_length': source['duration'] - start,
                 'title': title, 'narration': narration})
preview = original(base[21])
preview['narration'] = '这里预览的是已有独立案例，文案与配图一起检查。'
preview.pop('audio')
plan.append(preview)
plan.extend(original(p) for p in base[22:])
for index, p in enumerate(plan, 1):
    p['index'] = index
    p.setdefault('audio', str(OUT / f'new-voice-{index:02}.mp3'))


async def synthesize():
    sem = asyncio.Semaphore(2)
    async def one(p):
        dest = Path(p['audio'])
        if dest.exists() and dest.stat().st_size > 1000:
            return
        async with sem:
            for attempt in range(2):
                try:
                    await asyncio.wait_for(edge_tts.Communicate(
                        p['narration'], 'zh-CN-XiaoxiaoNeural', rate='-5%', pitch='-2Hz'
                    ).save(str(dest)), timeout=40)
                    print(f'new narration {p["index"]} ready', flush=True)
                    return
                except Exception:
                    if attempt:
                        raise
                    await asyncio.sleep(1)
    await asyncio.gather(*(one(p) for p in plan))


def prepare_timing(p):
    length = duration(p['audio'])
    result = command([FFMPEG, '-hide_banner', '-i', p['audio'], '-af',
                      'silencedetect=noise=-42dB:d=0.10', '-f', 'null', '-'])
    silence = re.findall(r'silence_(start|end):\s*([0-9.]+)', result.stderr)
    leading, ending = 0.0, length
    if len(silence) >= 2 and silence[0][0] == 'start' and float(silence[0][1]) < .02:
        leading = max(0.0, float(silence[1][1]) - .065)
    if len(silence) >= 2 and silence[-1][0] == 'end' and abs(float(silence[-1][1]) - length) < .15:
        if silence[-2][0] == 'start':
            ending = min(length, float(silence[-2][1]) + .09)
    intervals = []
    silence_start = None
    for kind, value in silence:
        if kind == 'start':
            silence_start = float(value)
        elif silence_start is not None:
            stop = float(value)
            if stop - silence_start > .50:
                start_cut, end_cut = silence_start + .13, stop - .13
                if start_cut >= leading and end_cut <= ending:
                    intervals.append((start_cut, end_cut))
            silence_start = None
    exclude = '+'.join(f'between(t,{a:.6f},{b:.6f})' for a, b in intervals)
    expression = f'between(t,{leading:.6f},{ending:.6f})'
    if exclude:
        expression += f'*not({exclude})'
    cleaned = OUT / f'clean-voice-{p["index"]:02}.wav'
    original_audio = p['audio']
    command([FFMPEG, '-y', '-v', 'error', '-i', original_audio, '-af',
             f"aselect='{expression}',asetpts=N/SR/TB", '-ar', '48000', str(cleaned)])
    speech = duration(cleaned)
    if speech < .5:
        raise ValueError('Invalid voice activity interval')
    # Keep a natural 0.28-second break rather than padding to old shot lengths.
    p.update(audio=str(cleaned), original_audio=original_audio,
             compressed_internal_silences=intervals,
             audio_start=0, audio_end=speech, speech_seconds=speech,
             duration=math.ceil((speech + .28) * 30) / 30)
    return p


ASS = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Tag,Microsoft YaHei,25,&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,-1,0,0,0,100,100,0,0,3,8,0,9,24,24,16,1
Style: Caption,Microsoft YaHei,34,&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,0,0,0,0,100,100,0,0,3,8,0,2,80,80,26,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''


def encode(p):
    stem = f'part-{p["index"]:02}'
    source = p['source']
    frames = source['frames']
    entries = []
    for i, f in enumerate(frames):
        next_t = frames[i + 1]['t'] if i + 1 < len(frames) else source['duration']
        entries.extend([f"file '{(Path(source['dir']) / f['file']).as_posix()}'",
                        f'duration {max(.01, next_t - f["t"]):.6f}'])
    entries.append(f"file '{(Path(source['dir']) / frames[-1]['file']).as_posix()}'")
    (OUT / (stem + '.concat')).write_text('\n'.join(entries), encoding='utf-8')
    (OUT / (stem + '.ass')).write_text(ASS +
        f'Dialogue: 0,0:00:00.00,0:01:00.00,Tag,,0,0,0,,{p["title"]} | 演示录屏\n' +
        f'Dialogue: 0,0:00:00.00,0:01:00.00,Caption,,0,0,0,,{p["narration"]}\n', encoding='utf-8-sig')
    ratio = p['duration'] / p['source_length']
    command([FFMPEG, '-y', '-v', 'error', '-i', p['audio'], '-af',
             f'apad,atrim=duration={p["duration"]}', '-ar', '48000', '-ac', '1',
             str(OUT / f'aligned-{p["index"]:02}.wav')])
    filters = (
        f'[0:v]trim=start={p["source_in"]}:duration={p["source_length"]},'
        f'setpts=(PTS-STARTPTS)*{ratio:.8f},'
        'scale=1920:1080:force_original_aspect_ratio=increase:force_divisible_by=2,'
        f'crop=1920:1080:0:0,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=1,subtitles={stem}.ass[v]'
    )
    command([FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', stem + '.concat',
             '-filter_complex', filters, '-map', '[v]', '-an',
             '-frames:v', str(round(p['duration'] * 30)), '-r', '30', '-c:v', 'libx264', '-preset', 'veryfast',
             '-crf', '19', '-threads', '2', '-pix_fmt', 'yuv420p', stem + '.mp4'], cwd=OUT)
    print(f'encoded {stem}', flush=True)
    return stem + '.mp4'


def stamp(t):
    n = round(t * 1000)
    return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'


def build():
    with ThreadPoolExecutor(max_workers=2) as pool:
        timed = list(pool.map(prepare_timing, plan))
        clips = list(pool.map(encode, timed))
    listing = OUT / 'join.concat'
    listing.write_text('\n'.join(f"file '{clip}'" for clip in clips), encoding='utf-8')
    joined = OUT / 'joined-unbalanced.mp4'
    command([FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
             '-c', 'copy', str(joined)])
    audio_listing = OUT / 'audio.concat'
    audio_listing.write_text('\n'.join(f"file 'aligned-{p['index']:02}.wav'" for p in timed), encoding='utf-8')
    audio_joined = OUT / '完整旁白.wav'
    command([FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(audio_listing),
             '-c:a', 'pcm_s16le', str(audio_joined)])
    measure = command([FFMPEG, '-hide_banner', '-i', str(audio_joined), '-af',
                       'loudnorm=I=-18:TP=-1.5:LRA=7:print_format=json', '-vn', '-f', 'null', '-'])
    m, _ = json.JSONDecoder().raw_decode(measure.stderr[measure.stderr.rfind('{'):])
    for key in ['input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset']:
        if not math.isfinite(float(m[key])):
            raise ValueError('Non-finite loudness measurement')
    normalize = ('loudnorm=I=-18:TP=-1.5:LRA=7:linear=true:'
                 f'measured_I={m["input_i"]}:measured_TP={m["input_tp"]}:'
                 f'measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}:'
                 f'offset={m["target_offset"]}')
    dest = OUT / '知客-三端演示-连贯配音与营销联动版.mp4'
    command([FFMPEG, '-y', '-v', 'error', '-i', str(joined), '-i', str(audio_joined),
             '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-af', normalize,
             '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', str(dest)])
    command([FFMPEG, '-v', 'error', '-i', str(dest), '-f', 'null', '-'])
    subtitles = []; offset = 0; report = []
    for p in timed:
        subtitles.extend([str(p['index']), stamp(offset) + ' --> ' + stamp(offset + p['duration']),
                          p['narration'], ''])
        report.append({k: v for k, v in p.items() if k != 'source'} | {'start': offset})
        offset += p['duration']
    (OUT / '中文字幕.srt').write_text('\n'.join(subtitles), encoding='utf-8-sig')
    (OUT / '配音稿.txt').write_text('\n\n'.join(p['title'] + '\n' + p['narration'] for p in timed), encoding='utf-8')
    probe = json.loads(command([FFPROBE, '-v', 'error', '-show_format', '-show_streams',
                               '-of', 'json', str(dest)]).stdout)
    (OUT / '成片检查.json').write_text(json.dumps({
        'voice': 'zh-CN-XiaoxiaoNeural', 'speech_rate': '-5%', 'voice_speed_changed': False,
        'nominal_shot_end_pause_seconds': .28,
        'new_footage': '原录制客户会话转入营销创作，实际预填需求、勾选素材及三平台选项；未提交新的生成任务。',
        'edit': '按语音重排镜头时长，网页操作镜头适当变速，既有独立营销结果如实标注。',
        'parts': report, 'loudness_measurement': m, 'probe': probe, 'decode_errors': 0,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    for index in [2, 16, 22, 23, 24, 25, 26, 27, 28, 29]:
        p = report[index - 1]
        command([FFMPEG, '-y', '-v', 'error', '-ss', str(p['start'] + p['duration'] * .6),
                 '-i', str(dest), '-frames:v', '1', str(OUT / f'check-{index:02}.jpg')])
    print(json.dumps({'output': str(dest), 'duration': probe['format']['duration'], 'chapters': len(report)}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(synthesize())
    build()
