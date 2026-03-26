# ALBERT Root Cause Report (Real-only, no mock)

Date (UTC): 2026-03-19
Scope: `apps/openclaw-cockpit`
Meet under investigation: `https://meet.google.com/wst-jpqq-cew`

## 1) What exactly failed before

### A. Mock/fabricated output residue existed in persisted sessions
- `data/albert_sessions.json` had multiple historical sessions containing fabricated transcript/insights/summary content (e.g. fixed sample dialogue and executive summary text) not produced by a real transcription pipeline.
- This violates the requirement of real-only output.

### B. Join failure root cause for target Meet link
Real runs against `https://meet.google.com/wst-jpqq-cew` show the page state after join click as:
- **"You can't join this video call"**

Evidence:
- `data/albert_artifacts/alb-f91a48f3598f/last-page.html` contains `<h1 ...>You can't join this video call</h1>`
- `data/albert_artifacts/alb-325d2ecda787/last-page.html` same message

Interpretation:
- The meet room is rejecting guest/unauthed entry for this worker flow (policy/host restriction or equivalent block). This is a real platform-level denial, not a selector timeout.

### C. Worker robustness gaps before changes
- Very limited join-state detection (few markers; no explicit blocked-state branch).
- Sparse debug evidence (no saved HTML snapshot per run).
- Recording hook considered success when command returned `0` even if no long-running capture process remained active.
- `done` could be emitted with generic summary text even without real transcript pipeline.

---

## 2) What was changed

## Changed files
- `apps/openclaw-cockpit/albert_worker.py`
- `apps/openclaw-cockpit/data/albert_sessions.json` (sanitization of historical mock residues)

### Worker hardening (`albert_worker.py`)
1. **State detection expanded and explicit**
   - Added richer detection buckets: `prejoin`, `waiting_admit`, `joined`, `failed`, `unknown`.
   - Added explicit blocked/error markers including language variants and invalid/blocked join messages.
   - Returns `(state, reason)` for better diagnostics.

2. **Guest flow robustness improved**
   - More labels/selectors across EN/PT/ES for:
     - use-without-account gate,
     - name input,
     - mute/camera controls,
     - join/ask-to-join actions.

3. **Admit waiting loop improved**
   - Poll loop now tracks `prejoin/waiting_admit/unknown` and updates session to `waiting_admit` only when appropriate.

4. **Real evidence capture strengthened**
   - Saves screenshot and **full HTML snapshot** (`last-page.html`) for root-cause proof per session.
   - Runtime log now records state transitions with reason tags.

5. **No fake completion output**
   - `transcript`, `insights`, `summary` are kept empty unless real pipeline provides them.
   - Removed fabricated-style completion text behavior.

6. **`done` gating tightened (real criteria)**
   - Recording now starts via `subprocess.Popen` and waits 3s.
   - Only considered active if process remains alive (`poll() is None`).
   - `done` is emitted only after:
     - joined state confirmed by Meet UI markers, and
     - recording pipeline process confirmed active.
   - If recording process exits early => `failed` with concrete error.

### Data integrity cleanup
- Sanitized historical fake residues in `data/albert_sessions.json`:
  - Cleared mock transcript/insights/summary for 9 affected sessions.
  - Added `mockDataRemoved=true` and `mockDataRemovedAt` marker.
  - Appended timeline note about integrity cleanup.

---

## 3) Real test runs (timestamps, session ids, statuses)

## Environment checks
- Playwright Python package: installed (`True`)
- Chromium launch test: success (`Example Domain` title)

## Meet real runs against target link

1) **Session** `alb-f91a48f3598f`
- Created: `2026-03-19T16:03:45.800222+00:00`
- Updated: `2026-03-19T16:03:57.989853+00:00`
- Final status: **failed**
- Error: `blocked_or_invalid_meet`
- Runtime log: `data/albert_artifacts/alb-f91a48f3598f/runtime.log`
- Screenshot: `data/albert_artifacts/alb-f91a48f3598f/meet-proof.png`
- HTML evidence: `data/albert_artifacts/alb-f91a48f3598f/last-page.html`
- Key runtime line: `post-click state=failed reason=blocked_or_invalid_meet`

2) **Session** `alb-325d2ecda787`
- Created: `2026-03-19T16:04:27.066307+00:00`
- Updated: `2026-03-19T16:04:41.215923+00:00`
- Final status: **failed**
- Error: `blocked_or_invalid_meet`
- Runtime log: `data/albert_artifacts/alb-325d2ecda787/runtime.log`
- Screenshot: `data/albert_artifacts/alb-325d2ecda787/meet-proof.png`
- HTML evidence: `data/albert_artifacts/alb-325d2ecda787/last-page.html`
- Key runtime line: `post-click state=failed reason=blocked_or_invalid_meet`

### Concrete failure text captured
- Found in both HTML snapshots: **"You can't join this video call"**

---

## 4) Runtime process status (app + worker)

Active after changes:
- App: `python3 app.py` (already running)
- Worker: `python3 albert_worker.py --poll-interval 2` (started and left running)

---

## 5) Final verdict

**Partially viable / blocked by meeting policy for this specific link.**

- The Albert pipeline is now stricter and real-only for progression/output (no fabricated transcript/summary/insights, stronger evidence, stricter done gating).
- For `https://meet.google.com/wst-jpqq-cew`, real join is currently blocked by Meet response: **"You can't join this video call"**.
- Therefore this link cannot reach `done` under real criteria right now; correct real outcome is **failed** with concrete evidence (as observed).
