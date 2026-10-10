#!/usr/bin/env python3
"""Read WeChat database/WAL metadata only. Never decrypts or writes source files."""
import argparse
import json
from pathlib import Path
import struct
import time


def checksum(data, state, order):
    if len(data) % 8:
        raise ValueError('checksum input is not a multiple of 8')
    s0, s1 = state
    for x, y in struct.iter_unpack(order+'II', data):
        s0 = (s0+x+s1) & 0xffffffff
        s1 = (s1+y+s0) & 0xffffffff
    return s0, s1


def wal_info(path):
    if not path.exists():
        return {'exists':False}
    before = path.stat()
    data = path.read_bytes()
    result = {'exists':True, 'bytes':len(data)}
    if len(data) < 32:
        result['header_present'] = False
        return result
    magic, version, page_size, checkpoint, salt0, salt1, c0, c1 = struct.unpack('>8I',data[:32])
    if magic not in (0x377f0682,0x377f0683):
        result['valid_magic'] = False
        return result
    order = '<' if magic == 0x377f0682 else '>'
    result.update({'valid_magic':True, 'page_size':page_size, 'format_version':version})
    state = checksum(data[:24], (0,0), order)
    result['header_checksum_valid'] = state == (c0,c1)
    if not result['header_checksum_valid'] or not (512 <= page_size <= 65536):
        return result
    frames = commits = last_commit_frame = 0
    end = 'end_of_buffer'
    stride = 24 + page_size
    for pos in range(32, len(data)-stride+1, stride):
        frame = data[pos:pos+stride]
        page, db_size, a, b, fc0, fc1 = struct.unpack('>6I',frame[:24])
        if (a,b) != (salt0,salt1):
            end = 'old_generation_or_preallocated_tail'
            break
        candidate = checksum(frame[24:], checksum(frame[:8],state,order), order)
        if candidate != (fc0,fc1) or not page:
            end = 'invalid_or_incomplete_frame'
            break
        state = candidate
        frames += 1
        if db_size:
            commits += 1
            last_commit_frame = frames
    after = path.stat()
    result.update({'valid_prefix_frames':frames,'commit_markers_in_prefix':commits,
                   'last_commit_frame_in_prefix':last_commit_frame,'scan_end':end,
                   'metadata_stable_during_read':(before.st_size,before.st_mtime_ns,before.st_ino)==
                                               (after.st_size,after.st_mtime_ns,after.st_ino),
                   'live_sqlite_snapshot_guaranteed':False})
    return result


def inventory(root):
    accounts = []
    for idx, storage in enumerate(sorted(root.glob('*/db_storage'))):
        files = []
        for p in sorted(storage.rglob('*.db')):
            with p.open('rb') as f:
                header = f.read(16)
            files.append({'database':str(p.relative_to(storage)), 'bytes':p.stat().st_size,
                          'plain_sqlite_header':header==b'SQLite format 3\x00',
                          'wal':wal_info(Path(str(p)+'-wal'))})
        accounts.append({'account_index':idx,'database_count':len(files),'databases':files})
    return {'accounts':accounts,'message_content_read':False,'key_material_read':False}


def signatures(root):
    result = {}
    for i,p in enumerate(sorted(root.glob('*/db_storage'))):
        for f in p.rglob('*'):
            if f.is_file() and (f.name.endswith('.db') or f.name.endswith('.db-wal')):
                s = f.stat()
                result[f'{i}/{f.relative_to(p)}']=(s.st_size,s.st_mtime_ns,s.st_ino)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files')
    parser.add_argument('--observe-seconds',type=float,default=0)
    args=parser.parse_args()
    if not 0 <= args.observe_seconds <= 30:
        parser.error('observation must be between 0 and 30 seconds')
    result=inventory(args.root)
    if args.observe_seconds:
        a=signatures(args.root)
        time.sleep(args.observe_seconds)
        b=signatures(args.root)
        result['observation']={'seconds':args.observe_seconds,
            'changed_files':[k for k in sorted(set(a)|set(b)) if a.get(k)!=b.get(k)]}
    print(json.dumps(result,ensure_ascii=False,indent=2))
