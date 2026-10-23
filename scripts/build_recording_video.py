"""Encode real browser captures, preserving each take's captured wall-clock timing."""
import json,subprocess,shutil,math,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'output/competition-video-20261023'
assert OUT.is_relative_to(ROOT/'output')
takes=json.loads((OUT/('edit.json' if (OUT/'edit.json').exists() else 'takes.json')).read_text(encoding='utf-8'))
ffmpeg=shutil.which('ffmpeg');ffprobe=shutil.which('ffprobe')
assert ffmpeg and ffprobe

def ass_time(t):
    cs=round(t*100);return f'{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'
def srt_time(t):
    ms=round(t*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'

ASS='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Microsoft YaHei,34,&H00FFFFFF,&H00FFFFFF,&H00111B2A,&H00111B2A,-1,0,0,0,100,100,0,0,1,0,0,7,42,42,18,1
Style: Caption,Microsoft YaHei,32,&H00FFFFFF,&H00FFFFFF,&H00111B2A,&H00111B2A,0,0,0,0,100,100,0,0,1,0,0,2,90,90,26,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''

def encode(item):
    i,take=item;stem=f'take-{i:02}';frames=take['frames'];duration=take['duration']
    assert len(frames)>20
    listing=[]
    for n,frame in enumerate(frames):
        next_t=frames[n+1]['t'] if n+1<len(frames) else duration
        listing.extend([f"file '{(Path(take['dir'])/frame['file']).as_posix()}'",f'duration {max(0.01,next_t-frame["t"]):.6f}'])
    listing.append(f"file '{(Path(take['dir'])/frames[-1]['file']).as_posix()}'")
    (OUT/(stem+'.concat')).write_text('\n'.join(listing),encoding='utf-8')
    overlay=ASS+f'Dialogue: 0,0:00:00.00,{ass_time(duration+1)},Title,,0,0,0,,{take["title"]}\n'+f'Dialogue: 0,0:00:00.00,{ass_time(duration+1)},Caption,,0,0,0,,{take["caption"]}\n'
    (OUT/(stem+'.ass')).write_text(overlay,encoding='utf-8-sig')
    cmd=[ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',stem+'.concat','-t',str(duration),
         '-vf',f'scale=1920:920:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:76:color=0x111B2A,setsar=1,subtitles={stem}.ass',
         '-r','30','-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-pix_fmt','yuv420p','-an',stem+'.mp4']
    p=subprocess.run(cmd,cwd=OUT,capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr.decode('utf-8',errors='replace')[-2000:])
    print('encoded',stem,flush=True)
    return stem+'.mp4'

with ThreadPoolExecutor(max_workers=2) as pool:clips=list(pool.map(encode,enumerate(takes,1)))
(OUT/'join.concat').write_text('\n'.join(f"file '{name}'" for name in clips),encoding='utf-8')
result=OUT/('知客-三端完整演示-字幕版.mp4' if '--full' in sys.argv else '知客-比赛功能演示-字幕版.mp4')
subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i','join.concat','-c','copy','-movflags','+faststart',result.name],cwd=OUT,check=True)
offset=0;subs=[];chapters=[]
for i,take in enumerate(takes,1):
    subs.extend([str(i),srt_time(offset)+' --> '+srt_time(offset+take['duration']),take['title']+'\n'+take['caption'],''])
    chapters.append({'start':offset,'duration':take['duration'],'title':take['title'],'caption':take['caption'],'frames':len(take['frames'])})
    offset+=take['duration']
(OUT/'中文字幕.srt').write_text('\n'.join(subs),encoding='utf-8-sig')
probe=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(result)]))
report={'file':str(result),'capture':'Actual webpage frames captured continuously within each take; takes joined without time acceleration.',
        'audio':'No audio; Chinese captions burned into video.','chapters':chapters,'ffprobe':probe}
(OUT/'视频检查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
points=[10,90,140,190,205,230]
if '--full' in sys.argv:
    labels=['客户端｜从需求开始咨询','管理员｜完成会话分配','对话系统｜多轮上下文与候选回复','管理员｜四级报价规则与独立复核','客户端｜收到结构化报价卡','客户端｜会话结束，记录可追溯','05｜发布预览与图文组合']
    points=[c['start']+min(9,c['duration']-1) for label in labels for c in chapters if c['title']==label]
for n,at in enumerate(points,1):
    subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-ss',str(at),'-i',str(result),'-frames:v','1',str(OUT/f'qa-{n}.jpg')],check=True)
print(json.dumps({'file':str(result),'duration':probe['format']['duration'],'size':probe['format']['size'],'width':probe['streams'][0]['width'],'height':probe['streams'][0]['height']},ensure_ascii=False),flush=True)
