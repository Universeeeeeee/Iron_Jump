# Visual foot reference module

This package is independent from the Iron_Jump engine and reports a rejectable
visual reference for timestamped touch events. It does not modify optical-grid
timing, treadmill rows, reports, or UI state.

## Mac MediaPipe L/R identity validator

The Mac tool is intentionally smaller than the Windows event validator. It
only checks whether MediaPipe keeps the anatomical left and right lower limbs
stable over time. It does not connect to the optical grid, classify contact,
calculate gait parameters, write CSV, or record video.

Install the Mac-validated dependency set. Do not use MediaPipe 1.0.1 for this
tool: it aborts inside the native Metal graph before Python can catch an error.

```bash
python -m pip install -r requirements-mac-mediapipe.txt
```

```bash
python tools/mac_mediapipe_validator.py \
  --camera-index 0 \
  --model models/pose_landmarker_full.task
```

Keep the pelvis, both knees, and both ankles visible. The window displays all
lower-body landmark names and qualities. `STABLE` means the raw MediaPipe L/R
assignment agrees with trusted temporal tracks; `AMBIGUOUS` exposes overlap,
an implausible jump, or a likely identity swap; `UNAVAILABLE` means the core
landmarks are missing/low quality or the tracker is warming up. The validator
does not silently swap MediaPipe labels. Press `Q` to exit. If macOS blocks the
camera, grant camera access to Terminal or the Python host in System Settings.

## Inputs and output

- `submit_frame(frame, captured_at_s)` accepts an unmirrored BGR frame and a
  timestamp already mapped into the host `time.perf_counter()` domain.
- `submit_touch_event(event_id, event_time_s)` accepts a touch event in the same
  monotonic clock domain.
- `decision_ready` emits `VisionDecision` with `left`, `right`, or `unknown`,
  a confidence value, and a reason. The low-level `both` enum is retained only
  for compatibility with earlier diagnostic data; it is not a current product
  target or acceptance label.
- Missing dependencies/models, stale windows, timeouts, low landmark quality,
  and inference errors return `unknown`; they never change optical-grid data.

```python
from vision import FootVisionService, VisionConfig

service = FootVisionService(
    VisionConfig(),
    r"C:\Iron_Jump\models\pose_landmarker_full.task",
)
service.decision_ready.connect(print)
service.start()

# Legacy cameras may connect directly only when their frame timestamp is already
# in the optical event's clock domain. TinySE uses the synchronized validator
# path described below instead.
capture.analysis_frame_ready.connect(service.submit_frame)

# Submit only touch events, using the optical event's perf_counter timestamp:
service.submit_touch_event(event_id=1, event_time_s=touch_time_s)

service.stop()
```

## Vision session dataset loop

The TinySE validator can save a complete replayable session package while
keeping native asynchronous recording (`video.mjpg` and `video.csv`):

```powershell
python tools/vision_event_validator.py `
  --camera tinyse `
  --model .\models\pose_landmarker_full.task `
  --output-root .\data\vision_sessions `
  --scenario random
```

Each run creates `YYYYMMDD_NNN/session.json`, `pose_frames.jsonl`,
`contact_events.csv`, `annotations.csv`, `video.mjpg`, and `video.csv`.
Recording failures are diagnostics and do not stop the optical-grid or online
vision path.

Annotate benchmark contacts with `L` / `R` / `S`, arrow keys or `A` / `D`, and
Space:

```powershell
python tools/annotate_foot_contacts.py .\data\vision_sessions\20260809_001
```

Existing annotations are preserved and the first unlabelled benchmark event is
selected when the tool is reopened. Replay uses saved Pose only:

```powershell
python tools/replay_foot_classifier.py .\data\vision_sessions\20260809_001
```

Select the replay path explicitly when tuning or testing phase recovery:

```powershell
python tools\replay_foot_classifier.py SESSION --mode visual-evidence-v2
python tools\replay_foot_classifier.py SESSION --mode compare
python tools\replay_foot_classifier.py SESSION `
  --mode phase-resync-v1 `
  --inject-phase-slip-at 20
python tools\replay_foot_classifier.py SESSION `
  --mode phase-resync-v1 `
  --phase-slip-injections 100 `
  --seed 20260812
