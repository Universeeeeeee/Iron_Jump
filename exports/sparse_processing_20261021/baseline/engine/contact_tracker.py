"""
contact_tracker.py — Contact-Based 实时步态事件检测器

从 ClusterTracker 的轨迹视图中检测触地/离地事件，
计算步长、步速、支撑时间等步态参数。

原嵌入在 data_show.py 的 UI 类中 (~300 行)，现抽离为独立可测试模块。

使用方式::

    from gait_npz_parser import ClusterTracker, extract_clusters
    from contact_tracker import ContactBasedGaitTracker

    tracker = ClusterTracker()
    gait = ContactBasedGaitTracker()

    # 每帧:
    clusters = extract_clusters(bits)
    tracker.update(timestamp, clusters)
    active_tracks = tracker.get_active_tracks_view()
    events = gait.process_frame(timestamp, active_tracks)
    for ev in events:
        if ev.kind == "touch":
            print(f"触地: 步长={ev.contact.step_length}")
        elif ev.kind == "lift":
            print(f"离地: 支撑={ev.contact.contact_duration}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    from .extra_parameter import compute_extra_parameters
except ImportError:
    try:
        from extra_parameter import compute_extra_parameters
    except ImportError:
        def compute_extra_parameters(*args, **kwargs):
            return {}


# ===================== 数据结构 =====================


@dataclass
class ContactState:
    """单个脚印 (contact) 的生命周期状态。"""

    contact_id: int
    track_id: Optional[int] = None
    status: str = "candidate"  # candidate | confirmed | lifted
    first_seen_time: float = 0.0
    last_seen_time: float = 0.0
    touch_time: Optional[float] = None
    lift_time: Optional[float] = None
    seen_count: int = 0
    miss_count: int = 0
    centroid_at_touch: Optional[float] = None
    latest_centroid: Optional[float] = None
    centroid_history: List[float] = field(default_factory=list)
    cluster_length_at_touch: Optional[float] = None
    latest_cluster_length: Optional[float] = None
    cluster_start_cm_at_touch: Optional[float] = None
    cluster_end_cm_at_touch: Optional[float] = None
    latest_cluster_start_cm: Optional[float] = None
    latest_cluster_end_cm: Optional[float] = None
    foot_label: Optional[str] = None  # "A" / "B" / None
    label_confidence: float = 0.0
    step_length: Optional[float] = None
    stride_time: Optional[float] = None
    velocity: Optional[float] = None
    contact_duration: Optional[float] = None
    matched_this_frame: bool = False
    is_initial_baseline: bool = False


@dataclass
class GaitStepEvent:
    """步态事件输出。

    ``process_frame()`` 在检测到触地或离地时返回此对象，
    上层 UI 据此更新图表和显示。
    """

    kind: str  # "touch" 或 "lift"
    contact: ContactState
    confirmed_time_s: float | None = None


# ===================== 主检测器 =====================


class ContactBasedGaitTracker:
    """基于对象跟踪的步态事件状态机。

    接收 ``ClusterTracker.get_active_tracks_view()`` 的输出，
    输出 touch/lift 事件及步态参数。
    """

    def __init__(
        self,
        contact_confirm_frames: int = 8,
        contact_lift_miss_frames: int = 10,
        min_step_interval: float = 0.5,
        arm_frames: int = 10,
        max_contact_age: float = 0.35,
        min_cluster_length: float = 12.0,
        max_centroid_jitter: float = 2.5,
        jitter_window: int = 4,
        ignore_initial_contacts: bool = False,
    ):
        self._contact_confirm_frames = contact_confirm_frames
        self._contact_lift_miss_frames = contact_lift_miss_frames
        self._min_step_interval = min_step_interval
        self._arm_frames = arm_frames
        self._max_contact_age = max_contact_age
        self._min_cluster_length = min_cluster_length
        self._max_centroid_jitter = max_centroid_jitter
        self._jitter_window = jitter_window
        self._ignore_initial_contacts = ignore_initial_contacts
        self.reset()

    def reset(self):
        """重置所有内部状态。"""
        # Armed 机制
        self._gait_armed = False
        self._no_contact_stable_frames = 0
        self._startup_frame_seen = False

        # Contact 管理
        self._next_contact_id = 1
        self.active_contacts: Dict[int, ContactState] = {}
        self._completed_contacts: List[ContactState] = []
        self.foot_contact_queue: List[int] = []

        # 上一次确认触地
        self._last_confirmed_touch_time = 0.0
        self._last_confirmed_touch_centroid: Optional[float] = None
        self._prev_touch_time_for_step = 0.0

        # 各脚历史
        self._foot_history: Dict[str, dict] = {"A": {}, "B": {}}
        self._foot_lift_time: Dict[str, Optional[float]] = {"A": None, "B": None}
        self._prev_cycle_data: Dict[str, dict] = {}

        # 计数器
        self.touch_count = 0
        self.lift_count = 0

        # 累积数据（供上层读取）
        self.stride_lengths: List[float] = []
        self.velocities: List[float] = []
        self.foot_a_support_times: List[float] = []
        self.foot_b_support_times: List[float] = []

        # 增量统计
        self.stride_sum = 0.0
        self.stride_count = 0
        self.velocity_sum = 0.0
        self.velocity_count = 0
        self.foot_a_support_sum = 0.0
        self.foot_b_support_sum = 0.0

        # 高阶指标
        self.latest_extra_metrics: dict = {}
        self.extra_metrics_history: List[dict] = []

        # 触地驱动高阶指标
        self.touch_extra_history: List[dict] = []
        self._last_touch_velocity_for_acc: Optional[float] = None
        self._last_touch_time_for_acc: Optional[float] = None
        self._last_touch_foot_label: Optional[str] = None

    # ---------------------------------------------------------------
    #  公共 API
    # ---------------------------------------------------------------

    def process_frame(
        self, timestamp: float, active_tracks: list
    ) -> List[GaitStepEvent]:
        """处理单帧轨迹视图，返回本帧产生的步态事件列表。

        参数:
            timestamp: 当前帧时间戳 (秒)
            active_tracks: ``ClusterTracker.get_active_tracks_view()`` 的返回值，
                每个元素为 dict: {"track_id", "centroid_cm", "length_cm", ...}

        返回:
            本帧产生的 GaitStepEvent 列表 (可能为空)
        """
        events: List[GaitStepEvent] = []

        # Step 1. Armed 机制：跑步机可忽略启动帧已有接触；
        # 其他模式仍需经历无接触静态期才算就绪。
        if self._ignore_initial_contacts:
            self._gait_armed = True
        else:
            if not active_tracks:
                self._no_contact_stable_frames += 1
            else:
                self._no_contact_stable_frames = 0
            if self._no_contact_stable_frames >= self._arm_frames:
                self._gait_armed = True

        # Step 2. 标记所有 contact 为本帧未匹配
        for c in self.active_contacts.values():
            c.matched_this_frame = False

        # Step 3. 用 track_id 匹配 contact
        for track in active_tracks:
            if track.get("miss_count", 0):
                continue
            contact = self._find_or_create_contact(track, timestamp)
            self._update_contact_seen(contact, track, timestamp)

        if self._ignore_initial_contacts and not self._startup_frame_seen:
            for contact in self.active_contacts.values():
                contact.is_initial_baseline = True
        self._startup_frame_seen = True

        # Step 4. 未匹配的 active contact 增加 miss_count
        for contact in self.active_contacts.values():
            if not contact.matched_this_frame and contact.status in (
                "candidate",
                "confirmed",
            ):
                contact.miss_count += 1

        # Step 5. candidate -> confirmed（触发 touch 事件）
        events.extend(self._confirm_new_contacts(timestamp))

        # Step 6. confirmed/candidate -> lifted（触发 lift 事件）
        events.extend(self._finalize_lost_contacts(timestamp))

        return events

    # ---------------------------------------------------------------
    #  内部方法
    # ---------------------------------------------------------------

    def _find_or_create_contact(
        self, track: dict, timestamp: float
    ) -> ContactState:
        track_id = track["track_id"]
        # 找已有绑定
        for contact in self.active_contacts.values():
            if contact.track_id == track_id and contact.status in (
                "candidate",
                "confirmed",
            ):
                return contact
        # 建新 contact
        cid = self._next_contact_id
        self._next_contact_id += 1
        contact = ContactState(
            contact_id=cid,
            track_id=track_id,
            status="candidate",
            first_seen_time=timestamp,
            last_seen_time=timestamp,
            seen_count=0,
            miss_count=0,
        )
        self.active_contacts[cid] = contact
        return contact

    def _update_contact_seen(
        self, contact: ContactState, track: dict, timestamp: float
    ):
        centroid = float(track["centroid_cm"])
        length_cm = float(track.get("length_cm", 0.0))
        cluster_start_cm = track.get("cluster_start_cm")
        cluster_end_cm = track.get("cluster_end_cm")
        contact.matched_this_frame = True
        contact.last_seen_time = timestamp
        contact.seen_count += 1
        contact.miss_count = 0
        contact.latest_centroid = centroid
        contact.latest_cluster_length = length_cm
        contact.latest_cluster_start_cm = (
            float(cluster_start_cm) if cluster_start_cm is not None else None
        )
        contact.latest_cluster_end_cm = (
            float(cluster_end_cm) if cluster_end_cm is not None else None
        )
        if contact.seen_count == 1:
            contact.centroid_at_touch = centroid
            contact.cluster_length_at_touch = length_cm
            contact.cluster_start_cm_at_touch = contact.latest_cluster_start_cm
            contact.cluster_end_cm_at_touch = contact.latest_cluster_end_cm
        contact.centroid_history.append(centroid)

    def _confirm_new_contacts(self, timestamp: float) -> List[GaitStepEvent]:
        events: List[GaitStepEvent] = []
        if not self._gait_armed:
            return events

        candidates = [
            c
            for c in self.active_contacts.values()
            if c.status == "candidate"
            and not c.is_initial_baseline
            and c.seen_count >= self._contact_confirm_frames
        ]
        candidates.sort(key=lambda c: c.first_seen_time)

        for contact in candidates:
            # 新生窗口限制
            if timestamp - contact.first_seen_time > self._max_contact_age:
                continue
            # 簇长度门槛
            if (
                contact.latest_cluster_length is None
                or contact.latest_cluster_length < self._min_cluster_length
            ):
                continue
            # 短窗质心抖动过滤
            if len(contact.centroid_history) >= self._jitter_window:
                recent = contact.centroid_history[-self._jitter_window :]
                jitter = max(recent) - min(recent)
                if jitter > self._max_centroid_jitter:
                    continue
            # 最小步态间隔
            if (
                timestamp - self._last_confirmed_touch_time
            ) < self._min_step_interval:
                continue

            contact.status = "confirmed"
            contact.touch_time = contact.first_seen_time
            if contact.centroid_at_touch is None:
                contact.centroid_at_touch = contact.latest_centroid
            if contact.cluster_length_at_touch is None:
                contact.cluster_length_at_touch = contact.latest_cluster_length
            if contact.cluster_start_cm_at_touch is None:
                contact.cluster_start_cm_at_touch = contact.latest_cluster_start_cm
            if contact.cluster_end_cm_at_touch is None:
                contact.cluster_end_cm_at_touch = contact.latest_cluster_end_cm

            self._handle_touch(contact)

            self._last_confirmed_touch_time = contact.touch_time
            self._last_confirmed_touch_centroid = contact.centroid_at_touch
            events.append(GaitStepEvent(kind="touch", contact=contact))

        return events

    def _handle_touch(self, contact: ContactState):
        """触地事件内部处理：计算步长、步速、高阶指标。"""
        self.touch_count += 1
        self.foot_contact_queue.append(contact.contact_id)

        # 推断左右脚
        foot_label, confidence = self._infer_foot_label(contact)
        contact.foot_label = foot_label
        contact.label_confidence = confidence
        if foot_label in ("A", "B") and confidence >= 0.7:
            self._last_touch_foot_label = foot_label

        # 计算步长和步速
        if (
            self._last_confirmed_touch_centroid is not None
            and contact.centroid_at_touch is not None
        ):
            step_length = abs(
                contact.centroid_at_touch - self._last_confirmed_touch_centroid
            )
            contact.step_length = step_length

            dt = contact.touch_time - self._prev_touch_time_for_step
            if dt > 1e-6:
                contact.stride_time = dt
                contact.velocity = step_length / dt

                self.stride_lengths.append(step_length)
                self.velocities.append(contact.velocity)
                self.stride_sum += step_length
                self.stride_count += 1
                self.velocity_sum += contact.velocity
                self.velocity_count += 1

                # 触地驱动高阶代理指标
                touch_extra = {
                    "imbalance_index": None,
                    "double_support": None,
                    "single_support": None,
                    "acceleration": None,
                }
                if len(self.stride_lengths) >= 2:
                    prev_stride = self.stride_lengths[-2]
                    denom = max(
                        (step_length + prev_stride) / 2.0, 1e-6
                    )
                    touch_extra["imbalance_index"] = (
                        abs(step_length - prev_stride) / denom * 100.0
                    )
                touch_extra["single_support"] = dt

                if (
                    self._last_touch_velocity_for_acc is not None
                    and self._last_touch_time_for_acc is not None
                ):
                    dtt = (
                        contact.touch_time - self._last_touch_time_for_acc
                    )
                    if dtt > 1e-6:
                        touch_extra["acceleration"] = (
                            contact.velocity
                            - self._last_touch_velocity_for_acc
                        ) / dtt

                self._last_touch_velocity_for_acc = contact.velocity
                self._last_touch_time_for_acc = contact.touch_time
                self.touch_extra_history.append(touch_extra)

        self._prev_touch_time_for_step = contact.touch_time

        # 高置信度进入严格历史
        if (
            contact.foot_label in ("A", "B")
            and contact.label_confidence >= 0.7
        ):
            foot = contact.foot_label
            hist = self._foot_history[foot]
            hist["touch_time"] = contact.touch_time
            hist["centroid"] = contact.centroid_at_touch
            hist["stride_length_cm"] = contact.step_length
            hist["stride_time"] = contact.stride_time
            hist["velocity_cm_s"] = contact.velocity
            hist["is_airborne"] = False
            prev_lift = self._foot_lift_time.get(foot)
            if prev_lift is not None:
                hist["flight_duration"] = contact.touch_time - prev_lift

    def _infer_foot_label(self, new_contact: ContactState):
        """推断新触地脚印的左右脚标签。"""
        confirmed_on_ground = [
            self.active_contacts[cid]
            for cid in self.foot_contact_queue
            if cid in self.active_contacts
            and self.active_contacts[cid].status == "confirmed"
        ]
        confirmed_on_ground = [
            c
            for c in confirmed_on_ground
            if c.contact_id != new_contact.contact_id
        ]
        labeled = [
            c
            for c in confirmed_on_ground
            if c.foot_label in ("A", "B") and c.label_confidence >= 0.7
        ]
        if len(labeled) == 1:
            other = labeled[0]
            new_label = "B" if other.foot_label == "A" else "A"
            return new_label, 0.8
        if self._last_touch_foot_label in ("A", "B"):
            new_label = "B" if self._last_touch_foot_label == "A" else "A"
            return new_label, 0.7
        return "A", 0.7

    def _finalize_lost_contacts(
        self, timestamp: float
    ) -> List[GaitStepEvent]:
        events: List[GaitStepEvent] = []
        to_lift = []
        for contact in self.active_contacts.values():
            if contact.status in ("candidate", "confirmed"):
                if contact.miss_count >= self._contact_lift_miss_frames:
                    to_lift.append(contact)

        to_lift.sort(
            key=lambda c: c.touch_time
            if c.touch_time is not None
            else c.first_seen_time
        )
        for contact in to_lift:
            if contact.status == "confirmed":
                self._handle_lift(contact)
                events.append(GaitStepEvent(kind="lift", contact=contact))
            else:
                # 丢弃从未确认的噪点 candidate
                self.active_contacts.pop(contact.contact_id, None)
        return events

    def _handle_lift(self, contact: ContactState):
        """离地事件内部处理：计算支撑时间、高阶指标。"""
        contact.status = "lifted"
        contact.lift_time = contact.last_seen_time

        if (
            contact.touch_time is not None
            and contact.lift_time >= contact.touch_time
        ):
            contact.contact_duration = (
                contact.lift_time - contact.touch_time
            )

        self.lift_count += 1

        if contact.contact_id in self.foot_contact_queue:
            self.foot_contact_queue.remove(contact.contact_id)

        # 高置信度标签脚印离地时触发高阶推演
        if (
            contact.foot_label in ("A", "B")
            and contact.label_confidence >= 0.7
        ):
            foot = contact.foot_label
            self._foot_lift_time[foot] = contact.lift_time
            hist = self._foot_history[foot]
            hist["lift_time"] = contact.lift_time
            hist["contact_duration"] = contact.contact_duration
            hist["is_airborne"] = True

            if foot == "A" and contact.contact_duration:
                self.foot_a_support_times.append(contact.contact_duration)
                self.foot_a_support_sum += contact.contact_duration
            elif foot == "B" and contact.contact_duration:
                self.foot_b_support_times.append(contact.contact_duration)
                self.foot_b_support_sum += contact.contact_duration

            opposite = "B" if foot == "A" else "A"
            try:
                extra = compute_extra_parameters(
                    cycle_data_main=dict(hist),
                    cycle_data_opposite=dict(
                        self._foot_history[opposite]
                    ),
                    prev_cycle_data=self._prev_cycle_data.get(foot),
                )
                self.latest_extra_metrics = extra
                self.extra_metrics_history.append(extra)
                self._prev_cycle_data[foot] = dict(hist)
            except Exception as e:
                print(f"[Extra Metrics] Calc Error: {e}")

        self._completed_contacts.append(contact)
        self.active_contacts.pop(contact.contact_id, None)


__all__ = [
    "ContactState",
    "GaitStepEvent",
    "ContactBasedGaitTracker",
]
