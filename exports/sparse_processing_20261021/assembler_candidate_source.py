class SensorFrameAssembler:
    """Assemble whole samples; never combine packets from different counters.

    Packets can arrive in either order, with zero- or one-based numbering. Late
    completed frames are rejected, not delivered backwards. A counter reversal is
    ambiguous (restart vs stale traffic): report it and require an explicit reset.
    """

    def __init__(self, layout: DeviceLayout | None = None):
        self._configured_layout = layout
        self.reset()

    def reset(self):
        from uuid import uuid4

        self.layout = self._configured_layout
        self.valid_bits = self._valid_bits(self.layout) if self.layout else b""
        self.layout_confirmed = False
        self.stream_id = uuid4().hex
        self._pending = {}
        self._packet_base = None
        self._last_index = None
        self._last_payload = None
        self._last_contact_bits = None
        self._sample_index = 0
        self._issues = []

    @staticmethod
    def _valid_bits(layout: DeviceLayout) -> bytes:
        valid = bytearray([1]) * layout.bit_count
        for i in layout.invalid_bit_indices:
            valid[i] = 0
        return bytes(valid)

    @staticmethod
    def _packet_segment_count(count: int, payload: bytes) -> int | None:
        if count == 1:
            if len(payload) % 12 == 0 and 12 <= len(payload) <= 12 * 255:
                return len(payload) // 12
        elif 2 <= count <= 255 and len(payload) == 12:
            return count
        return None

    def pop_issues(self):
        issues, self._issues = self._issues, []
        return tuple(issues)

    def _discard_superseded_pending(self):
        if self._last_index is None:
            return
        for index in list(self._pending):
            # Accepted samples already account for these missing counters. Use
            # uint32 ordering so wraparound does not discard future fragments.
            if 0 < ((self._last_index - index) & 0xFFFFFFFF) < 0x80000000:
                del self._pending[index]

    def expire(self, now_ns):
        self._discard_superseded_pending()
        for index, node in list(self._pending.items()):
            if now_ns - node["created"] >= 1_000_000_000:
                base = self._packet_base
                missing = () if base is None else tuple(
                    i for i in range(len(self.layout.segments)) if i + base not in node["packs"]
                )
                self._issues.append(AcquisitionIssue("incomplete_frame", index, missing))
                del self._pending[index]
        if self._configured_layout is None and not self.layout_confirmed and not self._pending:
            self._packet_base = None

    def feed(self, packet, received_ns: int):
        self.expire(received_ns)
        index, count, part = packet.frameIdx, packet.packNum, packet.packIdx
        payload = bytes(packet.buffer)
        detected_count = self._packet_segment_count(count, payload)
        if not 0 <= index <= 0xFFFFFFFF or detected_count is None or not 0 <= part <= count:
            if index in self._pending:
                self._pending[index]["invalid"] = True
            self._issues.append(AcquisitionIssue("invalid_packet", index))
            return None
        if self._last_index is not None and ((index - self._last_index) & 0xFFFFFFFF) >= 0x80000000:
            self._issues.append(AcquisitionIssue("out_of_order_or_reset", index))
            return None
        if self._configured_layout is None and (
            self.layout is None or (
                not self.layout_confirmed
                and detected_count != len(self.layout.segments)
                and not self._pending
            )
        ):
            self.layout = DeviceLayout.linear(detected_count)
            self.valid_bits = self._valid_bits(self.layout)
            self._packet_base = None
        n = len(self.layout.segments)
        if detected_count != n:
            if index in self._pending:
                self._pending[index]["invalid"] = True
            self._issues.append(AcquisitionIssue("layout_mismatch", index))
            return None
        if count == 1:
            if index in self._pending:
                self._pending[index]["invalid"] = True
                self._issues.append(AcquisitionIssue("packet_count_changed", index))
                return None
            if len(payload) != self.layout.payload_bytes:
                self._issues.append(AcquisitionIssue("layout_mismatch", index))
                return None
        else:
            if len(payload) != 12:
                self._issues.append(AcquisitionIssue("invalid_packet_length", index))
                return None
            if part in (0, n):
                base = 0 if part == 0 else 1
                if self._packet_base is not None and base != self._packet_base:
                    if index in self._pending:
                        self._pending[index]["invalid"] = True
                    self._issues.append(AcquisitionIssue("packet_base_changed", index))
                    return None
                self._packet_base = base
            if index not in self._pending and len(self._pending) >= 128:
                oldest = next(iter(self._pending))
                del self._pending[oldest]
                self._issues.append(AcquisitionIssue("assembly_overflow", oldest))
            node = self._pending.setdefault(index, {"created": received_ns, "packs": {}, "invalid": False})
            old = node["packs"].get(part)
            if old is not None and old != payload:
                node["invalid"] = True
                self._issues.append(AcquisitionIssue("conflicting_packet", index))
            node["packs"][part] = payload
            base = self._packet_base
            if node["invalid"] or base is None or len(node["packs"]) != n:
                return None
            if set(node["packs"]) != set(range(base, base + n)):
                self._issues.append(AcquisitionIssue("invalid_packet_indices", index))
                del self._pending[index]
                return None
            payload = b"".join(node["packs"][i] for i in range(base, base + n))
            del self._pending[index]

        dropped = 0
        if self._last_index is not None:
            delta = (index - self._last_index) & 0xFFFFFFFF
            if delta == 0:
                if payload != self._last_payload:
                    self._issues.append(AcquisitionIssue("conflicting_frame", index))
                return None
            if delta >= 0x80000000:
                self._issues.append(AcquisitionIssue("out_of_order_or_reset", index))
                return None
            self._sample_index += delta
            dropped = delta - 1
        contact_bits = (self._last_contact_bits if payload == self._last_payload
                        else self.layout.contact_bits(payload))
        self._last_contact_bits = contact_bits
        self._last_index, self._last_payload = index, payload
        self._discard_superseded_pending()
        self.layout_confirmed = True
        flags = []
        if dropped:
            flags.append("frame_gap")
        if not any(payload):
            flags.append("all_beams_blocked")
        return SensorFrame(
            self.stream_id, self.layout, index, self._sample_index, received_ns,
            contact_bits, self.valid_bits, payload, dropped, tuple(flags),
        )
