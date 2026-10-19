"""Observe repeated pure-helper work; always execute the original helper."""
class Observer:
    def __init__(self):self.groups={};self.restores=[];self.calls=0
    def enable(self):
        from engine import ground_source_review as source
        from engine.modes import walking_processor as processor
        from engine import ground_position_evidence as position,ground_metric_evidence as metric
        original=source.assigned_sources;observer=self
        def call(group):
            record=group.get('recovery') or group.get('established_owner')
            # Keep every read field, including decisions that the original later ignores.
            signature=None if not record else (record['owner_id'],tuple(record['source_ids']),tuple((x['source_id'],x['outcome'],x['owner_id']) for x in group.get('source_decisions',[])))
            value=original(group);observer.calls+=1
            frozen=tuple(sorted(value))
            if signature not in observer.groups:observer.groups[signature]=dict(calls=0,result=frozen)
            slot=observer.groups[signature];assert slot['result']==frozen;slot['calls']+=1
            return value
        for module in (source,processor,position,metric):
            assert module.assigned_sources is original
            self.restores.append((module,original));module.assigned_sources=call
    def disable(self):
        for module,original in self.restores:module.assigned_sources=original
        self.restores=[]
    def result(self):
        return dict(calls=self.calls,distinct_effective_inputs=len(self.groups),repeat_calls=sum(x['calls']-1 for x in self.groups.values()),groups=[dict(input=key,**value) for key,value in self.groups.items()],original_executed_every_call=True,
                    limits='Input observation changes allocation and execution. Repetition proves potential reusable work, not a measured speedup, cache correctness under mutation, or backlog contribution.')
