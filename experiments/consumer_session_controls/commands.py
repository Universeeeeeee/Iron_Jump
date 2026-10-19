"""Preserve original Walk command semantics; completion requires resource evidence."""
NOTIFICATIONS=('hop_event','jump_quality_notice','gait_step_event','device_message','device_state_changed','device_layout_changed','led_health_changed','beam_quality_notice','pause_state_changed')

def apply_control(controller,kind):
    if kind in ('pause','resume'):
        if not controller.is_running or controller.engine.overground is None:raise ValueError('Wrong phase or mode')
        before=(controller.is_running,controller.is_paused,controller._pause_pending)
        getattr(controller,kind)()
        if before!=(controller.is_running,controller.is_paused,controller._pause_pending):raise ValueError('Unexpected Walk pause transition')
        return dict(status='unsupported',applied=False,reason='ground_single_passage')
    if kind=='stop':
        if not controller.is_running:raise ValueError('Stop without running session')
        controller.stop('manual');return dict(status='pending_resource_confirmation',applied=False)
    if kind=='discard':
        if controller.is_running:raise ValueError('Cannot discard running session')
        controller.discard();return dict(status='pending_resource_confirmation',applied=False)
    raise ValueError('Unsupported control command')

def resources_stopped(controller,source,thread):
    reader=source.reader
    return controller._thread is None and (reader is None or not reader.is_alive()) and thread is not None and not thread.isRunning()

def bind_notifications(controller,emit):
    callbacks=[]
    for name in NOTIFICATIONS:
        def relay(*args,_name=name):emit('notification',dict(signal=_name,args=args))
        getattr(controller,name).connect(relay);callbacks.append(relay)
    return callbacks
