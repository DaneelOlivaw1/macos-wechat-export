#!/usr/bin/env python3
"""UI send plus independent read-only DB verification; uncertain sends never retry."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from wechat_db import Reader, root_for, private_write, emit


def matches(reader, chat, self_id, text, baseline):
    current = reader.snapshot(chat)
    for name, salt in baseline['salts'].items():
        if current['salts'].get(name) != salt or current['cursor'].get(name,-1) < baseline['cursor'][name]:
            raise RuntimeError('database_changed_during_send')
    rows = reader.read(chat,1000,after=baseline['cursor'],self_id=self_id)
    return [r for r in rows if r['from_self'] is True and r['text']==text]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db-root', type=Path)
    ap.add_argument('--key-file', type=Path, default=Path('.wechat-local/keys.json'))
    ap.add_argument('--state-dir', type=Path, default=Path('.wechat-local/send-state'))
    ap.add_argument('--chat-id', required=True)
    ap.add_argument('--self-id', required=True)
    ap.add_argument('--title', required=True, help='Exact visible header, including group member count')
    ap.add_argument('--text-file', type=Path, required=True, help='UTF-8 single line, no trailing newline')
    ap.add_argument('--id', required=True)
    ap.add_argument('--composer-top', required=True, type=float)
    ap.add_argument('--send-key', choices=['enter','cmd-enter'], default='enter')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--verify-only', action='store_true', help='Recheck existing attempt without sending')
    ap.add_argument('--verify-timeout', type=float, default=15)
    args = ap.parse_args()
    text = args.text_file.read_text(encoding='utf8')
    if not text.strip() or len(text)>200 or any(ord(c)<32 or ord(c)==127 for c in text):
        ap.error('text must be one nonempty line, <=200 characters, no control characters/newline')
    if not .45 <= args.composer_top <= .88 or not 1 <= args.verify_timeout <= 120:
        ap.error('invalid geometry or timeout')
    reader = Reader(root_for(args.db_root),args.key_file)
    # UI titles are not unique identifiers. Caller must manually select the contact
    # matching --chat-id, then inspect --dry-run. Database checks cannot undo a mis-send.
    contact = reader.resolve(args.chat_id)
    if len(contact) != 1 and args.chat_id != 'filehelper':
        raise RuntimeError('unknown_or_ambiguous_contact_id')
    reader.read(args.chat_id,1,self_id=args.self_id)
    args.state_dir.mkdir(parents=True,mode=0o700,exist_ok=True)
    lock = os.open(args.state_dir/'verified-send.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        journal = args.state_dir/(hashlib.sha256(args.id.encode()).hexdigest()+'.db.json')
        signature = hashlib.sha256(json.dumps([str(reader.root),args.chat_id,args.self_id,args.title,text],ensure_ascii=False).encode()).hexdigest()
        previous = json.loads(journal.read_text()) if journal.exists() else None
        if previous and previous['signature'] != signature:
            raise RuntimeError('id_reused_with_different_payload')
        if previous and previous['status'] == 'sent_db_verified':
            emit({'type':'already_sent_db_verified','id':args.id})
            return 0
        command = [str(Path(__file__).with_name('wechat-ui').resolve()),'send',
                   '--chat',args.title,'--text-file',str(args.text_file.resolve()),
                   '--id',args.id,'--composer-top',str(args.composer_top),
                   '--state-dir',str(args.state_dir.resolve()),'--send-key',args.send_key]
        if args.dry_run:
            if previous:
                raise RuntimeError('id_already_attempted; use --verify-only')
            reader.snapshot(args.chat_id)  # Ensure DB lookup works before any UI operation.
            return subprocess.run(command+['--dry-run']).returncode
        if args.verify_only and not previous:
            raise RuntimeError('no_saved_attempt_to_verify')
        if previous:
            baseline = previous['baseline']
            # Never send again with a previously attempted ID, even after a timeout.
        else:
            preflight = subprocess.run(command+['--dry-run'])
            if preflight.returncode:
                return preflight.returncode
            baseline = reader.snapshot(args.chat_id)
            previous = {'signature':signature,'status':'attempted','baseline':baseline,
                        'started_at':time.time()}
            private_write(journal,previous)
            # Pin the payload to a private snapshot, avoiding changes to the caller's file.
            import tempfile
            fd, temp = tempfile.mkstemp(prefix='.send-text-',dir=args.state_dir)
            try:
                with os.fdopen(fd,'w',encoding='utf8') as f:
                    f.write(text)
                command[command.index('--text-file')+1] = temp
                proc = subprocess.run(command)
                previous['ui_exit_code'] = proc.returncode
                private_write(journal,previous)
            finally:
                os.unlink(temp)
        deadline = time.monotonic()+args.verify_timeout
        while True:
            found = matches(reader,args.chat_id,args.self_id,text,baseline)
            if len(found)>1:
                raise RuntimeError('multiple_new_matching_messages; manual_review_required')
            if len(found)==1 and int(found[0]['server_id'] or 0)!=0:
                previous.update(status='sent_db_verified',verified_at=time.time(),
                                message_ref={k:found[0][k] for k in ('database','local_id','server_id')})
                private_write(journal,previous)
                emit({'type':'sent_db_verified','id':args.id,'exact_matches':1,'server_id_present':True,
                      'recipient_read_receipt':False})
                return 0
            if time.monotonic()>=deadline:
                emit({'type':'send_result_uncertain','id':args.id,'automatic_retry':False,
                      'action':'inspect WeChat; same ID with --verify-only only rechecks the database'})
                return 3
            time.sleep(.5)
    finally:
        os.close(lock)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        emit({'type':'error','reason':str(error)})
        sys.exit(2)
