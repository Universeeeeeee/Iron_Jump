"""Observe the real inbox; never treat an empty deque as an idle consumer."""
import threading
import time

# rows: host_ns, completed_sample, completed_receipt_ns, pending_count,
# oldest_pending_receipt_ns, latest_sample, latest_receipt_ns,
# unfinished_at_batch_boundary, popped_or_inflight, phase, batch_first,
# batch_last, batch_size. Pending age is exact at the locked snapshot.
# Unfinished uses batch completion boundaries (may include already processed
# frames in that batch); it is not a per-frame progress estimate.
class QueueProbe:
    def __init__(self, first_sample, detailed, final_sample=None):
        self.state=(first_sample-1,0,None)
        self.detailed=detailed;self.final_sample=final_sample
        self.common=[];self.samples=[];self.bucket=None
        self.stop_event=threading.Event();self.thread=None;self.errors=[]

    def snapshot(self,inbox):
        with inbox._lock:
            now=time.perf_counter_ns()
            completed,receipt,batch=self.state
            latest=inbox.quality.latest_received_frame
            if latest is None:return None
            pending=len(inbox._pending)
            oldest=inbox._pending[0][1].received_monotonic_ns if pending else None
            unfinished=latest.sample_index-completed
            assert unfinished>=pending>=0,(unfinished,pending)
            popped=unfinished-pending
            phase='batch' if batch else 'handoff' if popped else 'pending' if pending else 'empty'
            first,last,size=batch if batch else (None,None,0)
            return (now,completed,receipt,pending,oldest,latest.sample_index,
                    latest.received_monotonic_ns,unfinished,popped,phase,first,last,size)

    def consume(self,inbox,items,original):
        if not items:return original(inbox,items)
        first,last=items[0][1],items[-1][1]
        if self.detailed:self.state=(self.state[0],self.state[1],(first.sample_index,last.sample_index,len(items)))
        original(inbox,items)
        self.state=(last.sample_index,last.received_monotonic_ns,None)
        inbox.last_consumed_sample=last.sample_index
        bucket=last.sample_index//64
        if bucket!=self.bucket or last.sample_index==self.final_sample:
            self.bucket=bucket;row=self.snapshot(inbox)
            self.common.append(row)

    def start(self,inbox):
        if not self.detailed:return
        def sample():
            try:
                while not self.stop_event.wait(.1):
                    row=self.snapshot(inbox)
                    if row is not None:self.samples.append(row)
            except Exception as exc:self.errors.append(repr(exc))
        self.thread=threading.Thread(target=sample,daemon=True);self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(2)
        assert not self.errors,self.errors
        assert self.thread is None or not self.thread.is_alive()
