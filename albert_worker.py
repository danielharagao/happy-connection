from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from albert_store import AlbertStore, utc_now_iso

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None
    PlaywrightTimeoutError = Exception

BASE_DIR = Path(__file__).resolve().parent
APP_ENV = (os.environ.get("OPENCLAW_COCKPIT_ENV") or os.environ.get("APP_ENV") or "prod").strip().lower()
if APP_ENV in {"dev", "development"}:
    DATA_DIR = BASE_DIR / "data-dev"
elif APP_ENV in {"test", "testing"}:
    DATA_DIR = BASE_DIR / "data-test"
else:
    DATA_DIR = BASE_DIR / "data"


def _session_artifact_paths(store: AlbertStore, session_id: str) -> tuple[Path, Path, Path]:
    artifact_dir = store.artifacts_dir / session_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    screenshot = artifact_dir / "meet-proof.png"
    run_log = artifact_dir / "runtime.log"
    page_html = artifact_dir / "last-page.html"
    return artifact_dir, screenshot, run_log, page_html


def _build_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger(f"albert-worker-{log_path.parent.name}")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    return logger


def _normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def _try_click_by_text(page, labels: list[str], logger: logging.Logger) -> bool:
    for label in labels:
        # 1) role=button
        try:
            el = page.get_by_role("button", name=label)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(timeout=2500)
                logger.info("clicked button(role): %s", label)
                return True
        except Exception:
            pass

        # 2) button with text
        try:
            el = page.locator(f'button:has-text("{label}")')
            if el.count() > 0 and el.first.is_visible():
                el.first.click(timeout=2500)
                logger.info("clicked button(css): %s", label)
                return True
        except Exception:
            pass

        # 3) generic visible text node
        try:
            el = page.get_by_text(label, exact=False)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(timeout=2500)
                logger.info("clicked text node: %s", label)
                return True
        except Exception:
            pass
    return False


def _set_guest_name(page, logger: logging.Logger, guest_name: str) -> None:
    selectors = [
        'input[aria-label="Your name"]',
        'input[aria-label="Seu nome"]',
        'input[aria-label="Tu nombre"]',
        'input[placeholder="Your name"]',
        'input[placeholder="Seu nome"]',
        'input[type="text"]',
    ]
    for selector in selectors:
        try:
            el = page.locator(selector)
            if el.count() > 0 and el.first.is_visible():
                el.first.fill(guest_name, timeout=3000)
                logger.info("guest name filled via selector=%s", selector)
                return
        except Exception:
            continue
    logger.info("guest name field not found")


def _get_page_text(page) -> str:
    try:
        return _normalize_text(page.inner_text("body"))
    except Exception:
        try:
            return _normalize_text(page.content())
        except Exception:
            return ""


def _detect_join_state(page) -> tuple[str, str]:
    text = _get_page_text(page)
    if not text:
        return "unknown", "empty_page"

    blocked_markers = [
        "you can't join this video call",
        "you can’t join this video call",
        "não é possível participar desta chamada",
        "não é possível participar desta videochamada",
        "this meeting is not available",
        "meeting code is invalid",
        "código da reunião inválido",
    ]
    if any(x in text for x in blocked_markers):
        return "failed", "blocked_or_invalid_meet"

    waiting_markers = [
        "asking to join",
        "you'll join the call when someone lets you in",
        "you will join the call when someone lets you in",
        "ask to join sent",
        "requesting to join",
        "waiting to be admitted",
        "pedido para participar enviado",
        "aguardando alguém admitir você",
        "aguardando admissão",
        "esperando que alguém admita você",
        "solicitação enviada",
    ]
    if any(x in text for x in waiting_markers):
        return "waiting_admit", "join_request_sent"

    joined_markers = [
        "leave call",
        "sair da chamada",
        "call controls",
        "meeting details",
        "detalhes da reunião",
        "you joined",
        "você entrou",
    ]
    if any(x in text for x in joined_markers):
        return "joined", "in_meeting_ui_detected"

    prejoin_markers = [
        "use without an account",
        "usar sem uma conta",
        "continuar sem uma conta",
        "join now",
        "participar agora",
        "ask to join",
        "pedir para participar",
    ]
    if any(x in text for x in prejoin_markers):
        return "prejoin", "prejoin_screen"

    return "unknown", "no_known_markers"


def _snapshot_debug(page, html_path: Path, logger: logging.Logger) -> None:
    try:
        html_path.write_text(page.content(), encoding="utf-8")
        logger.info("saved debug html: %s", html_path)
    except Exception as exc:
        logger.error("could not save debug html: %s", exc)


