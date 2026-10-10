#!/usr/bin/env python3
"""Synthetic media/ASR/inbox tests. No WeChat access, private media, network or sending."""
import hashlib,io,json,os,struct,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import media_pipeline as m
import check_inbox as inbox

class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wechat-media-test-');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def config(self):return {'db_root':str(self.root/'db_storage'),'self_id':'synthetic_self','app_data':str(self.root/'app_data')}
    def png(self):
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(80,40),(25,190,60)).save(out,format='PNG');return out.getvalue()
    def seg(self,text,i=0):return {'start':i,'end':i+1,'text':text,'avg_logprob':-.2,'no_speech_prob':.01}
    def test_stored_voice(self):
        text='人工语音文本'.encode();inner=b'\x12'+bytes([len(text)])+text
        self.assertEqual(m.voice_text(b'\x2a'+bytes([len(inner)])+inner),text.decode())
        self.assertIsNone(m.voice_text(b'\x2a\xff'))
    def test_protobuf_bounds(self):
        for raw in (b'\x12\x7fshort',b'\x00',b'\x80'*12):
            with self.assertRaises(ValueError):m.protobuf(raw)
    def test_asr_cross_segment_loop(self):
        self.assertEqual(m.assess_transcript([self.seg('我',i) for i in range(8)])['status'],'unreliable')
    def test_asr_nan_invalid_times_and_strict_json(self):
        for update in ({'avg_logprob':float('nan')},{'end':-2},{'no_speech_prob':.99}):
            s=self.seg('人工音频');s.update(update);r=m.assess_transcript([s]);self.assertEqual(r['text'],'');json.dumps(r,allow_nan=False)
    def test_asr_normal_not_accuracy_claim(self):
        r=m.assess_transcript([self.seg('先准备下一板，再调整节奏。')]);self.assertEqual(r['status'],'machine_transcript');self.assertTrue(r['text'])
    def test_v2_decryption(self):
        from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
        from cryptography.hazmat.primitives.padding import PKCS7
        raw=self.png();a=35;x=12;key=b'0123456789abcdef';xor=47
        pad=PKCS7(128).padder();head=pad.update(raw[:a])+pad.finalize()
        enc=Cipher(algorithms.AES(key),modes.ECB()).encryptor();encrypted=enc.update(head)+enc.finalize()
        dat=b'\x07\x08V2\x08\x07'+struct.pack('<II',a,x)+b'\0'+encrypted+raw[a:-x]+bytes(v^xor for v in raw[-x:])
        self.assertEqual(m.dat_decode(dat,key,xor),raw)
        p=self.root/'a.dat';p.write_bytes(dat);out=self.root/'decoded';out.mkdir()
        with patch.object(m,'image_keys',return_value=iter([(key,xor)])):
            r=m.decode_image(self.config(),[p],out)
        self.assertEqual((r['width'],r['height']),(80,40));self.assertEqual(r['status'],'needs_visual_review')
        with patch.object(m,'image_keys',return_value=iter([(b'x'*16,xor)])):
            self.assertEqual(m.decode_image(self.config(),[p],out)['status'],'blocked')
    def test_raw_xor_and_empty_image(self):
        out=self.root/'out';out.mkdir()
        p=self.root/'x.dat';p.write_bytes(bytes(v^91 for v in self.png()))
        self.assertEqual(m.decode_image(self.config(),[p],out)['width'],80)
        p.write_bytes(b'');self.assertEqual(m.decode_image(self.config(),[p],out)['status'],'blocked')
    def attachment(self,name='synthetic_video',payload=b'synthetic-data'):
        from datetime import datetime
        stamp=1700000000;folder=self.root/'msg/file'/datetime.fromtimestamp(stamp).strftime('%Y-%m');folder.mkdir(parents=True,exist_ok=True)
        path=folder/name;path.write_bytes(payload)
        xml=f'<msg><appmsg><title>{name}</title><type>6</type><appattach><totallen>{len(payload)}</totallen><md5>{hashlib.md5(payload).hexdigest()}</md5></appattach></appmsg></msg>'
        return path,{'content':xml.encode().hex(),'create_time':str(stamp)}
    def test_attachment_exact_hash_and_size(self):
        p,row=self.attachment();self.assertEqual(m.attachment_path(self.config(),row),p.resolve())
        p.write_bytes(b'X'*len(p.read_bytes()))
        with self.assertRaisesRegex(RuntimeError,'digest_mismatch'):m.attachment_path(self.config(),row)
    def test_attachment_traversal_and_symlink(self):
        p,row=self.attachment();s=bytes.fromhex(row['content']).replace(b'<title>synthetic_video',b'<title>../synthetic_video');row['content']=s.hex()
        with self.assertRaises(ValueError):m.attachment_path(self.config(),row)
        p,row=self.attachment();p.unlink();target=self.root/'other';target.write_bytes(b'synthetic-data');p.symlink_to(target)
        with self.assertRaises(RuntimeError):m.attachment_path(self.config(),row)
    def test_video_frames_and_no_audio(self):
        p=self.root/'synthetic.mp4';out=self.root/'frames';out.mkdir()
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=green:s=96x64:r=10:d=1','-c:v','mpeg4','-y',str(p)],check=True)
        r=m.video(self.config(),p,out)
        self.assertEqual(r['status'],'needs_visual_review');self.assertTrue(r['sampling_only']);self.assertEqual(r['audio']['status'],'no_audio_stream')
        self.assertTrue(all(Path(f['path']).is_file() for f in r['frames']))
    def test_full_file_video_prepare_and_cache(self):
        source=self.root/'fixture.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=96x64:r=10:d=1','-c:v','mpeg4','-y',str(source)],check=True)
        path,row=self.attachment(payload=source.read_bytes())
        row.update(local_id='11',server_id='1100',local_type=str(m.FILE_MESSAGE),packed='')
        c=dict(self.config(),chat_id='synthetic-room',cache_dir=str(self.root/'cache'))
        class FakeDB:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def query(self,*args):return [dict(row)]
        with patch.object(m,'open_db',return_value=FakeDB()):
            first=m.prepare(c,'message_0.db',11)
            with patch.object(m,'video',side_effect=AssertionError('cache should be reused')):
                second=m.prepare(c,'message_0.db',11)
        self.assertTrue(first['attachment_video']);self.assertEqual(first,second)
    def test_prepare_stored_voice_needs_no_asr(self):
        text='人工转写'.encode();inner=b'\x12'+bytes([len(text)])+text;packed=b'\x2a'+bytes([len(inner)])+inner
        row={'local_id':'12','server_id':'1200','local_type':'34','packed':packed.hex(),'content':'','create_time':'1700000000'}
        class FakeDB:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def query(self,*args):return [dict(row)]
        c=dict(self.config(),chat_id='synthetic-room',cache_dir=str(self.root/'cache'))
        with patch.object(m,'open_db',return_value=FakeDB()),patch.object(m,'transcribe',side_effect=AssertionError('no ASR needed')):
            r=m.prepare(c,'message_0.db',12)
        self.assertEqual(r['status'],'ready');self.assertEqual(r['source'],'wechat_stored_transcript')
    def test_private_cache_json(self):
        p=self.root/'receipt.json';m.save(p,{'text':'synthetic'});self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_inbox_new_media_only_and_failure_visible(self):
        state=self.root/'state.json';state.write_text(json.dumps({'chat_id':'room','self_id':'self'}))
        c=dict(self.config(),key_file='unused',chat_id='room',self_id='self',expected_name='Demo',state_file=str(state),media_python='/not/a/runtime',cache_dir=str(self.root/'cache'))
        class FakeReader:
            def __init__(self,*args):pass
            def resolve(self,*args):return [{'nick_name':'Demo','remark':''}]
            def check(self,*args):return {'new_messages':[
                {'database':'message_0.db','local_id':'1','local_type':'1','from_self':False,'text':'new text'},
                {'database':'message_0.db','local_id':'2','local_type':'34','from_self':False,'text':None},
                {'database':'message_0.db','local_id':'3','local_type':'43','from_self':True,'text':None}], 'incoming_count':2,'ack_cursor':{'message_0.db':3}}
            def read(self,*args,**kwargs):return [{'local_type':'43','text':None,'local_id':'old'}]
        with patch.object(inbox,'Reader',FakeReader),patch.object(inbox.subprocess,'run',side_effect=OSError('synthetic')) as run:
            r=inbox.check(c)
        self.assertEqual(r['blocked_media_refs'],[{'database':'message_0.db','local_id':'2'}]);self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args.args[0][-1],'2');self.assertEqual(json.loads(state.read_text()),{'chat_id':'room','self_id':'self'})

if __name__=='__main__':unittest.main(verbosity=2)
