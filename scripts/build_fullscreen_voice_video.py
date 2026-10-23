"""Re-encode the short cut directly from original webpage captures, with Chinese narration."""
import json,shutil,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/competition-video-voice-20261023'
plan=json.loads((OUT/'voice-plan.json').read_text(encoding='utf-8'))
sources=json.loads((ROOT/'output/competition-video-full-20261023/edit.json').read_text(encoding='utf-8'))
ffmpeg=shutil.which('ffmpeg');ffprobe=shutil.which('ffprobe')
def duration(path):return float(subprocess.check_output([ffprobe,'-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]))
def stamp(t):
 n=round(t*1000);return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'
ASS='''[Script Info]
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
 i=p['index'];src=sources[p['source_chapter']];stem=f'part-{i:02}';frames=src['frames'];listing=[]
 for j,frame in enumerate(frames):
  nxt=frames[j+1]['t'] if j+1<len(frames) else max(src['duration'],frame['t']+.2)
  listing.extend([f"file '{(Path(src['dir'])/frame['file']).as_posix()}'",f'duration {max(.01,nxt-frame["t"]):.6f}'])
 listing.append(f"file '{(Path(src['dir'])/frames[-1]['file']).as_posix()}'")
 (OUT/(stem+'.concat')).write_text('\n'.join(listing),encoding='utf-8')
 tag=p['title'].replace('｜',' · ')+'  |  演示录屏'
 (OUT/(stem+'.ass')).write_text(ASS+f'Dialogue: 0,0:00:00.00,0:01:00.00,Tag,,0,0,0,,{tag}\nDialogue: 0,0:00:00.00,0:01:00.00,Caption,,0,0,0,,{p["narration"]}\n',encoding='utf-8-sig')
 wav=OUT/f'voice-{i:02}.wav';voice_duration=duration(wav);speed=max(1,voice_duration/(p['duration']-.4))
 filters=f'[0:v]trim=start={p["source_in"]}:duration={p["duration"]},setpts=PTS-STARTPTS,scale=1920:1080:force_original_aspect_ratio=increase:force_divisible_by=2,crop=1920:1080:0:0,setsar=1,subtitles={stem}.ass[v];[1:a]atempo={speed:.5f},adelay=150:all=1,apad,atrim=duration={p["duration"]},volume=0.85,alimiter=limit=0.89:level=false[a]'
 cmd=[ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',stem+'.concat','-i',wav.name,'-filter_complex',filters,'-map','[v]','-map','[a]',
      '-t',str(p['duration']),'-r','30','-c:v','libx264','-preset','veryfast','-crf','19','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-ar','48000',stem+'.mp4']
 r=subprocess.run(cmd,cwd=OUT,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.decode('utf-8',errors='replace')[-1600:])
 return {'file':stem+'.mp4','speech_seconds':voice_duration,'speech_speed':speed,**p}

with ThreadPoolExecutor(max_workers=2) as pool:parts=list(pool.map(encode,plan))
(OUT/'join.concat').write_text('\n'.join("file '"+p['file']+"'" for p in parts),encoding='utf-8')
dest=OUT/'知客-三端精简演示-全屏配音版.mp4'
subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i','join.concat','-c','copy','-movflags','+faststart',dest.name],cwd=OUT,check=True)
subs=[];offset=0
for p in parts:
 subs.extend([str(p['index']),stamp(offset)+' --> '+stamp(offset+p['duration']),p['narration'],'']);offset+=p['duration']
(OUT/'中文配音字幕.srt').write_text('\n'.join(subs),encoding='utf-8-sig')
probe=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(dest)]))
(OUT/'成片检查.json').write_text(json.dumps({'voice':'Microsoft Huihui Desktop，中文合成语音','composition':'原始网页连续帧，16:9全屏填充；非16:9素材裁切下边缘，不拉伸；字幕叠加在画面上。','parts':parts,'ffprobe':probe},ensure_ascii=False,indent=2),encoding='utf-8')
for i,at in enumerate([8,22,62,91,117,134],1):
 subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-ss',str(at),'-i',str(dest),'-frames:v','1',str(OUT/f'check-{i}.jpg')],check=True)
subprocess.run([ffmpeg,'-v','error','-i',str(dest),'-f','null','-'],check=True)
print(json.dumps({'path':str(dest),'seconds':probe['format']['duration'],'streams':[(s['codec_type'],s['codec_name']) for s in probe['streams']]},ensure_ascii=False))
