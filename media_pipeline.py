#!/usr/bin/env python3
"""Local WeChat media preparation. Config/keys/caches remain private. No sending."""
import argparse,hashlib,io,json,math,os,re,struct,subprocess,sys,time,wave
from pathlib import Path
import xml.etree.ElementTree as ET
from sqlcipher_probe import DB,load_key


def varint(data,pos):
    value=0
    for shift in range(0,70,7):
        if pos>=len(data):raise ValueError('truncated protobuf')
        b=data[pos];pos+=1;value|=(b&127)<<shift
        if b<128:return value,pos
    raise ValueError('oversized protobuf')

def protobuf(data):
    result={};i=0
    while i<len(data):
        key,i=varint(data,i);field,wire=key>>3,key&7
        if not field:raise ValueError('invalid protobuf field')
        if wire==0:value,i=varint(data,i)
        elif wire in (1,5):
            n=8 if wire==1 else 4;value=data[i:i+n];i+=n
            if len(value)!=n:raise ValueError('truncated fixed field')
        elif wire==2:
            n,i=varint(data,i)
            if n>len(data)-i:raise ValueError('truncated bytes field')
            value=data[i:i+n];i+=n
        else:raise ValueError('unsupported protobuf wire type')
        result.setdefault(field,[]).append(value)
    return result

def voice_text(packed):
    try:
        outer=protobuf(packed);inner=protobuf(outer[5][0]);text=inner[2][0].decode('utf8')
        return text if text.strip() and len(text)<20000 else None
    except (ValueError,KeyError,IndexError,AttributeError,UnicodeDecodeError):return None

def decompress(data):
    if data.startswith(b'\x28\xb5\x2f\xfd'):
        try:
            from compression import zstd
            return zstd.decompress(data)
        except ImportError:
            import zstandard
            return zstandard.ZstdDecompressor().decompress(data,max_output_size=10*1024*1024)
    return data

def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    import tempfile
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.media-')
    with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False)
    os.replace(tmp,path)

def sqltext(value):return "CAST(x'"+value.encode().hex()+"' AS TEXT)"

def open_db(config,relative):
    path=Path(config['db_root'])/relative
    return DB(path,load_key(config['key_file'],path))

_ASR_MODEL=None

