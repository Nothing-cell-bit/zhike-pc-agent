"""Replace the demo's SAPI narration with a Chinese neural female voice.

Uses an isolated edge-tts dependency directory; never changes model credentials.
The already-rendered video stream is copied without changing its pictures.
"""
import argparse
import asyncio
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tmp/tooldeps/edge-tts-7.3.1'))
import edge_tts

SOURCE = ROOT / 'output/competition-video-voice-20261023'
OUT = ROOT / 'output/competition-video-natural-20261023'
VOICE = 'zh-CN-XiaoxiaoNeural'
PLAN = json.loads((SOURCE / 'voice-plan.json').read_text(encoding='utf-8'))
FFMPEG = shutil.which('ffmpeg')
FFPROBE = shutil.which('ffprobe')
OUT.mkdir(parents=True, exist_ok=True)


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def duration(path):
    return float(run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
                      '-of', 'default=nw=1:nk=1', str(path)]).stdout)


async def synthesize():
    sem = asyncio.Semaphore(2)

    async def one(p):
        dest = OUT / f'voice-{p["index"]:02}.mp3'
        if dest.exists() and dest.stat().st_size > 1000:
            return
        async with sem:
            for attempt in range(2):
                try:
                    await asyncio.wait_for(edge_tts.Communicate(
                        p['narration'], VOICE, rate='-5%', pitch='-2Hz'
                    ).save(str(dest)), timeout=40)
                    print(f'voice {p["index"]:02} ready', flush=True)
                    return
                except Exception:
                    if attempt:
                        raise
                    await asyncio.sleep(1)

    await asyncio.gather(*(one(p) for p in PLAN))


def compose():
    timings = []
    for p in PLAN:
        src = OUT / f'voice-{p["index"]:02}.mp3'
        length = duration(src)
        speed = max(1.0, length / (p['duration'] - .35))
        if speed > 1.15:
            raise ValueError(f'Chapter {p["index"]} needs excessive speed: {speed:.3f}')
        dest = OUT / f'aligned-{p["index"]:02}.wav'
        run([FFMPEG, '-y', '-v', 'error', '-i', str(src), '-af',
             f'atempo={speed:.6f},adelay=150:all=1,apad,atrim=duration={p["duration"]}',
             '-ar', '48000', '-ac', '1', str(dest)])
        timings.append({**p, 'speech_seconds': length, 'alignment_speed': speed})

    listing = OUT / 'audio.concat'
    listing.write_text('\n'.join(f"file 'aligned-{p['index']:02}.wav'" for p in PLAN), encoding='utf-8')
    joined = OUT / '完整旁白-未均衡.wav'
    run([FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
         '-c:a', 'pcm_s16le', str(joined)])
    measured = run([FFMPEG, '-hide_banner', '-i', str(joined), '-af',
                    'loudnorm=I=-18:TP=-1.5:LRA=7:print_format=json', '-f', 'null', '-'])
    report, _ = json.JSONDecoder().raw_decode(measured.stderr[measured.stderr.rfind('{'):])
    for key in ['input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset']:
        if not math.isfinite(float(report[key])):
            raise ValueError(f'Invalid loudness measurement: {key}')
    normalized = OUT / '完整旁白-晓晓女声.wav'
    filt = ('loudnorm=I=-18:TP=-1.5:LRA=7:linear=true:'
            f'measured_I={report["input_i"]}:measured_TP={report["input_tp"]}:'
            f'measured_LRA={report["input_lra"]}:measured_thresh={report["input_thresh"]}:'
            f'offset={report["target_offset"]}')
    run([FFMPEG, '-y', '-v', 'error', '-i', str(joined), '-af', filt,
         '-ar', '48000', '-c:a', 'pcm_s16le', str(normalized)])

    dest = OUT / '知客-三端精简演示-自然中文女声版.mp4'
    run([FFMPEG, '-y', '-v', 'error', '-i', str(SOURCE / '知客-三端精简演示-全屏配音版.mp4'),
         '-i', str(normalized), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
         '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(dest)])
    run([FFMPEG, '-v', 'error', '-i', str(dest), '-f', 'null', '-'])
    probe = json.loads(run([FFPROBE, '-v', 'error', '-show_format', '-show_streams',
                           '-of', 'json', str(dest)]).stdout)
    shutil.copyfile(SOURCE / '中文配音字幕.srt', OUT / '中文配音字幕.srt')
    shutil.copyfile(SOURCE / '配音稿.txt', OUT / '配音稿.txt')
    (OUT / '配音替换检查.json').write_text(json.dumps({
        'voice': VOICE, 'voice_label': '晓晓，中文神经网络女声', 'rate': '-5%',
        'pitch': '-2Hz', 'engine_version': edge_tts.__version__,
        'video_stream': 'copied from existing 1920x1080 fullscreen version',
        'audio_normalization': {'target_lufs': -18, 'target_true_peak_db': -1.5, 'measurement': report},
        'parts': timings, 'probe': probe, 'decode_errors': 0,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(dest), 'duration': probe['format']['duration'],
                      'max_alignment_speed': max(x['alignment_speed'] for x in timings)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--synthesize-only', action='store_true')
    args = parser.parse_args()
    asyncio.run(synthesize())
    if not args.synthesize_only:
        compose()
