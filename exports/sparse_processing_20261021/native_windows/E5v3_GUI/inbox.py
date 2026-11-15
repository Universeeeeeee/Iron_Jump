"""Bound received serialized packets; one bounded in-progress receive is separate."""
from collections import deque
import hashlib
import json
from pathlib import Path
import threading

class Inbox:
    def __init__(self,max_messages=128,max_bytes=8*1024*1024):
        self.max_messages=max_messages;self.max_bytes=max_bytes;self.condition=threading.Condition()
        self.queue=deque();self.bytes=0;self.incoming=None;self.closed=False;self.reader_done=False;self.end_detail=None
        self.received=0;self.high_messages=0;self.high_bytes=0
    def put(self,packet):
        if len(packet)>self.max_bytes:raise ValueError('Oversized received packet')
        with self.condition:
            self.incoming=packet
            while not self.closed and (len(self.queue)>=self.max_messages or self.bytes+len(packet)>self.max_bytes):self.condition.wait(.2)
            if self.closed:return False
            self.queue.append(packet);self.bytes+=len(packet);self.incoming=None;self.received+=1
            self.high_messages=max(self.high_messages,len(self.queue));self.high_bytes=max(self.high_bytes,self.bytes)
            return True
    def take(self,maximum=8):
        with self.condition:
            out=[self.queue.popleft() for _ in range(min(maximum,len(self.queue)))]
            self.bytes-=sum(len(v) for v in out);self.condition.notify_all();return out
    def ended(self,detail):
        with self.condition:self.reader_done=True;self.end_detail=detail;self.condition.notify_all()
    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()
    def snapshot(self):
        with self.condition:
            return dict(queued_messages=len(self.queue),queued_bytes=self.bytes,incoming_bytes=0 if self.incoming is None else len(self.incoming),
                received_packets=self.received,high_queued_messages=self.high_messages,high_queued_bytes=self.high_bytes,reader_done=self.reader_done,end_detail=self.end_detail,
                max_messages=self.max_messages,max_bytes=self.max_bytes,closed=self.closed)
    def preserve(self,folder):
        folder=Path(folder);folder.mkdir(exist_ok=False)
        with self.condition:packets=list(self.queue)+([] if self.incoming is None else [self.incoming]);state=self.snapshot()
        files={}
        for i,packet in enumerate(packets):
            name=f'unconsumed_{i:04d}.pickle'
            with (folder/name).open('xb') as f:f.write(packet)
            files[name]=hashlib.sha256(packet).hexdigest()
        with (folder/'state.json').open('x') as f:json.dump(dict(state=state,files=files),f,indent=2)
