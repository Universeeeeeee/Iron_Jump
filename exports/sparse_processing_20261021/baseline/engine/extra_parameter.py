import math
from typing import Dict, List, Optional, Any

def compute_extra_parameters(
    cycle_data_main: Dict[str, Any],
    cycle_data_opposite: Optional[Dict[str, Any]] = None,
    prev_cycle_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Optional[float]]:
    """
    计算基于时空步态数据的扩展派生参数。
    所有参数根据物理与临床运动学推导规范实现。

    Args:
        cycle_data_main: 本侧腿当前步态周期的基础指标
            必填键: 
             - touch_time: float (触地时间)
             - lift_time: float (离地时间)
             - next_touch_time: float (下一次触地时间)
             - stride_time: float (步态周期时长)
             - stride_length_cm: float (步幅，同一侧脚两次着地的距离)
             - flight_duration: float (腾空时间)
             - contact_duration: float (支撑时间)

        cycle_data_opposite: 对侧腿在同期（或重叠期）的步态数据，用于计算双足协调参数。
            选填键: touch_time, lift_time, flight_duration

        prev_cycle_data: 本侧腿上一个步态周期的基础指标，用于计算加速度等差分参数。
            选填键: velocity_cm_s, stride_time

    Returns:
        Dict[str, float]: 扩展计算出的步态参数集合，如果前置必要数据不足，对应键值为 None。
    """
    metrics: Dict[str, Optional[float]] = {
        "single_support": None,
        "double_support": None,
        "load_response": None,
        "pre_swing": None,
        "step_time": None,
        "acceleration": None,
        "imbalance_index": None
    }

    # ==========================
    # 1. 基础物理形态参数计算
    # ==========================
    # 加速度 (Acceleration)
    # 差分本步平均速度与上一步平均速度。
    if prev_cycle_data is not None:
        v_current = cycle_data_main.get("velocity_cm_s")
        v_prev = prev_cycle_data.get("velocity_cm_s")
        t_current = cycle_data_main.get("stride_time")
        if v_current is not None and v_prev is not None and t_current and t_current > 0:
            accel = (v_current - v_prev) / t_current
            metrics["acceleration"] = round(accel, 3)

    # ==========================
    # 2. 双足关联支撑相计算 (需对侧数据)
    # ==========================
    if cycle_data_opposite is not None:
        main_touch = cycle_data_main.get("touch_time")
        main_lift = cycle_data_main.get("lift_time")
        main_contact = cycle_data_main.get("contact_duration")
        main_stride_time = cycle_data_main.get("stride_time")
        
        opp_touch = cycle_data_opposite.get("touch_time")
        opp_lift = cycle_data_opposite.get("lift_time")
        opp_flight = cycle_data_opposite.get("flight_duration")
        opp_contact = cycle_data_opposite.get("contact_duration")

        # 单支撑期 (Single Support): 本侧在支撑时，对侧正处于腾空期
        if opp_flight is not None:
            metrics["single_support"] = round(opp_flight, 3)

        # Step Time: 本侧触地到对侧触地之间的时间
        if main_touch is not None and opp_touch is not None:
            metrics["step_time"] = round(abs(opp_touch - main_touch), 3)

        if main_touch is not None and main_lift is not None and opp_touch is not None and opp_lift is not None:
            # 负荷反应期 (DS1/Load Response): 对侧即将离地，本侧刚落地的重叠态
            if opp_lift > main_touch:
                metrics["load_response"] = round(opp_lift - main_touch, 3)
            
            # 摆动前期 (DS2/Pre-Swing): 本侧即将离地，对侧刚落地的重叠态
            if main_lift > opp_touch:
                metrics["pre_swing"] = round(main_lift - opp_touch, 3)

        # 双支撑期 (Double Support): 包含所有两脚完全着地的时期
        # 公式推导：如果在完整一个周期(stride)内，理论值为 双脚各自触地时间之和 减去 总周期耗时 
        if main_contact is not None and opp_contact is not None and main_stride_time:
            double_support = main_contact + opp_contact - main_stride_time
            # 若结果小于0，说明存在飞行期，不是严谨步态或者不同步，可重置为计算直接的 DS1+DS2
            if double_support >= 0:
                metrics["double_support"] = round(double_support, 3)
            else:
                ds1 = metrics.get("load_response", 0) or 0
                ds2 = metrics.get("pre_swing", 0) or 0
                if ds1 > 0 or ds2 > 0:
                    metrics["double_support"] = round(ds1 + ds2, 3)

        # 不平衡指数 (Imbalance): 以两侧接触时间的差异评定步态不对称性
        if main_contact and opp_contact and (main_contact + opp_contact) > 0:
            imbalance = abs(main_contact - opp_contact) / ((main_contact + opp_contact) / 2.0) * 100.0
            metrics["imbalance_index"] = round(imbalance, 2)

    return metrics
