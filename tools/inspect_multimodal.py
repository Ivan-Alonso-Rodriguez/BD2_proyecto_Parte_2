"""Inspección física: python tools/inspect_multimodal.py ARCHIVO --page 0."""
import argparse
import json
import struct
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.core.storage.disk_manager import DiskManager


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('file',type=Path)
    p.add_argument('--page',type=int,default=0)
    args=p.parse_args()
    if not args.file.is_file():raise SystemExit('Archivo inexistente')
    with DiskManager(args.file) as disk:
        raw=disk.read_page(args.page)
        result={'file':args.file.name,'page':args.page,'byte_offset':args.page*4096,'pages':disk.num_pages(),'magic':raw[:8].rstrip(b'\0').decode('ascii',errors='replace')}
        magic=raw[:4]
        if magic==b'RTR2':
            _,version,d,root,capacity,count=struct.unpack_from('<4sIIIIQ',raw)
            result.update(version=version,dimensions=d,root=root,capacity=capacity,entries=count)
        elif magic==b'RTN2':
            _,page,leaf,count=struct.unpack_from('<4sIBH',raw)
            result.update(page_id=page,leaf=bool(leaf),entries=count)
        elif raw[:8]==b'ATARRAY2':
            _,size,page_size,count=struct.unpack_from('<8sIIQ',raw)
            result.update(record_bytes=size,page_bytes=page_size,records=count)
        elif magic==b'IVF2':
            _,d,n,metric=struct.unpack_from('<4sIQI',raw)
            result.update(dimensions=d,vectors=n,metric='COSINE' if metric else 'L2')
        elif magic in (b'IVL2',b'BLB2'):
            _,page,count,nxt=struct.unpack_from('<4sIIi',raw)
            result.update(page_id=page,count=count,next_page=nxt)
        result['first_64_bytes_hex']=raw[:64].hex(' ')
        result['io']=disk.counter.snapshot()
        print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
