#!/usr/bin/env python3
"""One-shot read-only inbox plus local media preparation. Never sends or acknowledges."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from wechat_db import Reader,emit
from media_pipeline import SUPPORTED_TYPES


def load_config(path):
    path=Path(path).resolve()
    config=json.loads(path.read_text())
    for name in ('db_root','key_file','state_file','media_python','cache_dir','asr_model','app_data'):
        if config.get(name):
            value=Path(config[name]).expanduser()
            config[name]=str((path.parent/value).resolve()) if not value.is_absolute() else str(value.resolve())
    for name in ('db_root','key_file','chat_id','self_id','expected_name','state_file','media_python','cache_dir'):
        if not config.get(name):raise ValueError('configuration_missing_'+name)
    return config


def check(config):
    reader=Reader(config['db_root'],config['key_file'])
    state=json.loads(Path(config['state_file']).read_text())
    if state['chat_id']!=config['chat_id'] or state['self_id']!=config['self_id']:
        raise ValueError('configuration_state_identity_mismatch')
    contacts=reader.resolve(config['chat_id'])
    if len(contacts)!=1 or config['expected_name'] not in (contacts[0]['nick_name'],contacts[0]['remark']):
        raise ValueError('contact_identity_or_name_changed')
    batch=reader.check(state)
    incoming=[r for r in batch['new_messages'] if r['from_self'] is False]
    # Only NEW incoming media. Context below stays text-only; no historical conversion.
    ids={}
    for row in incoming:
        if int(row['local_type']) in SUPPORTED_TYPES:
            ids.setdefault(row['database'],[]).append(row['local_id'])
    prepared={}
    if ids:
        import tempfile
        with tempfile.TemporaryDirectory(prefix='wechat-media-config-') as temp:
            snapshot=Path(temp)/'config.json';snapshot.write_text(json.dumps(config));snapshot.chmod(0o600)
            for database,items in ids.items():
                try:
                    proc=subprocess.run([config['media_python'],str(Path(__file__).with_name('media_pipeline.py')),
                        '--config',str(snapshot),'--database',database,'--ids',','.join(items)],
                        capture_output=True,text=True,timeout=240)
                    for line in proc.stdout.splitlines():
                        result=json.loads(line)
                        if result['database']!=database or result['local_id'] not in items:raise ValueError('unexpected_media_receipt')
                        prepared[(database,result['local_id'])]=result
                except (OSError,ValueError,KeyError,subprocess.TimeoutExpired):
                    # Deliberately no raw subprocess stderr: it can contain private paths/content.
                    pass
    blocked=[];visual=[]
    for row in incoming:
        ref={k:row[k] for k in ('database','local_id')}
        if int(row['local_type'])==1:continue
        media=prepared.get((row['database'],row['local_id']),{'status':'blocked','reason':
            'media_processor_failed_or_timed_out' if int(row['local_type']) in SUPPORTED_TYPES else 'unsupported_message_type'})
        row['media']=media
        if media.get('text'):row['text']=media['text']
        if media['status']=='blocked':blocked.append(ref)
        if media['status']=='needs_visual_review':visual.append(ref)
    batch.update(new_count=len(batch['new_messages']),blocked_media_refs=blocked,needs_visual_review_refs=visual)
    if incoming:batch['recent_text_context']=reader.read(config['chat_id'],20,self_id=config['self_id'])
    return batch


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',type=Path,required=True)
    a=ap.parse_args();os.umask(0o077)
    emit(check(load_config(a.config)))

if __name__=='__main__':
    try:main()
    except Exception as e:
        emit({'type':'error','reason':str(e)});sys.exit(2)
