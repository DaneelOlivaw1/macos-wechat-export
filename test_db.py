#!/usr/bin/env python3
"""Synthetic SQLCipher, message reader, cursor, send verification and LLDB tests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import contextlib
import io
from unittest.mock import patch
from sqlcipher_probe import DB, self_test
from wechat_db import Reader, literal, private_write
from send_verified import matches
from capture_keys import verified


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--lldb', action='store_true', help='Launch only a fabricated local C child under LLDB')
    args = ap.parse_args()
    results = self_test()['checks']
    with tempfile.TemporaryDirectory(prefix='wechat-synthetic-') as directory:
        root = Path(directory)
        (root/'contact').mkdir(); (root/'message').mkdir()
        chat='synthetic-room@chatroom'; self_id='synthetic_self'; other='synthetic_peer'
        table='Msg_'+hashlib.md5(chat.encode()).hexdigest()
        contact=root/'contact/contact.db'; messages=root/'message/message_0.db'
        raw=os.urandom(32); key=raw.hex()
        manifest=root/'keys.json'
        private_write(manifest, {'keys':{str(p.relative_to(root)):{'enc_key':key} for p in (contact,messages)}})
        with DB(contact,key,fixture_write=True) as db:
            db.query('CREATE TABLE contact(username TEXT, nick_name TEXT, remark TEXT);')
            db.query(f'INSERT INTO contact VALUES({literal(chat)},\'Demo Group\',\'\'),'
                     f'({literal(other)},\'Duplicate Name\',\'\'),(\'synthetic_peer_2\',\'Duplicate Name\',\'\')')
        with DB(messages,key,fixture_write=True) as writer:
            writer.query('PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; '
                         'CREATE TABLE Name2Id(user_name TEXT PRIMARY KEY); '
                         f'INSERT INTO Name2Id(rowid,user_name) VALUES(7,{literal(self_id)}),(19,{literal(other)}); '
                         f'CREATE TABLE "{table}"(local_id INTEGER PRIMARY KEY,server_id INTEGER,local_type INTEGER,'
                         'create_time INTEGER,real_sender_id INTEGER,message_content BLOB)')
            def add(n,sender,body,kind=1,server=None):
                server=n*100 if server is None else server
                blob=body.hex() if isinstance(body,bytes) else body.encode().hex()
                writer.query(f'INSERT INTO "{table}" VALUES({n},{server},{kind},{1000+n},{sender},x\'{blob}\')')
            add(1,7,'old message')
            writer.query('PRAGMA wal_checkpoint(TRUNCATE)')
            page=messages.read_bytes()[:4096]
            assert verified(raw,page) and not verified(os.urandom(32),page)
            results.append('first_page_hmac_accepts_correct_key_rejects_wrong_key')
            reader=Reader(root,manifest)
            assert len(reader.resolve('Duplicate Name'))==2
            assert reader.resolve("' OR 1=1 --")==[]
            results.append('duplicate_names_preserved_and_lookup_injection_rejected')
            state=reader.init_state(chat,self_id)
            add(2,19,other+':\nnew incoming')
            from compression import zstd
            add(3,19,zstd.compress((other+':\n压缩文本').encode()))
            add(4,19,'<msg><secret>must not appear</secret></msg>',kind=3)
            add(5,7,'self message')
            batch=reader.check(state)
            assert batch['incoming_count']==3 and len(batch['new_messages'])==4
            assert batch['new_messages'][0]['text']=='new incoming'
            assert batch['new_messages'][1]['text']=='压缩文本'
            assert batch['new_messages'][2]['text'] is None
            assert batch['new_messages'][3]['from_self'] is True
            results.extend(['group_prefix_removed','zstd_text_decoded','media_xml_not_exposed','own_sender_excluded_from_incoming'])
            assert reader.check(state)==batch  # no acknowledgement, no loss
            state['cursor']=batch['ack_cursor'];state['salts']=batch['salts']
            assert reader.check(state)['new_messages']==[]
            results.append('explicit_ack_prevents_both_message_loss_and_replay')
            baseline=reader.snapshot(chat)
            add(6,19,other+':\nverified reply')
            assert matches(reader,chat,self_id,'verified reply',baseline)==[]
            add(7,7,'verified reply',server=0)
            matched=matches(reader,chat,self_id,'verified reply',baseline)
            assert len(matched)==1 and matched[0]['server_id']=='0'
            writer.query(f'UPDATE "{table}" SET server_id=700 WHERE local_id=7')
            assert matches(reader,chat,self_id,'verified reply',baseline)[0]['server_id']=='700'
            add(8,7,'verified reply')
            assert len(matches(reader,chat,self_id,'verified reply',baseline))==2
            results.extend(['send_verification_rejects_peer_echo','pending_server_id_becomes_visible','duplicate_sends_detected'])
            broken=dict(state,root_hash='wrong')
            try: reader.check(broken)
            except RuntimeError: pass
            else: raise AssertionError('wrong account accepted')
            results.append('cursor_account_binding')
            # Exercise the entire wrapper with a fake UI sender and a real encrypted
            # database. Deliberately return UI uncertainty after inserting one row.
            import send_verified
            payload=root/'message.txt';payload.write_text('wrapper reply')
            argv=['send_verified.py','--db-root',str(root),'--key-file',str(manifest),
                  '--state-dir',str(root/'send-state'),'--chat-id',chat,'--self-id',self_id,
                  '--title','Demo Group (2)','--text-file',str(payload),'--id','fixture-send',
                  '--composer-top','0.7']
            calls=[]
            def fake_ui(command):
                calls.append(command)
                if '--dry-run' in command:
                    return subprocess.CompletedProcess(command,0)
                assert Path(command[command.index('--text-file')+1]).read_text()=='wrapper reply'
                add(9,7,'wrapper reply')
                return subprocess.CompletedProcess(command,2)  # send_result_uncertain
            with patch.object(sys,'argv',argv), patch.object(send_verified.subprocess,'run',fake_ui), contextlib.redirect_stdout(io.StringIO()):
                assert send_verified.main()==0
                assert send_verified.main()==0
            assert len(calls)==2  # one preflight, one send; repeated ID sends nothing
            results.extend(['wrapper_resolves_ui_uncertainty_from_database','wrapper_id_retry_does_not_send'])
            payload.write_text('different payload')
            with patch.object(sys,'argv',argv), contextlib.redirect_stdout(io.StringIO()):
                try: send_verified.main()
                except RuntimeError as error: assert 'id_reused' in str(error)
                else: raise AssertionError('different payload reused ID')
            results.append('wrapper_id_payload_binding')
        if args.lldb:
            toy=root/'toy.c'; executable=root/'toy'
            # A two-round PBKDF invocation passes the synthetic raw key and MAC salt.
            macsalt=bytes(x^0x3a for x in page[:16])
            toy.write_text('#include <CommonCrypto/CommonKeyDerivation.h>\n#include <unistd.h>\n'
                           'int main(void){unsigned char key[32]={'+','.join(map(str,raw))+'};'
                           'unsigned char salt[16]={'+','.join(map(str,macsalt))+'}; unsigned char out[32];'
                           'sleep(1); CCKeyDerivationPBKDF(kCCPBKDF2,(const char*)key,32,salt,16,kCCPRFHmacAlgSHA512,2,out,32);'
                           'sleep(1); return 0;}')
            subprocess.run(['xcrun','clang',str(toy),'-o',str(executable)],check=True)
            output=root/'captured/keys.json'
            env=dict(os.environ,PYTHONPATH=subprocess.check_output(['/usr/bin/lldb','-P'],text=True).strip())
            proc=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('capture_keys.py')),
                                 '--exe',str(executable),'--db-root',str(root/'message'),'--out',str(output),'--timeout','15'],
                                env=env,capture_output=True,text=True,timeout=30)
            assert proc.returncode==0, proc.stdout  # progress only, no keys
            found=json.loads(output.read_text())['keys']
            assert found['message_0.db']['enc_key']==key
            assert output.stat().st_mode & 0o777 == 0o600
            assert raw.hex() not in proc.stdout
            results.extend(['lldb_child_capture_verified','captured_key_private_and_not_logged'])
    print(json.dumps({'passed':len(results),'checks':results,'fixtures_only':True},indent=2))


if __name__=='__main__':
    main()