```

It writes `replay_summary.json` and `replay_events.csv`, including overall and
per-scenario Accuracy, Accepted Accuracy, Coverage, Unknown Rate,
Accepted Error Rate, high-confidence wrong count, and wrong event IDs.

The first-release thresholds are uncalibrated starting values. Passing unit
tests proves software ordering and fallback behavior, not real-person label
accuracy.

### Unified Windows desktop tool

`vision_app.py` provides one QtPy launcher for recording, annotation, and
Replay. The packaged executable supports the same internal modes:

```text
IronJumpVisionTools.exe
IronJumpVisionTools.exe --record ...
IronJumpVisionTools.exe --annotate <session>
IronJumpVisionTools.exe --replay <session>
```

The launcher starts child tools through `QProcess`, remembers model/output
settings with `QSettings`, and distinguishes `recording`, `complete`, and
`partial` sessions. Annotation and Replay reject a session that is still being
recorded; a partial session requires an explicit warning acknowledgement.

Build on Windows with `build_vision_app.bat`. PyInstaller uses `onedir` and
writes `dist\IronJumpVisionTools\IronJumpVisionTools.exe`. Source, spec, and
72 related tests have been verified on the development machine, but the final
Windows build, TinySE camera, optical-grid DLL, and long-running hardware path
still require validation on the target Windows computer.

## Windows diagnostic

After installing dependencies and placing the MediaPipe Pose Landmarker Full
`.task` model locally:

```powershell
New-Item -ItemType Directory -Force .\models | Out-Null
Invoke-WebRequest `
  -Uri "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task" `
  -OutFile ".\models\pose_landmarker_full.task"

python tools\vision_live.py `
  --camera tinyse `
  --model .\models\pose_landmarker_full.task `
  --output vision-results.csv
```

The independent window continuously evaluates rolling visual windows (default
250 ms interval); press Q to exit. The live window uses a 0.65 reference-only
threshold and 80 ms pose sampling to keep CPU load bounded; the core module's
0.90 high-confidence fusion default is unchanged. The CSV records timestamps,
label, candidate label, confidence, rejection reason, and end-to-end latency.
Continuous visual state does not validate synchronization with the optical grid.

## Windows real-event validation

Run the sidecar validator by itself when both the Tiny SE camera and optical
grid are connected. It reuses the project's `SessionController` touch events
but does not write visual labels back to the engine or report:

```powershell
python tools\vision_event_validator.py `
  --camera tinyse `
  --mode treadmill-gait `
  --model .\models\pose_landmarker_full.task `
  --output .\vision-event-validation.csv
```

For treadmill modes the validator runs `landing_v2` plus the conservative
`FootPhaseManager`. After the preview appears, click **标定跑带方向**, then
click the visible belt rear and front points in that order. Until both points
are recorded, V2 returns `unknown/calibration_required`. The calibration is
session-local and is saved in `session.json`; moving the camera or changing its
resolution requires a new calibration. The **校正左右脚相位** button toggles
the session phase manually without rewriting completed history.

The validator stores the immutable `raw_device_label`, the current
`effective_device_label`, and `final_label` separately. Vision never replaces
one event directly. An automatic phase flip requires two high-quality crossed
mismatches covering opposite device labels (`device L→R`, `vision R→L`). A
single mismatch, `LL/RR`, device anomaly, or `unknown` cannot flip phase.

The live image overlays left/right hip, knee, ankle, heel, and foot-index
landmarks. Each real grid touch preserves an event image on the right. Press
`L`, `R`, or `U` to record manual left/right/unreviewable truth for the latest
event; press `Q` to exit. Older diagnostic files may contain `B`, but two-foot
landing is no longer part of the formal vision acceptance scope.

