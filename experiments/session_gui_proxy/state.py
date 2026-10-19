"""Confirmed actor state only; command enqueue is never operation completion."""
NOTIFICATIONS={'hop_event','jump_quality_notice','gait_step_event','device_message','device_state_changed','device_layout_changed','led_health_changed','beam_quality_notice','pause_state_changed'}

class State:
    def __init__(self):
        self.sequence=0;self.phase='new';self.is_running=False;self.is_paused=False;self.ready_key=None
        self.device_state='disconnected';self.layout=None;self.quality_status={};self.report=None;self.payload_end=False;self.last_control=None
    def apply(self,message,pid):
        if message['sequence']!=self.sequence+1 or message['pid']!=pid:raise ValueError('Actor output identity/order changed')
        kind=message['kind'];p=message['payload']
        if kind=='actor_ready':
            if self.phase!='new':raise ValueError('Duplicate actor readiness')
            self.phase='actor_ready'
        elif kind=='prepared':
            if self.phase!='actor_ready':raise ValueError('Prepare confirmation out of order')
            self.phase='prepared'
        elif kind=='readiness':self.quality_status=p
        elif kind=='ready_to_start':
            if self.phase!='prepared':raise ValueError('Arm boundary out of order')
            self.ready_key=p['quality_key'];self.phase='ready'
        elif kind=='started':
            if self.phase!='ready':raise ValueError('Start confirmation out of order')
            self.is_running=True;self.phase='running'
        elif kind=='command_received':pass
        elif kind=='command_rejected':
            if p['applied'] or p['status']!='unsupported':raise ValueError('Unexpected rejection semantics')
        elif kind=='command_completed':
            if not p['reader_stopped'] or not p['qt_thread_stopped']:raise ValueError('Unconfirmed measurement stop')
            if p['kind'] not in ('stop','discard') or self.phase not in ('running','ready','prepared'):raise ValueError('Invalid operation completion')
            self.last_control=p['kind'];self.is_running=False;self.is_paused=False;self.phase='stopped'
            self.quality_status={}
            if p['kind']=='discard':self.device_state='disconnected';self.layout=None
        elif kind=='report_value':
            if self.phase!='stopped':raise ValueError('Report before confirmed stop')
            self.report=p['report']
        elif kind=='payload_end':
            if self.phase!='stopped' or not p['transport_unconfirmed'] or not p['local_measurement_complete']:raise ValueError('Invalid data end')
            self.payload_end=True
        elif kind=='notification':
            name=p['signal'];args=p['args']
            if name not in NOTIFICATIONS:raise ValueError('Unknown GUI notification')
            if name=='device_state_changed':self.device_state=args[0]
            elif name=='device_layout_changed':self.layout=args[0]
            elif name=='pause_state_changed':self.is_paused=args[0]
        elif kind not in ('visual','snapshot','drained_eof'):raise ValueError('Unknown actor message')
        self.sequence=message['sequence'];return kind
    def finalize(self,actor,exitcode):
        if not self.payload_end or exitcode!=0 or not actor['complete']:raise ValueError('Actor completion unconfirmed')
        if not actor['reader_stopped'] or not actor['qt_thread_stopped'] or not actor['writer_stop_confirmed']:raise ValueError('Actor resources unconfirmed')
        if actor['outbox']['failure'] is not None or actor['outbox']['accepted']!=self.sequence or actor['outbox']['write_calls_returned']!=self.sequence:raise ValueError('Output not complete')
        if self.last_control=='stop' and self.report is None:raise ValueError('Missing report')
        self.phase='complete'