def _start_recording_pipeline(session_id: str, artifact_dir: Path, logger: logging.Logger) -> tuple[bool, str, dict[str, Any]]:
    cmd = os.environ.get("ALBERT_AUDIO_CAPTURE_CMD", "").strip()
    if not cmd:
        return False, "ALBERT_AUDIO_CAPTURE_CMD not configured", {"status": "missing_cmd"}

    filled = cmd.format(session_id=session_id, artifact_dir=str(artifact_dir))
    logger.info("starting recording pipeline command: %s", filled)
    try:
        proc = subprocess.Popen(
            filled,
            shell=True,
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        logger.error("recording pipeline spawn failed: %s", exc)
        return False, f"recording spawn failed: {exc}", {"status": "spawn_error"}

    time.sleep(3.0)
    rc = proc.poll()
    if rc is not None:
        logger.error("recording process exited early rc=%s", rc)
        return False, f"recording process exited early rc={rc}", {"status": "exited", "exitCode": rc}

    detail = {"status": "running", "pid": proc.pid, "startedAt": utc_now_iso(), "command": filled}
    logger.info("recording pipeline active pid=%s", proc.pid)
    return True, "recording pipeline active", detail


def _click_join_flow(page, logger: logging.Logger) -> bool:
    # Guest/non-account entry gates
    _try_click_by_text(
        page,
        [
            "Use without an account",
            "Continue without an account",
            "Usar sem uma conta",
            "Continuar sem uma conta",
            "Usar sin una cuenta",
            "Continuar sin una cuenta",
        ],
        logger,
    )
    page.wait_for_timeout(900)

    _set_guest_name(page, logger, "Albert | Danhausch Notes")

    # Try muting by keyboard first (stable across locales)
    for key in ["Control+e", "Control+d"]:
        try:
            page.keyboard.press(key)
        except Exception:
            pass

    # Also try explicit buttons in multiple locales
    _try_click_by_text(
        page,
        [
            "Turn off microphone",
            "Turn off camera",
            "Desativar microfone",
            "Desativar câmera",
            "Desactivar micrófono",
            "Desactivar cámara",
        ],
        logger,
    )

    clicked = _try_click_by_text(
        page,
        [
            "Ask to join",
            "Join now",
            "Join",
            "Pedir para participar",
            "Participar agora",
            "Participar",
            "Solicitar unirse",
            "Unirse ahora",
        ],
        logger,
    )
    logger.info("join-click-attempt=%s", clicked)
    return clicked


def _google_login_if_enabled(context, logger: logging.Logger) -> tuple[bool, str]:
    mode = (os.environ.get("ALBERT_AUTH_MODE") or "guest").strip().lower()
    if mode != "google":
        return True, "guest_mode"

    email = (os.environ.get("ALBERT_GOOGLE_EMAIL") or "").strip()
    password = os.environ.get("ALBERT_GOOGLE_PASSWORD") or ""
    if not email or not password:
        return False, "missing_google_credentials"

    page = context.new_page()
    try:
        page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(800)

        email_ok = False
        for sel in ['input#identifierId', 'input[type="email"]']:
            try:
                el = page.locator(sel)
                if el.count() and el.first.is_visible():
                    el.first.fill(email, timeout=5000)
                    email_ok = True
                    break
            except Exception:
                continue
        if not email_ok:
            return False, "google_email_input_not_found"

        _try_click_by_text(page, ["Next", "Próxima", "Avançar"], logger)
        page.wait_for_timeout(1500)

        pwd_ok = False
        for sel in ['input[name="Passwd"]', 'input[type="password"]']:
            try:
                el = page.locator(sel)
                if el.count() and el.first.is_visible():
                    el.first.fill(password, timeout=5000)
                    pwd_ok = True
                    break
            except Exception:
                continue
        if not pwd_ok:
            return False, "google_password_input_not_found_or_challenge"

        _try_click_by_text(page, ["Next", "Próxima", "Avançar"], logger)
        page.wait_for_timeout(2500)
        u = (page.url or "").lower()
        if "challenge" in u:
            return False, "google_challenge_required"
        logger.info("google auth completed (best effort)")
        return True, "google_auth_ok"
    except Exception as exc:
        return False, f"google_auth_failed:{exc}"
    finally:
        try:
            page.close()
        except Exception:
            pass


def process_job(store: AlbertStore, job: dict[str, Any]) -> None:
    session_id = str(job.get("sessionId") or "")
    meet_link = str(job.get("meetLink") or "").strip()
    artifact_dir, screenshot_path, run_log_path, html_debug_path = _session_artifact_paths(store, session_id)
    logger = _build_logger(run_log_path)

    artifacts = {
        "artifactDir": str(artifact_dir),
        "screenshot": str(screenshot_path),
        "runtimeLog": str(run_log_path),
        "debugHtml": str(html_debug_path),
    }
    store.patch_session(session_id, {"mode": "real", "artifacts": artifacts, "worker": {"pickedAt": utc_now_iso(), "jobId": job.get("id")}})
    logger.info("job started session=%s link=%s", session_id, meet_link)

    if sync_playwright is None:
        store.update_session(session_id, "failed", "Playwright não está instalado no ambiente Python.", extra={"error": "missing_playwright", "artifacts": artifacts})
        logger.error("missing playwright python package")
        return

    browser = None
    context = None
    page = None
    try:
        store.update_session(session_id, "joining", "Abrindo Google Meet e tentando entrada como convidado.", extra={"error": "", "artifacts": artifacts})
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=(os.environ.get("ALBERT_HEADLESS", "1") != "0"),
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(locale="en-US")

            ok_auth, auth_reason = _google_login_if_enabled(context, logger)
            if not ok_auth:
                store.update_session(
                    session_id,
                    "failed",
                    "Falha no login da conta Google do Albert.",
                    extra={"error": auth_reason, "artifacts": artifacts},
                )
                return

            page = context.new_page()
            page.goto(meet_link, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)

            _click_join_flow(page, logger)
            page.wait_for_timeout(2500)

            state, reason = _detect_join_state(page)
            logger.info("post-click state=%s reason=%s", state, reason)

            wait_secs = int(os.environ.get("ALBERT_WAIT_ADMIT_SECONDS", "120"))
            end = time.time() + max(15, wait_secs)
            while time.time() < end and state in {"prejoin", "waiting_admit", "unknown"}:
                if state == "waiting_admit":
                    store.update_session(session_id, "waiting_admit", "Aguardando admissão do anfitrião.", extra={"artifacts": artifacts, "joinStateReason": reason})
                page.wait_for_timeout(3000)
                state, reason = _detect_join_state(page)
                logger.info("poll state=%s reason=%s", state, reason)
                if state == "joined" or state == "failed":
                    break

            if state == "joined":
                store.update_session(
                    session_id,
                    "joined",
                    "Bot entrou na sala do Meet (entrada real confirmada por UI).",
                    extra={
                        "transcript": "",
                        "insights": [],
                        "summary": "",
                        "recording": {"status": "starting"},
                        "recordingPending": True,
                        "artifacts": artifacts,
                    },
                )

                ok, rec_msg, rec_info = _start_recording_pipeline(session_id, artifact_dir, logger)
                if ok:
                    store.update_session(
                        session_id,
                        "recording",
                        "Captura de áudio iniciada e processo ativo confirmado.",
                        extra={"recording": rec_info, "recordingPending": False, "artifacts": artifacts},
                    )
                    store.update_session(
                        session_id,
                        "done",
                        "Sessão concluída com evidência real: entrada no Meet + pipeline de gravação ativo.",
                        extra={
                            "recording": rec_info,
                            "recordingPending": False,
                            "transcript": "",
                            "insights": [],
                            "summary": "",
                            "artifacts": artifacts,
                        },
                    )
                else:
                    store.update_session(
                        session_id,
                        "failed",
                        "Entrou no Meet, mas pipeline de gravação não ficou ativo.",
                        extra={
                            "error": rec_msg,
                            "recording": rec_info,
                            "recordingPending": True,
                            "transcript": "",
                            "insights": [],
                            "summary": "",
                            "artifacts": artifacts,
                        },
                    )
            elif state == "waiting_admit":
                store.update_session(
                    session_id,
                    "waiting_admit",
                    "Pedido para participar enviado; aguardando anfitrião admitir.",
                    extra={"error": "", "joinStateReason": reason, "artifacts": artifacts},
                )
            elif state == "failed":
                store.update_session(
                    session_id,
                    "failed",
                    "Meet recusou/bloqueou a entrada do convidado para este link.",
                    extra={"error": reason, "artifacts": artifacts},
                )
            else:
                store.update_session(
                    session_id,
                    "failed",
                    "Não foi possível confirmar admissão/entrada no Meet.",
                    extra={"error": f"{state}:{reason}", "artifacts": artifacts},
                )

            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception as exc:
                logger.error("screenshot failed: %s", exc)
            _snapshot_debug(page, html_debug_path, logger)

            context.close()
            browser.close()
    except PlaywrightTimeoutError as exc:
        logger.error("playwright timeout: %s", exc)
        if page is not None:
            _snapshot_debug(page, html_debug_path, logger)
        store.update_session(session_id, "failed", "Timeout ao tentar entrar no Meet.", extra={"error": str(exc), "artifacts": artifacts})
    except Exception as exc:
        logger.exception("worker failed")
        if page is not None:
            _snapshot_debug(page, html_debug_path, logger)
        store.update_session(session_id, "failed", "Falha no worker real do Meet.", extra={"error": str(exc), "artifacts": artifacts})
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Albert Meet Worker")
    parser.add_argument("--once", action="store_true", help="Process only one due job and exit")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()

    store = AlbertStore(DATA_DIR)
    store.ensure()

    while True:
        job = store.pop_due_job()
        if job:
            process_job(store, job)
            if args.once:
                return 0
            continue
        if args.once:
            return 0
        time.sleep(max(0.5, args.poll_interval))


if __name__ == "__main__":
    sys.exit(main())