def assess_transcript(segments):
    """Conservative rejection of common ASR failures; this is not accuracy proof."""
    clean=[];accepted=[];invalid=False
    def repetitive(text):
        value=''.join(c for c in text if c.isalnum())
        if len(value)>=8 and len(set(value))<=2:return True
        return any(len(value)>=size*4 and value== (value[:size]*((len(value)+size-1)//size))[:len(value)]
                   for size in range(1,min(16,len(value)//4)+1))
    for source in segments:
        s={k:(None if isinstance(v,float) and not math.isfinite(v) else v) for k,v in source.items()}
        clean.append(s)
        bad=any(isinstance(v,float) and not math.isfinite(v) for v in source.values())
        start,end=s.get('start'),s.get('end')
        bad=bad or start is None or end is None or start<0 or end<=start
        invalid=invalid or bad
        if not bad and s.get('no_speech_prob') is not None and s.get('avg_logprob') is not None and s['no_speech_prob']<.8 and s['avg_logprob']>-1.2 and not repetitive(s.get('text','')):
            accepted.append(s)
    text=''.join(s.get('text','') for s in accepted)
    # Cross-segment loops are common over rhythmic noise; confidence alone misses them.
    phrases=[''.join(c for c in s.get('text','') if c.isalnum()) for s in clean]
    repeated_run=any(phrases[i] and len(set(phrases[i:i+4]))==1 for i in range(len(phrases)-3))
    unreliable=invalid or repetitive(text) or repeated_run or not text.strip() or len(accepted)<len(clean)*.5
    return {'text':'' if unreliable else text,'segments':clean,'source':'local_whisper',
            'status':'unreliable' if unreliable else 'machine_transcript',
            'quality_checked':2,'uncertain_segments':len(clean) if unreliable else len(clean)-len(accepted),
            'machine_transcript':True,'reason':'no_reliable_speech_or_ASR_anomaly' if unreliable else None}

def transcribe(path,model):
    if not model or not Path(model).is_dir():raise RuntimeError('local_ASR_model_missing')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    import mlx_whisper
    result=mlx_whisper.transcribe(str(path),path_or_hf_repo=str(model),language='zh',verbose=None,condition_on_previous_text=False)
    segments=[{'start':s['start'],'end':s['end'],'text':s['text'],'avg_logprob':s.get('avg_logprob'),'no_speech_prob':s.get('no_speech_prob')} for s in result['segments']]
    return assess_transcript(segments)

def image_keys(config):
    # Reverse-engineered local filename pattern; not an official WeChat API.
    base=Path(config.get('app_data',str(Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/app_data')))
    codes=set()
    for sub in ['net/kvcomm','ilink/kvcomm']:
        for path in (base/sub).glob('key_*_*.statistic'):
            match=re.fullmatch(r'key_(\d+)_.*\.statistic',path.name)
            if match:codes.add(int(match[1]))
    ids=[config['self_id'],Path(config['db_root']).parent.name]
    for code in codes:
        for own in ids:yield hashlib.md5((str(code)+own).encode()).hexdigest()[:16].encode(),code&255

def dat_decode(data,key,xor):
    from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
    from cryptography.hazmat.primitives.padding import PKCS7
    if len(data)<15:raise ValueError('short_image')
    a,x=struct.unpack('<II',data[6:14]);n=a+(16-a%16) if a else 0
    if 15+n+x>len(data):raise ValueError('image_lengths_invalid')
    decrypt=Cipher(algorithms.AES(key),modes.ECB()).decryptor()
    v=decrypt.update(data[15:15+n])+decrypt.finalize()
    if n:
        unpad=PKCS7(128).unpadder();v=unpad.update(v)+unpad.finalize()
    tail=data[15+n:]
    return v+(tail[:-x] if x else tail)+(bytes(c^xor for c in tail[-x:]) if x else b'')

def decode_image(config,paths,directory):
    from PIL import Image
    keys=list(image_keys(config));errors=[]
    for path in sorted(paths,key=lambda p:Path(p).stat().st_size,reverse=True):
        data=Path(path).read_bytes();variants=[]
        if not data:continue
        if data.startswith((b'\x07\x08V1\x08\x07',b'\x07\x08V2\x08\x07')):
            candidates=keys
            if data.startswith(b'\x07\x08V1'):
                candidates=[(b'cfcd208495d565ef',x) for x in range(256)]
            for key,xor in candidates:
                try:variants.append(dat_decode(data,key,xor))
                except ValueError:continue
        elif data.startswith((b'\xff\xd8',b'\x89PNG',b'GIF8',b'RIFF')):variants=[data]
        else:
            # Older single-byte XOR format, accepted only if image decoding succeeds.
            variants=[bytes(c^xor for c in data) for xor in {data[0]^0xff,data[0]^0x89,data[0]^0x47}]
        for raw in variants:
            dest=directory/'image.png'
            try:
                if raw.startswith(b'wxgf'):
                    # Static WXGF: locate the HEVC VPS and let ffmpeg validate the bitstream.
                    positions=[m.start() for m in re.finditer(b'\x00\x00\x00\x01\x40|\x00\x00\x01\x40',raw)]
                    if not positions:continue
                    stream=directory/'image.hevc';stream.write_bytes(raw[min(positions):])
                    proc=subprocess.run(['ffmpeg','-v','error','-f','hevc','-i',str(stream),'-frames:v','1','-y',str(dest)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=30)
                    if proc.returncode or not dest.exists():continue
                    im=Image.open(dest);im.load()
                    # Multiple frames/alpha are not claimed supported by this static fallback.
                    wxgf=True
                else:
                    im=Image.open(io.BytesIO(raw));im.load();im.save(dest);wxgf=False
                return {'status':'needs_visual_review','image':str(dest.resolve()),'width':im.width,'height':im.height,
                        'thumbnail_only':Path(path).name.endswith('_t.dat'),'wxgf_first_frame_only':wxgf}
            except Exception:continue
    return {'status':'blocked','reason':'image_format_or_key_unsupported'}

def locate_assets(config,row,kind):
    root=Path(config['db_root']);svr=int(row['server_id']);chat=config['chat_id']
    with open_db(config,'message/message_resource.db') as db:
        rows=db.query('SELECT hex(i.packed_info) AS info,hex(d.packed_info) AS detail,d.size,d.status FROM MessageResourceInfo i '
                      'JOIN MessageResourceDetail d ON d.message_id=i.message_id JOIN ChatName2Id c ON c.rowid=i.chat_id '
                      f'WHERE c.user_name={sqltext(chat)} AND i.message_svr_id={svr}')
    hashes=set()
    for resource in rows:
        for field in ('info','detail'):
            hashes.update(x.decode() for x in re.findall(rb'[a-fA-F0-9]{32}',bytes.fromhex(resource[field])))
    from datetime import datetime
    month=datetime.fromtimestamp(int(row['create_time'])).strftime('%Y-%m')
    group_hash=hashlib.md5(chat.encode()).hexdigest()
    folder=root.parent/('msg/attach/'+group_hash+'/'+month+'/Img' if kind==3 else 'msg/video/'+month)
    valid_sizes={int(r['size']) for r in rows if r['status']=='1' and int(r['size'])>0}
    return [p for h in hashes for p in folder.glob(h+'*') if p.is_file() and p.stat().st_size in valid_sizes]

def video(config,path,directory):
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],text=True,timeout=30))
    duration=float(info['format']['duration'])
    if not math.isfinite(duration) or duration<=0:raise ValueError('invalid_video_duration')
    if not any(s.get('codec_type')=='video' for s in info['streams']):raise ValueError('attachment_has_no_video_stream')
    if duration>600:return {'status':'blocked','reason':'video_over_10_minutes_requires_explicit_segment_selection','duration':duration}
    n=min(24,max(2,int(duration/3)+1));times=[duration*i/n for i in range(n)];frames=[]
    for idx,t in enumerate(times):
        dest=directory/f'frame-{idx:02d}.jpg'
        subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-vf','scale=960:-2','-y',str(dest)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=30)
        frames.append({'timestamp':round(t,3),'path':str(dest.resolve())})
    result={'status':'needs_visual_review','video':str(path),'duration':duration,'frames':frames,'sampling_only':True}
    if any(s['codec_type']=='audio' for s in info['streams']):
        wav=directory/'audio.wav'
        subprocess.run(['ffmpeg','-v','error','-i',str(path),'-vn','-ar','16000','-ac','1','-y',str(wav)],check=True,stderr=subprocess.PIPE,timeout=60)
        try:result['audio']=transcribe(wav,config.get('asr_model'))
        except Exception:result['audio']={'status':'unavailable','reason':'local_ASR_failed_or_model_missing','text':''}
    else:result['audio']={'status':'no_audio_stream','text':''}
    return result

FILE_MESSAGE=(6<<32)|49
SUPPORTED_TYPES=(3,34,43,FILE_MESSAGE)

def attachment_path(config,row):
    """Match a local attachment by untrusted metadata, size AND content digest."""
    raw=decompress(bytes.fromhex(row['content']))
    if len(raw)>10*1024*1024:raise ValueError('attachment_xml_too_large')
    begin=raw.find(b'<')
    if begin<0:raise ValueError('attachment_xml_missing')
    root=ET.fromstring(raw[begin:])
    if root.findtext('.//appmsg/type')!='6':raise ValueError('not_file_attachment')
    name=root.findtext('.//appmsg/title') or ''
    size=int(root.findtext('.//appattach/totallen') or '0')
    digest=(root.findtext('.//appattach/md5') or root.findtext('.//md5') or '').lower()
    if not name or name in ('.','..') or any(c in name for c in ('/','\\','\x00')) or len(name)>255:
        raise ValueError('unsafe_attachment_filename')
    if not 0<size<=200*1024*1024 or not re.fullmatch('[0-9a-f]{32}',digest):
        raise ValueError('attachment_size_or_digest_unavailable')
    from datetime import datetime
    month=datetime.fromtimestamp(int(row['create_time'])).strftime('%Y-%m')
    folder=(Path(config['db_root']).parent/'msg/file'/month).resolve()
    path=folder/name
    if not path.is_file() or path.is_symlink() or path.resolve().parent!=folder or path.stat().st_size!=size:
        raise RuntimeError('attachment_not_downloaded_or_name_changed')
    with path.open('rb') as f:actual=hashlib.file_digest(f,'md5').hexdigest()
    if actual!=digest:raise RuntimeError('attachment_digest_mismatch')
    return path

def prepare(config,dbname,local_id):
    if not re.fullmatch(r'message_\d+\.db',dbname):raise ValueError('invalid database name')
    table='Msg_'+hashlib.md5(config['chat_id'].encode()).hexdigest()
    with open_db(config,'message/'+dbname) as db:
        rows=db.query(f'SELECT local_id,server_id,create_time,local_type,hex(message_content) AS content,hex(packed_info_data) AS packed FROM "{table}" WHERE local_id={int(local_id)}')
    if len(rows)!=1:raise ValueError('message_not_found')
    row=rows[0];kind=int(row['local_type']);packed=bytes.fromhex(row['packed'])
    key=hashlib.sha256((config['chat_id']+'|'+dbname+'|'+str(local_id)+'|'+row['server_id']).encode()).hexdigest()[:24]
    directory=Path(config['cache_dir'])/key;directory.mkdir(parents=True,mode=0o700,exist_ok=True)
    receipt=directory/'result.json'
    if receipt.exists():
        previous=json.loads(receipt.read_text())
        if previous.get('source')=='local_whisper':
            previous.update(assess_transcript(previous['segments']))
            previous['status']='ready' if previous['text'] else 'blocked'
        if previous.get('audio',{}).get('source')=='local_whisper':
            previous['audio']=assess_transcript(previous['audio']['segments'])
        save(receipt,previous)
        if previous.get('status') in ['ready','needs_visual_review']:return previous
    result={'database':dbname,'local_id':str(local_id),'server_id':row['server_id'],'kind':kind}
    try:
        if kind==34:
            text=voice_text(packed)
            if text:result.update(status='ready',text=text,source='wechat_stored_transcript',machine_transcript=True)
            else:
                found=[]
                for path in sorted((Path(config['db_root'])/'message').glob('media_*.db')):
                    with open_db(config,'message/'+path.name) as db:
                        found+=db.query('SELECT hex(v.voice_data) AS body FROM VoiceInfo v JOIN Name2Id n ON n.rowid=v.chat_name_id '
                                        f'WHERE n.user_name={sqltext(config["chat_id"])} AND v.svr_id={int(row["server_id"])}')
                if len(found)!=1 or not found[0]['body']:raise RuntimeError('voice_not_downloaded_or_ambiguous')
                silk=directory/'audio.silk';silk.write_bytes(bytes.fromhex(found[0]['body']))
                import pilk
                pcm=directory/'audio.pcm';wav=directory/'audio.wav';pilk.decode(str(silk),str(pcm),pcm_rate=24000)
                with wave.open(str(wav),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(pcm.read_bytes())
                result.update(transcribe(wav,config.get('asr_model')))
                result['status']='ready' if result['text'].strip() else 'blocked'
                if result['status']=='blocked':result['reason']='no_reliable_speech_detected'
        elif kind in (3,43):
            paths=locate_assets(config,row,kind)
            if not paths:raise RuntimeError('media_not_downloaded')
            if kind==3:result.update(decode_image(config,paths,directory))
            else:
                mp4=[p for p in paths if p.suffix.lower()=='.mp4']
                if len(mp4)!=1:raise RuntimeError('video_original_missing_or_ambiguous')
                result.update(video(config,mp4[0],directory))
        elif kind==FILE_MESSAGE:
            path=attachment_path(config,row)
            try:result.update(video(config,path,directory));result['attachment_video']=True
            except (subprocess.CalledProcessError,ValueError):
                result.update(status='blocked',reason='attachment_is_not_supported_video; documents_are_not_executed_or_opened')
        else:result.update(status='blocked',reason='unsupported_message_type')
    except Exception as e:
        result.update(status='blocked',reason=type(e).__name__+': '+str(e))
    save(receipt,result)
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',type=Path,required=True);ap.add_argument('--database',required=True);ap.add_argument('--ids',required=True)
    a=ap.parse_args();os.umask(0o077);config=json.loads(a.config.read_text())
    for name in ('db_root','key_file','cache_dir','asr_model','app_data'):
        if config.get(name):
            p=Path(config[name]).expanduser()
            config[name]=str(p.resolve() if p.is_absolute() else (a.config.resolve().parent/p).resolve())
    ids=[int(x) for x in a.ids.split(',')]
    if not ids or any(i<1 for i in ids) or len(ids)>200:raise ValueError('too_many_messages')
    for i in ids:print(json.dumps(prepare(config,a.database,i),ensure_ascii=False,allow_nan=False),flush=True)
if __name__=='__main__':main()