For TinySE, the validator first collects at least 30 frames over at least 0.8
seconds and maps the DirectShow sample clock into `time.perf_counter()`. It does
not start the optical-grid session until the UI shows `sync=ready`. Keep the
optical area clear during this warm-up and for another 1–2 seconds after the
grid session starts, then begin stepping. If the sample clock regresses, its
P95–P5 delivery uncertainty exceeds 40 ms, or its rolling drift exceeds 40 ms,
the session becomes `degraded` and affected events are exported as
`unknown/clock_sync_degraded`; legacy decode timestamps are never mixed into
the aligned stream.

`camera_callback_time_s` is captured at the Python ctypes callback entrance,
before copying the MJPEG buffer; `camera_legacy_time_s` remains the old
post-decode timestamp for comparison.

The validator uses a 250 ms pre-event window, a 200 ms post-event window, a
60 ms pose interval, and a 500 ms decision timeout. Each CSV row includes the
actual analysis/Pose FPS, inference attempts, successful Pose counts before and
after touch, maximum Pose gap, sync offset/uncertainty/sample period, and both
legacy and aligned camera timestamps. The exported camera frame index and
`camera_event_delta_ms` identify the latest analysis frame delivered when the
grid event reaches the validator. That same frame and its nearest cached pose
are used for the right-side event snapshot. The exact sync failure is retained in
`sync_reason`, and `sync_warmup_ms` records how long the initial mapping took;
the event-level fallback remains `unknown/clock_sync_degraded`. In Jump mode, an
initial touch without a preceding lift is retained as `baseline` but excluded
from landing coverage and accuracy.

Analysis FPS is calculated from aligned camera sample timestamps. Pose FPS is
calculated from successful result arrival times, so CPU inference backlog lowers
the displayed value instead of being hidden by evenly spaced sample timestamps.

Do not run this validator at the same time as the main application because both
would attempt to own the optical device. TinySE real synchronization quality
must be accepted on Windows hardware; Mac tests use synthetic timestamps only.

Controlled single-foot checks have produced 10/10 left and 10/10 right labels.
These simple runs do not establish robustness. Formal acceptance must use
independent truth across normal alternation, random order, repeated same-foot
contacts, movement outside the grid, crossed legs, mild stumbles, occlusion,
multiple subjects, and multiple sessions. The automatic timing path passes
only if sync is ready within 2 seconds, uncertainty P95 is at most 40 ms,
clean-event pose coverage is at least 80%, and decision latency P95 is at most
350 ms. High-confidence wrong Left/Right predictions are more serious than an
`unknown` rejection and must be reported separately.

After three controlled runs, this PowerShell summary checks the four automatic
timing and coverage measurements:

```powershell
$files = @(
  ".\vision-left.csv",
  ".\vision-right.csv",
  ".\vision-random.csv"
)
$rows = @($files | ForEach-Object { Import-Csv $_ })
$eligible = @($rows | Where-Object {
  $_.event_role -in @("grid_touch", "landing")
})

function Get-P95($values) {
  $sorted = @($values | Where-Object { $_ -ne "" } |
    ForEach-Object { [double]$_ } | Sort-Object)
  if ($sorted.Count -eq 0) { return [double]::NaN }
  $index = [int][Math]::Max(0, [Math]::Ceiling($sorted.Count * 0.95) - 1)
  return $sorted[$index]
}

$poseCovered = @($eligible | Where-Object {
  [int]$_.pose_before -ge 2 -and [int]$_.pose_after -ge 2
}).Count
$syncReady = @($eligible | Where-Object { $_.sync_status -eq "ready" }).Count

[pscustomobject]@{
  EligibleEvents      = $eligible.Count
  SyncReadyPercent    = if ($eligible.Count) {
    100 * $syncReady / $eligible.Count
  } else { 0 }
  SyncWarmupMaxMs     = (@($eligible.sync_warmup_ms |
    Where-Object { $_ -ne "" } | ForEach-Object { [double]$_ }) |
    Measure-Object -Maximum).Maximum
  UncertaintyP95Ms    = Get-P95 $eligible.sync_uncertainty_ms
  PoseCoveragePercent = if ($eligible.Count) {
    100 * $poseCovered / $eligible.Count
  } else { 0 }
  DecisionP95Ms       = Get-P95 $eligible.latency_ms
}
```
