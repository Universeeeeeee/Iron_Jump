"""Bound accepted IPC output, including in-flight data; failures never mean delivered."""
from collections import deque
import hashlib
import json
import pickle
from pathlib import Path
import threading

class OutboxError(RuntimeError):pass

class Outbox:
    def __init__(self,connection,max_messages=128,max_bytes=8*1024*1024):
        if max_messages<=0 or max_bytes<=0:raise ValueError('Positive output bounds required')
        self.connection=connection;self.max_messages=max_messages;self.max_bytes=max_bytes
        self.condition=threading.Condition();self.queue=deque();self.inflight=None
        self.accepting=True;self.failure=None;self.accepted=0;self.written=0;self.last_written=0
        self.resident_bytes=0;self.high_bytes=0;self.high_messages=0
        self.thread=threading.Thread(target=self._run,name='SessionOutputWriter',daemon=True);self.thread.start()

    def _fail(self,reason,sequence=None,packet=None,detail=None):
        if self.failure is None:
            self.failure=dict(reason=reason,sequence=sequence,packet_bytes=None if packet is None else len(packet),packet_sha256=None if packet is None else hashlib.sha256(packet).hexdigest(),detail=detail)
        self.accepting=False;self.condition.notify_all()

    def enqueue(self,message):
        try:packet=pickle.dumps(message,protocol=5);sequence=message['sequence']
        except Exception as exc:
            with self.condition:self._fail('serialization_failed:'+type(exc).__name__,detail=repr(exc))
            raise OutboxError('Output serialization failed') from exc
        with self.condition:
            if self.failure is not None:raise OutboxError('Output has a retained failure')
            count=len(self.queue)+int(self.inflight is not None)
            if not self.accepting:reason='output_closed'
            elif sequence!=self.accepted+1:reason='sequence_mismatch'
            elif len(packet)>self.max_bytes:reason='oversized_packet'
            elif count+1>self.max_messages:reason='message_limit'
            elif self.resident_bytes+len(packet)>self.max_bytes:reason='byte_limit'
            else:reason=None
            if reason is not None:
                self._fail(reason,sequence,packet);raise OutboxError(reason)
            self.queue.append((sequence,packet));self.accepted=sequence;self.resident_bytes+=len(packet)
            self.high_bytes=max(self.high_bytes,self.resident_bytes);self.high_messages=max(self.high_messages,count+1)
            self.condition.notify_all()

    def _run(self):
        while True:
            with self.condition:
                while not self.queue and self.accepting and self.failure is None:self.condition.wait()
                if self.failure is not None or not self.queue:return
                self.inflight=self.queue.popleft();sequence,packet=self.inflight
            try:self.connection.send_bytes(packet)
            except Exception as exc:
                with self.condition:self._fail('send_failed:'+type(exc).__name__,sequence,packet,repr(exc))
                return
            with self.condition:
                self.written+=1;self.last_written=sequence;self.resident_bytes-=len(packet);self.inflight=None
                self.condition.notify_all()

    def finish(self,timeout=2):
        with self.condition:self.accepting=False;self.condition.notify_all()
        self.thread.join(timeout)
        with self.condition:
            if self.thread.is_alive():self._fail('writer_stop_unconfirmed')
            return not self.thread.is_alive() and self.failure is None and not self.queue and self.inflight is None

    def snapshot(self):
        with self.condition:
            return dict(accepted=self.accepted,write_calls_returned=self.written,last_write_returned_sequence=self.last_written,
                accepting=self.accepting,failure=self.failure,writer_alive=self.thread.is_alive(),
                accepted_resident_messages=len(self.queue)+int(self.inflight is not None),accepted_resident_bytes=self.resident_bytes,
                high_accepted_messages=self.high_messages,high_accepted_bytes=self.high_bytes,max_messages=self.max_messages,max_bytes=self.max_bytes,
                pending_sequences=[s for s,p in ([self.inflight] if self.inflight else [])+list(self.queue)],
                parent_application_receipt_confirmed=False)

    def preserve(self,folder):
        folder=Path(folder);folder.mkdir(exist_ok=False)
        with self.condition:
            state=self.snapshot();pending=([self.inflight] if self.inflight else [])+list(self.queue)
        files={}
        for sequence,packet in pending:
            name=f'unconfirmed_{sequence:08d}.pickle'
            with (folder/name).open('xb') as f:f.write(packet)
            files[name]=hashlib.sha256(packet).hexdigest()
        with (folder/'state.json').open('x',encoding='utf-8') as f:json.dump(dict(state=state,unconfirmed_files=files,
            meaning='Snapshot of unconfirmed output; a write may subsequently return. Never proves parent application receipt.'),f,indent=2)
        return state

    def abort(self,reason):
        with self.condition:self._fail(reason)
