"""Run the current landing-foot classifier without USB, camera, or MediaPipe."""

from __future__ import annotations

import argparse
from pathlib import Path



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay saved foot contacts")
    parser.add_argument("session", help="Path to a vision_session directory")
    parser.add_argument(
        "--output-dir",
        help="Output directory (defaults to the session directory)",
    )
    parser.add_argument(
        "--mode",
        choices=("landing-v1", "visual-evidence-v2", "phase-resync-v1", "compare"),
        default="landing-v1",
    )
    parser.add_argument(
        "--inject-phase-slip-at",
        type=int,
        help="Replay-only: invert immutable device labels from this event id",
    )
    parser.add_argument(
        "--phase-slip-injections",
        type=int,
        help="Run this many deterministic random phase-slip injection trials",
    )
    parser.add_argument("--seed", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from vision.replay import (
        compare_replay,
        replay_session,
        run_phase_slip_injections,
        write_replay_outputs,
    )
    from vision.session import load_csv, load_session

    session = Path(args.session).expanduser().resolve()
    if args.phase_slip_injections is not None:
        if args.mode != "phase-resync-v1":
            raise SystemExit("--phase-slip-injections requires --mode phase-resync-v1")
        import json

        _metadata, paths = load_session(session)
        summary = run_phase_slip_injections(
            load_csv(paths.contact_events),
            count=args.phase_slip_injections,
            seed=args.seed,
        )
        output = Path(args.output_dir).expanduser().resolve() if args.output_dir else session
        output.mkdir(parents=True, exist_ok=True)
        summary_path = output / "phase_slip_injections.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Injection summary: {summary_path}")
        print(
            f"Recoverable={summary['recoverable_injections']} "
            f"Recovered={summary['recovered_injections']} "
            f"Rate={summary['phase_slip_recovery_rate'] * 100.0:.2f}% "
            f"P95 contacts={summary['recovery_contacts_p95']}"
        )
        return 0
    if args.mode == "compare":
        import json

        summary = compare_replay(session)
        output = Path(args.output_dir).expanduser().resolve() if args.output_dir else session
        output.mkdir(parents=True, exist_ok=True)
        summary_path = output / "replay_compare.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Compare: {summary_path}")
        return 0
    summary, rows = replay_session(
        session,
        mode=args.mode,
        inject_phase_slip_at=args.inject_phase_slip_at,
    )
    summary_path, events_path = write_replay_outputs(
        Path(args.output_dir).expanduser().resolve() if args.output_dir else session,
        summary,
        rows,
    )
    if args.mode == "phase-resync-v1":
        print(f"Events: {summary['total_events']}")
        print(f"Automatic flips: {summary['automatic_phase_flips']}")
        print(f"Recovered: {summary['phase_slip_recovered']}")
        print(f"Recovery contacts: {summary['recovery_contact_count']}")
    else:
        _print_summary(summary)
    print(f"Summary: {summary_path}")
    print(f"Events:  {events_path}")
    return 0


def _print_summary(summary: dict) -> None:
    def percent(key: str) -> str:
        return f"{float(summary[key]) * 100.0:.2f}%"

    print(f"Total Events: {summary['total_events']}")
    print(
        f"Ground Truth: Left={summary['left_ground_truth']} "
        f"Right={summary['right_ground_truth']}"
    )
    print(
        f"Correct={summary['correct']} Wrong={summary['wrong']} "
        f"Unknown={summary['unknown']}"
    )
    print(
        f"Accuracy={percent('accuracy')} "
        f"Accepted Accuracy={percent('accepted_accuracy')} "
        f"Coverage={percent('coverage')} "
        f"Unknown Rate={percent('unknown_rate')} "
        f"Accepted Error Rate={percent('accepted_error_rate')}"
    )
    print(f"High-confidence Wrong Count: {summary['high_confidence_wrong_count']}")
    wrong_ids = summary.get("wrong_event_ids") or []
    print("Wrong event_id: " + (", ".join(wrong_ids) if wrong_ids else "none"))
    for scenario, values in summary.get("scenarios", {}).items():
        print(
            f"[{scenario}] events={values['total_events']} "
            f"correct={values['correct']} wrong={values['wrong']} "
            f"unknown={values['unknown']} "
            f"accepted_accuracy={values['accepted_accuracy'] * 100.0:.2f}% "
            f"coverage={values['coverage'] * 100.0:.2f}%"
        )


if __name__ == "__main__":
    raise SystemExit(main())
