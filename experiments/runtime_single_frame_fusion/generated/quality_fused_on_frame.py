def on_frame(self, frame):
    if self.done:
        if self._ground_mode and self.context is not None:
            # None means archive accepted raw evidence only, never measure it.
            self.frame_ready.emit(frame, None, True)
        return
    previous = self.last_frame
    self.last_frame = frame
    if self.context is None:
        projected = self._segments.observe(frame)
        if projected is None:
            self.preflight.invalidate("全部段持续全零，无可用段")
        else:
            self.preflight.feed(projected)
            if self.preflight.context:
                self.preflight.context = replace(self.preflight.context, segment_selection=self._segments.snapshot())
        self._publish()
        return
    if frame.layout != self._segments.source_layout or frame.stream_id != self.context.stream_id:
        self._record("device_changed", frame, (), "设备布局或数据流变化，结束本次采集")
        self.finish("device_changed")
        return
    if previous is not None and frame.sample_index <= previous.sample_index:
        self._record("counter_reset", frame, (), "设备采样计数回退")
        self.finish("counter_reset")
        return
    invalid = (len(frame.contact_bits) != frame.layout.bit_count or
               len(frame.valid_bits) != frame.layout.bit_count or b'\x00' in frame.valid_bits or
               any(flag != 'all_beams_blocked' or not self._ground_mode for flag in frame.quality_flags)
               or bool(frame.dropped_frames_before) or
               (previous is not None and frame.sample_index != previous.sample_index + 1))
    projected = self._segments.project(frame)
    if invalid:
        self._record("invalid_data", frame, (), "本段原始数据保留，事件与跨段指标不计入统计")
        self.frame_ready.emit(frame, projected, True)
        return
    restored = tuple(s for s in self._segments.snapshot()["excluded_segment_indices"]
                     if frame.contact_bits[s * 96:(s + 1) * 96] != b'\x01' * 96)
    if restored and restored != getattr(self, "_last_restored_segments", ()):
        self._record("excluded_segment_signal", frame, (),
                     "已剔除段重新出现信号：" + "、".join(str(s + 1) for s in restored) + "；本次有效布局保持固定，下次准备时重新识别")
    self._last_restored_segments = restored
    processed = masked_frame(projected, self.context.bad_indices)
    # Ground mode checks fixed-mask boundaries after its 10 ms optical filter.
    uncertain = not self._ground_mode and uncertain_contact(processed, self.context.bad_indices)
    if self._segments.regions and self._segments.regions[-1] > 0:
        occupied = {self._segments.regions[i // 96] for i, bit in enumerate(processed.contact_bits) if bit}
        if occupied:
            previous_regions = getattr(self, "_occupied_regions", occupied)
            if len(occupied) > 1 or occupied != previous_regions:
                uncertain = True
                self._record("excluded_segment_boundary", frame, (),
                             "运动跨越被剔除段的物理空隙，相关事件不配对、不补造距离指标")
            self._occupied_regions = occupied
    # Runtime observations are warnings, never new masks. Motion can produce similar signals.
    self._runtime.observe(processed)
    samples = self._runtime.policy.samples
    if self._runtime.healthy_samples < samples:
        self._runtime_suspicious_mask = None
        self._runtime_suspicious_indices = ()
    else:
        flagged = self._runtime.suspicious_mask
        if self._runtime.mask_changed:
            self._runtime_suspicious_mask = flagged
            self._runtime_suspicious_indices = tuple(np.flatnonzero(flagged).tolist())
    suspicious = self._runtime_suspicious_indices
    if suspicious:
        self._record("runtime_obstruction", frame, suspicious,
                     "运行中存在持续遮挡或高频变化，已保留原始记录供复核" if self._ground_mode else
                     "新增持续遮挡或高频变化，可能是停留/传感器异常；未动态屏蔽，该不确定区间不计入统计")
        if not self._ground_mode:
            uncertain = True
    elif uncertain and uncertain_contact(processed, self.context.bad_indices):
        self._record("masked_contact_boundary", frame, self.context.bad_indices,
                     "接触邻近不可用光束，当前事件及跨越该区间的指标排除")
    if not uncertain and not suspicious:
        self._last_event_key = None
    self.frame_ready.emit(frame, processed, uncertain)
