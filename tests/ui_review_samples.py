"""Consistent synthetic jump events for UI review; never used by the application."""

from statistics import mean, pstdev

from config.test_report import JumpResultRecord, JumpTestReport, _jump_heights, _cadences


def jump_report():
    air = (0.50, 0.52, 0.48)
    contact = (0.20, 0.21, 0.19)
    cycles = tuple(a + c for a, c in zip(air, contact))
    heights = _jump_heights(air)
    cadences = _cadences(cycles)
    touch = 0.1
    results = []
    for index, (flight, stance, height, cycle, cadence) in enumerate(
        zip(air, contact, heights, cycles, cadences), 1
    ):
        lift = touch + stance
        touch = lift + flight
        results.append(JumpResultRecord(
            index=index, lift_time_s=lift, touch_time_s=touch,
            air_time_s=flight, jump_height_m=height, contact_time_s=stance,
            cycle_time_s=cycle, cadence_jumps_per_min=cadence,
            is_included_in_statistics=True,
        ))
    return JumpTestReport(
        touch_count=4, lift_count=3, air_times=air, contact_times=contact,
        cycle_times=cycles, avg_jump_height=mean(heights), max_jump_height=max(heights),
        avg_air_time=mean(air), max_air_time=max(air), avg_contact_time=mean(contact),
        avg_cadence=mean(cadences), finish_reason="manual", jump_heights=heights,
        cadences=cadences, min_jump_height=min(heights), std_jump_height=pstdev(heights),
        min_air_time=min(air), std_air_time=pstdev(air), min_contact_time=min(contact),
        max_contact_time=max(contact), std_contact_time=pstdev(contact),
        jump_results=tuple(results), report_config_snapshot={"data_source": "simulation"},
    )
