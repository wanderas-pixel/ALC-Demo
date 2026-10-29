#!/usr/bin/env python3
"""
GCP-Native 5-Minute Executive Demo Video & UI Walkthrough Generator
- Voice-Over Synthesis: Google Cloud Text-to-Speech API (Neural2 / Journey / Studio HD voices)
- UI Walkthrough Capture: Headless Chromium (Playwright) at 1920x1080 against Cloud Run
- Video/Audio Mastering: FFmpeg H.264 + AAC 1080p MP4 pipeline on Google Cloud Build
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

import google.auth
import google.auth.transport.requests
import requests
from playwright.async_api import Page, async_playwright

COCKPIT_URL = os.environ.get(
    "COCKPIT_URL", "https://acme-abo-cockpit-101296135052.us-central1.run.app"
)
PROJECT_ID = os.environ.get("PROJECT_ID", "genai-demos-391416")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/workspace/video_output"))
FINAL_MP4_PATH = OUTPUT_DIR / "alc_executive_5min_demo.mp4"


# ---------------------------------------------------------------------------
# 5-Minute Executive Script Scenes (Voice-Over + Subtitles + UI Actions)
# ---------------------------------------------------------------------------
SCENES: List[Dict[str, Any]] = [
    {
        "id": "scene_01_intro_login",
        "beat": "BEAT 1/4 • PORTFOLIO RISK & ZERO-TOUCH ONBOARDING",
        "ai_pillar": "Google Cloud Agent Platform • Zero-Trust Portal Gate",
        "narration": (
            "Today, managing a commercial building portfolio comes with three massive hidden costs: "
            "it takes weeks of manual engineering just to map cryptic BMS point names for a single building; "
            "silent mechanical drift wastes up to twenty percent of HVAC energy without tripping a single alarm; "
            "and when a fault does happen, alarm storms trigger expensive four-hour technician truck rolls. "
            "Welcome to the Autonomous Building Operations Cockpit, built on Google Cloud for Automated Logic."
        ),
        "captions": [
            "Hidden Costs: Weeks of manual BMS point mapping, 20% silent HVAC energy waste, and 4-hour truck rolls.",
            "Autonomous Building Operations (ABO) Cockpit — Built on Google Cloud for Automated Logic (ALC).",
        ],
    },
    {
        "id": "scene_02_portfolio_and_kpis",
        "beat": "BEAT 1/4 • PORTFOLIO RISK & ZERO-TOUCH ONBOARDING",
        "ai_pillar": "Gemini + W3C SHACL-as-Reward • TimesFM 2.5 Risk Roll-Up",
        "narration": (
            "First, we eliminated the onboarding bottleneck. Using Gemini paired with a symbolic W3C SHACL validation loop, "
            "we automatically translated over five thousand raw BACnet points across five enterprise sites into a unified "
            "Brick and ASHRAE 223P Digital Twin—cutting onboarding from weeks to minutes. "
            "Second, look at our Hero Site in Atlanta. Traditional BMS dashboards say All Systems Nominal because room temperatures "
            "are holding at 72 degrees. Yet our portfolio ribbon flags Atlanta at a 74 percent AI Failure Risk, and Austin at 78 percent—using "
            "a worst-case asset roll-up so leadership is never blindsided by a single-point failure."
        ),
        "captions": [
            "Zero-Touch Semantic Onboarding: Gemini + SHACL maps 5,400+ raw BACnet points into Brick v1.4 & ASHRAE 223P in minutes.",
            "Executive Worst-Case Risk Roll-Up: Atlanta flagged at 74% AI Risk & Austin at 78% despite 'All Systems Nominal' BMS status.",
        ],
    },
    {
        "id": "scene_03_floor2_outliers",
        "beat": "BEAT 1/4 • PORTFOLIO RISK & ZERO-TOUCH ONBOARDING",
        "ai_pillar": "TimesFM 2.5 Zero-Shot Forecasting • Spatial CAD Digital Twin",
        "narration": (
            "On the first floor blueprint, we can inspect the physical supply ductwork and thermal heatmap across sixteen healthy zones. "
            "But watch what happens when we switch to the Second Floor. Immediately, two zones light up in amber-yellow: "
            "Second Floor Huddle and Open Office 232. When I click Second Floor Huddle, our top KPI strip immediately reveals why the building "
            "is at 74 percent AI Risk: Google's TimesFM 2.5 time-series foundation model has detected severe valve actuator hunting "
            "with a 36 to 48 hour failure horizon—giving facility leaders a two-day early warning before a single tenant complains."
        ),
        "captions": [
            "1st Floor CAD Blueprint: Real-time supply ductwork (brick:feeds) and thermal heatmap across 16 healthy zones.",
            "2nd Floor Discovery: 2F Huddle (PIU-1) & Open Office 232 (PIU-8) flagged by TimesFM 2.5 with a 74% risk (36–48h horizon).",
        ],
    },
    {
        "id": "scene_04_knowledge_graph",
        "beat": "BEAT 2/4 • HARD ROI: OPEX SAVINGS & SLA PROTECTION",
        "ai_pillar": "BigQuery Property Graph (ISO GQL) • Neuro-Symbolic GraphRAG",
        "narration": (
            "Let's open Tab 2: Knowledge Graph and AI Risk. Pure-LLM chatbots fail in commercial buildings because they hallucinate physical layouts. "
            "We solved this with Neuro-Symbolic GraphRAG powered by BigQuery Property Graph and ISO GQL. "
            "Every node is synchronized one-to-one with our floor plan colors, and AI automatically sorts our highest-risk outliers to the top. "
            "Selecting Second Floor Huddle PIU-1 deterministically traverses mechanical airflow from Rooftop AHU-2, spatial SLA boundaries, "
            "and BACnet controller routing with zero hallucination."
        ),
        "captions": [
            "Tab 2 — Neuro-Symbolic GraphRAG: BigQuery Property Graph (ISO GQL) eliminates LLM topology hallucinations.",
            "Deterministic 3-Layer Traversal: Mechanical (brick:feeds), Spatial (rec:locatedIn), and OT Network (bsm:routesTo).",
        ],
    },
    {
        "id": "scene_05_energy_zscores_mttr",
        "beat": "BEAT 2/4 • HARD ROI: OPEX SAVINGS & SLA PROTECTION",
        "ai_pillar": "Unsupervised Peer-Cohort ML (+3.42σ) • CMMS MTTR Regression",
        "narration": (
            "How much money is that silent drift costing us right now? Let's click Tab 5: Energy Z-Scores and MTTR. "
            "Our unsupervised machine learning benchmarks every terminal box against its peer cohort on the same air handler. "
            "It caught Second Floor Huddle at plus 3.42 standard deviations and Open Office 232 at plus 2.78 sigma—locked in simultaneous "
            "heating and cooling, where a leaking reheat valve fights cold primary air. In this one building alone, catching that invisible waste "
            "recovers 18,400 dollars per year and 42 metric tons of CO2. And by grounding live telemetry in historical CMMS work orders, "
            "the AI proves we can fix this in 18 minutes via a remote BACnet deadband recalibration instead of a 3.8-hour manual truck roll."
        ),
        "captions": [
            "Tab 5 — Unsupervised Peer-Cohort ML: Catches +3.42σ & +2.78σ simultaneous heating/cooling ($18,400/yr & 42 tCO₂ saved).",
            "CMMS-Grounded MTTR: Work Order WO-2026-0841 proves an 18-minute remote AI calibration replaces a 3.8-hour truck roll.",
        ],
    },
    {
        "id": "scene_06_multisite_austin",
        "beat": "BEAT 2/4 • HARD ROI: OPEX SAVINGS & SLA PROTECTION",
        "ai_pillar": "Multi-Site Portfolio Intelligence • Cleanroom Yield Protection",
        "narration": (
            "This intelligence scales across the entire enterprise portfolio. When I click our Austin Precision Manufacturing Plant—flagged "
            "at 78 percent AI Risk—the cockpit immediately focuses on the SMT PCB Assembly Line, where a plus 3.65 sigma desiccant wheel slip "
            "threatens 14,500 dollars per hour in cleanroom production yield. Let's return to our Atlanta headquarters to run a proactive failure simulation."
        ),
        "captions": [
            "Portfolio Scalability: Switching to Austin Manufacturing Plant (78% AI Risk) isolates SMT Cleanroom (+3.65σ, $14.5k/hr risk).",
            "Returning to ACME Emerald Crest HQ (Atlanta) for counterfactual blast-radius simulation.",
        ],
    },
    {
        "id": "scene_07_whatif_simulation",
        "beat": "BEAT 2/4 • HARD ROI: OPEX SAVINGS & SLA PROTECTION",
        "ai_pillar": "Counterfactual Blast-Radius Simulation • Non-Linear Thermal Physics",
        "narration": (
            "In the AI Building Co-Pilot on the right, let's click: What is the impact if RTU-1 fails? "
            "In milliseconds, our Root-Cause Agent traverses the BigQuery Property Graph and runs a physics-informed thermal simulation. "
            "It warns us that losing RTU-1 impacts 16 first-floor zones, including Tier-1 critical spaces. And while standard offices have "
            "a 95-minute thermal buffer, our Main IDF Server Room will breach its 80.6 degree ASHRAE ceiling in just 22 minutes due to dense IT rack heat loads."
        ),
        "captions": [
            "Co-Pilot Counterfactual Query: 'What is the impact if RTU-1 (1st Floor Air Handler) fails?'",
            "Physics-Informed Thermal Forecast: Main IDF Server Room (VAV 1-6) breaches 80.6°F SLA ceiling in just 22 minutes.",
        ],
    },
    {
        "id": "scene_08_trigger_alarm_storm",
        "beat": "BEAT 3/4 • OPERATIONAL RESILIENCE: 32 ALARMS TO 1 ROOT CAUSE",
        "ai_pillar": "Live Fault Injection (SCN-1) • Real-Time Spatial Triage",
        "narration": (
            "Now let's trigger that exact mechanical crisis live. A supply fan VFD belt slip and bearing over-temperature fault "
            "just hit Rooftop Unit 1. In a legacy building management system, as warm supply air floods the first floor, all 16 downstream VAV boxes "
            "starve for static pressure and trigger 32 simultaneous high-priority alarms. Look at what our AI Cockpit did in under two seconds: "
            "all 16 first-floor rooms turned amber as Muted Sympathetic Symptoms, while the AI isolated the single red Primary Root Fault to RTU-1."
        ),
        "captions": [
            "LIVE INCIDENT (SCN-1): Supply Fan VFD Belt Slip injected on RTU-1 triggers a 32-alarm cascading storm.",
            "Instant Spatial Isolation: 16 downstream 1st-floor zones marked as Muted Symptoms (Amber); RTU-1 isolated as Root Fault (Red).",
        ],
    },
    {
        "id": "scene_09_cross_layer_rca",
        "beat": "BEAT 3/4 • OPERATIONAL RESILIENCE: 32 ALARMS TO 1 ROOT CAUSE",
        "ai_pillar": "ASHRAE 223P / BSM OT Network Verification • >95% Alarm Noise Reduction",
        "narration": (
            "Before recommending any mechanical action, the AI verifies whether this is a real HVAC failure or an IT/OT network drop. "
            "In Tab 3: BACnet OT Network, our Triage Agent confirms zero percent packet loss across our BACnet IP core switch, "
            "Floor Router 301003, and all 90 ALC Optiflex controllers. "
            "In Tab 6: Alarms and Heartbeats, and inside the 3-Layer Causal Root-Cause Simulator, you can see how the AI collapsed 32 screaming alarms "
            "into 1 Critical Primary Root Cause on RTU-1 and automatically muted 31 downstream symptoms—eliminating over 95 percent of alarm noise."
        ),
        "captions": [
            "Tab 3 — Cross-Layer OT Verification: 0.0% packet loss across Router #301003 & 90 ALC controllers rules out cyber/network faults.",
            "Tab 6 & Causal Trace Modal: 32 alarms collapsed into 1 Primary Root Cause + 31 Muted Symptoms (>95% noise reduction).",
        ],
    },
    {
        "id": "scene_10_agent_platform_governance",
        "beat": "BEAT 4/4 • TRUSTED AUTONOMY: AGENT PLATFORM & 42s RECOVERY",
        "ai_pillar": "Vertex AI Agent Engine • Agent Gateways • IAM Identities • Cloud Trace",
        "narration": (
            "How can a CISO and VP of Operations trust autonomous AI to touch physical building infrastructure? "
            "Look at the governance telemetry in the AI Building Co-Pilot. This multi-agent system runs natively on Google Cloud's Vertex AI Agent Runtime "
            "and is cataloged in Agent Registry. Every turn is inspected by native Agent Gateways—Client-to-Agent for ingress and Agent-to-Anywhere for egress. "
            "Each subagent authenticates with its own least-privilege IAM service account so read-only triage agents can never write to hardware, "
            "and every step emits a live OpenTelemetry Cloud Trace link for complete end-to-end auditability."
        ),
        "captions": [
            "Enterprise Governance: Vertex AI Agent Runtime (5782923462607634432) + Agent Gateways (CLIENT_TO_AGENT & AGENT_TO_ANYWHERE).",
            "Zero-Trust Observability: Per-Agent IAM Service Accounts (sa-agent-*) + live W3C OpenTelemetry Cloud Trace links.",
        ],
    },
    {
        "id": "scene_11_closed_loop_remediation",
        "beat": "BEAT 4/4 • TRUSTED AUTONOMY: AGENT PLATFORM & 42s RECOVERY",
        "ai_pillar": "W3C SHACL & ASHRAE-36 Safety Guardrails • BACnet Priority-8 Closed-Loop Fix",
        "narration": (
            "Finally, look at the staged Human-in-the-Loop Remediation Card at the bottom right. "
            "Before this card could render, our Remediation Validator Agent verified the proposed BACnet Priority-8 command against "
            "W3C SHACL shapes and ASHRAE Guideline 36 safety envelopes. With safety verification passed, the operator clicks "
            "Approve and Execute Closed-Loop Recovery. "
            "Immediately, the governed BACnet command engages our backup air handler cross-tie, first-floor temperatures recover from "
            "75.8 degrees back to 71.8 degrees nominal, and all 16 zones return to emerald green. "
            "We just turned a 32-alarm crisis and a 4.2-hour truck roll into a 42-second, safety-governed recovery on Google Cloud. Thank you."
        ),
        "captions": [
            "Symbolic Safety Gate: Proposed BACnet Priority-8 command passes W3C SHACL & ASHRAE Guideline 36 verification (68°F–76°F).",
            "Closed-Loop Recovery Executed: 1F zones restored (75.8°F → 71.8°F) in 42 seconds vs. 4.2-hour manual truck roll!",
        ],
    },
]


# ---------------------------------------------------------------------------
# Step 1: Google Cloud Text-to-Speech API Synthesis
# ---------------------------------------------------------------------------
def get_gcp_access_token() -> str:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials.token


def synthesize_scene_audio(scene: Dict[str, Any], audio_dir: Path, token: str) -> float:
    """Synthesizes scene narration using Google Cloud Text-to-Speech API and returns duration in seconds."""
    scene_id = scene["id"]
    wav_path = audio_dir / f"{scene_id}.wav"
    mp3_path = audio_dir / f"{scene_id}.mp3"

    url = "https://texttospeech.googleapis.com/v1/text:synthesize"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID,
    }

    # Try Studio / Journey / Neural2 executive voices in priority order
    preferred_voices = [
        {"languageCode": "en-US", "name": "en-US-Journey-D"},
        {"languageCode": "en-US", "name": "en-US-Studio-O"},
        {"languageCode": "en-US", "name": "en-US-Neural2-D"},
    ]

    audio_bytes: Optional[bytes] = None
    used_voice = ""
    for voice_cfg in preferred_voices:
        payload = {
            "input": {"text": scene["narration"]},
            "voice": voice_cfg,
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": 1.03,
            },
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            audio_bytes = base64.b64decode(data["audioContent"])
            used_voice = voice_cfg["name"]
            break
        else:
            print(f"[TTS] Voice {voice_cfg['name']} returned {resp.status_code}: {resp.text[:160]}")

    if not audio_bytes:
        raise RuntimeError(f"Failed to synthesize TTS audio for {scene_id}")

    mp3_path.write_bytes(audio_bytes)

    # Convert MP3 to 44.1kHz stereo WAV with a 0.65s trailing pause for clean pacing
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mp3_path),
            "-af",
            "apad=pad_dur=0.65",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(wav_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Measure exact WAV duration via ffprobe
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(wav_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(probe.stdout.strip())
    print(f"[TTS] {scene_id} ({used_voice}): {duration:.2f}s")
    return duration


# ---------------------------------------------------------------------------
# Step 2: Playwright Presentation HUD & Animated Cursor Helpers
# ---------------------------------------------------------------------------
OVERLAY_INIT_JS = """
() => {
  if (document.getElementById('abo-exec-hud')) return;

  const style = document.createElement('style');
  style.textContent = `
    #abo-exec-hud {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    }
    #abo-beat-banner {
      position: fixed;
      top: 10px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(2, 6, 23, 0.92);
      border: 1px solid rgba(56, 189, 248, 0.55);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.65), 0 0 20px rgba(14, 165, 233, 0.25);
      border-radius: 9999px;
      padding: 6px 20px;
      display: flex;
      align-items: center;
      gap: 12px;
      backdrop-filter: blur(12px);
      transition: all 0.35s ease;
    }
    #abo-beat-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #38bdf8;
      box-shadow: 0 0 10px #38bdf8;
    }
    #abo-beat-title {
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      color: #f8fafc;
      text-transform: uppercase;
    }
    #abo-beat-sep {
      color: #475569;
      font-size: 12px;
    }
    #abo-beat-pillar {
      font-size: 11px;
      font-weight: 600;
      color: #38bdf8;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    #abo-caption-box {
      position: fixed;
      bottom: 18px;
      left: 50%;
      transform: translateX(-50%);
      max-width: 1180px;
      width: 78%;
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.93) 0%, rgba(2, 6, 23, 0.96) 100%);
      border: 1px solid rgba(148, 163, 184, 0.35);
      border-left: 4px solid #38bdf8;
      border-radius: 12px;
      padding: 11px 22px;
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(12px);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    #abo-caption-text {
      font-size: 15px;
      font-weight: 600;
      color: #f1f5f9;
      line-height: 1.4;
      letter-spacing: -0.01em;
    }
    #abo-caption-tag {
      font-size: 10px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 4px 9px;
      border-radius: 6px;
      background: rgba(14, 165, 233, 0.15);
      border: 1px solid rgba(56, 189, 248, 0.4);
      color: #7dd3fc;
      white-space: nowrap;
      flex-shrink: 0;
    }
    #abo-demo-spotlight {
      position: fixed;
      pointer-events: none;
      border: 2.5px solid #38bdf8;
      box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.22), 0 0 28px rgba(56, 189, 248, 0.55);
      border-radius: 12px;
      transition: all 0.45s cubic-bezier(0.22, 1, 0.36, 1);
      opacity: 0;
      z-index: 999997;
    }
    #abo-demo-cursor {
      position: fixed;
      top: 540px;
      left: 960px;
      width: 28px;
      height: 28px;
      pointer-events: none;
      z-index: 999999;
      transition: top 0.55s cubic-bezier(0.22, 1, 0.36, 1), left 0.55s cubic-bezier(0.22, 1, 0.36, 1), transform 0.15s ease;
      filter: drop-shadow(0 4px 10px rgba(0,0,0,0.85));
    }
    .abo-click-ring {
      position: fixed;
      width: 44px;
      height: 44px;
      border-radius: 50%;
      border: 3px solid #f59e0b;
      background: rgba(245, 158, 11, 0.25);
      pointer-events: none;
      z-index: 999998;
      transform: translate(-50%, -50%) scale(0.3);
      animation: aboRipple 0.65s ease-out forwards;
    }
    @keyframes aboRipple {
      0% { transform: translate(-50%, -50%) scale(0.3); opacity: 1; }
      100% { transform: translate(-50%, -50%) scale(2.1); opacity: 0; }
    }
  `;
  document.head.appendChild(style);

  const hud = document.createElement('div');
  hud.id = 'abo-exec-hud';
  hud.innerHTML = `
    <div id="abo-beat-banner">
      <div id="abo-beat-dot"></div>
      <div id="abo-beat-title">AUTONOMOUS BUILDING OPERATIONS</div>
      <div id="abo-beat-sep">|</div>
      <div id="abo-beat-pillar">Google Cloud Agent Platform</div>
    </div>
    <div id="abo-demo-spotlight"></div>
    <div id="abo-demo-cursor">
      <svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M5 3L23 13.5L14.5 16L19 24.5L15.5 26L11 17.5L5 22V3Z" fill="#38BDF8" stroke="#020617" stroke-width="2.2" stroke-linejoin="round"/>
      </svg>
    </div>
    <div id="abo-caption-box">
      <div id="abo-caption-text">Autonomous Building Operations (ABO) — Executive Walkthrough</div>
      <div id="abo-caption-tag">LIVE GCP COCKPIT</div>
    </div>
  `;
  document.body.appendChild(hud);
}
"""


async def ensure_hud(page: Page, beat: str, pillar: str, caption: str) -> None:
    await page.evaluate(OVERLAY_INIT_JS)
    await page.evaluate(
        """({beat, pillar, caption}) => {
            const bt = document.getElementById('abo-beat-title');
            const bp = document.getElementById('abo-beat-pillar');
            const ct = document.getElementById('abo-caption-text');
            if (bt) bt.textContent = beat;
            if (bp) bp.textContent = pillar;
            if (ct) ct.textContent = caption;
        }""",
        {"beat": beat, "pillar": pillar, "caption": caption},
    )


async def set_caption(page: Page, caption: str) -> None:
    await page.evaluate(
        """(caption) => {
            const ct = document.getElementById('abo-caption-text');
            if (ct) ct.textContent = caption;
        }""",
        caption,
    )


async def move_cursor_and_highlight(
    page: Page, selector_or_text: str, by_text: bool = False, click: bool = False, pad: int = 6
) -> bool:
    """Moves the visual cursor & spotlight box to the target element and optionally clicks it."""
    try:
        loc = page.get_by_text(selector_or_text, exact=False).first if by_text else page.locator(selector_or_text).first
        if await loc.count() == 0:
            return False
        await loc.scroll_into_view_if_needed(timeout=2000)
        box = await loc.bounding_box(timeout=2000)
        if not box:
            return False

        cx = box["x"] + box["width"] * 0.5
        cy = box["y"] + box["height"] * 0.5

        await page.evaluate(
            """({x, y, bx, by, bw, bh, pad}) => {
                const cur = document.getElementById('abo-demo-cursor');
                const spot = document.getElementById('abo-demo-spotlight');
                if (cur) {
                    cur.style.left = `${x}px`;
                    cur.style.top = `${y}px`;
                }
                if (spot) {
                    spot.style.left = `${bx - pad}px`;
                    spot.style.top = `${by - pad}px`;
                    spot.style.width = `${bw + pad * 2}px`;
                    spot.style.height = `${bh + pad * 2}px`;
                    spot.style.opacity = '1';
                }
            }""",
            {
                "x": cx,
                "y": cy,
                "bx": box["x"],
                "by": box["y"],
                "bw": box["width"],
                "bh": box["height"],
                "pad": pad,
            },
        )
        await asyncio.sleep(0.55)

        if click:
            await page.evaluate(
                """({x, y}) => {
                    const ring = document.createElement('div');
                    ring.className = 'abo-click-ring';
                    ring.style.left = `${x}px`;
                    ring.style.top = `${y}px`;
                    document.body.appendChild(ring);
                    setTimeout(() => ring.remove(), 700);
                }""",
                {"x": cx, "y": cy},
            )
            await loc.click(timeout=3000, force=True)
            await asyncio.sleep(0.35)
        return True
    except Exception as exc:
        print(f"[UI] Warning on target '{selector_or_text}': {exc}")
        return False


async def clear_spotlight(page: Page) -> None:
    await page.evaluate(
        """() => {
            const spot = document.getElementById('abo-demo-spotlight');
            if (spot) spot.style.opacity = '0';
        }"""
    )


async def wait_until_scene_end(scene_start: float, target_duration: float) -> None:
    elapsed = time.monotonic() - scene_start
    remaining = target_duration - elapsed
    if remaining > 0:
        await asyncio.sleep(remaining)


# ---------------------------------------------------------------------------
# Step 3: Scene-by-Scene Choreographed UI Walkthrough
# ---------------------------------------------------------------------------
async def run_ui_walkthrough(durations: Dict[str, float], raw_video_dir: Path) -> tuple[Path, float]:
    """Drives the live Cloud Run cockpit in 1920x1080 and returns (recorded_webm_path, trim_start_sec)."""
    # Reset live backend scenario state first
    try:
        requests.post(f"{COCKPIT_URL}/api/admin/reset", timeout=15)
    except Exception as e:
        print(f"[Setup] Reset warning: {e}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--window-size=1920,1080", "--disable-gpu", "--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            screen={"width": 1920, "height": 1080},
            record_video_dir=str(raw_video_dir),
            record_video_size={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        video_context_t0 = time.monotonic()
        page = await context.new_page()

        # Pre-load the login gate so there is no blank white frame at the start
        await page.goto(COCKPIT_URL, wait_until="networkidle", timeout=45000)
        await asyncio.sleep(0.4)

        # Exact timestamp where Scene 1 audio begins!
        walkthrough_t0 = time.monotonic()
        trim_start_sec = max(0.0, walkthrough_t0 - video_context_t0)
        print(f"[Video] Pre-roll trim offset: {trim_start_sec:.2f}s")

        # ===================================================================
        # SCENE 1: Intro & Portal Login Gate -> Unlock Operations Cockpit
        # ===================================================================
        s1 = SCENES[0]
        t_s1 = time.monotonic()
        await ensure_hud(page, s1["beat"], s1["ai_pillar"], s1["captions"][0])
        await asyncio.sleep(1.5)

        await move_cursor_and_highlight(page, 'input[type="text"]', click=True)
        await page.fill('input[type="text"]', "user")
        await asyncio.sleep(0.6)

        await move_cursor_and_highlight(page, 'input[type="password"]', click=True)
        await page.fill('input[type="password"]', "12345")
        await asyncio.sleep(0.6)

        await set_caption(page, s1["captions"][1])
        await move_cursor_and_highlight(page, "Unlock Operations Cockpit", by_text=True, click=True)
        await asyncio.sleep(1.5)
        await ensure_hud(page, s1["beat"], s1["ai_pillar"], s1["captions"][1])
        await clear_spotlight(page)
        await wait_until_scene_end(t_s1, durations[s1["id"]])

        # ===================================================================
        # SCENE 2: Portfolio Ribbon & 4-Card AI KPI Strip
        # ===================================================================
        s2 = SCENES[1]
        t_s2 = time.monotonic()
        await ensure_hud(page, s2["beat"], s2["ai_pillar"], s2["captions"][0])

        # Highlight KPI Card 1 (Building Asset Inventory) & KPI Card 4 (MTTR & Energy ROI)
        await move_cursor_and_highlight(page, "Building Asset Inventory", by_text=True, click=False, pad=10)
        await asyncio.sleep(3.2)
        await move_cursor_and_highlight(page, "Historical MTTR & Energy ROI", by_text=True, click=False, pad=10)
        await asyncio.sleep(3.2)

        await set_caption(page, s2["captions"][1])
        # Highlight Hero Site (Atlanta 74% Risk) & Austin Manufacturing (78% Risk)
        await move_cursor_and_highlight(page, "ACME Emerald Crest HQ", by_text=True, click=False, pad=8)
        await asyncio.sleep(3.5)
        await move_cursor_and_highlight(page, "ACME Sunbelt Precision Manufacturing", by_text=True, click=False, pad=8)
        await asyncio.sleep(3.0)
        await clear_spotlight(page)
        await wait_until_scene_end(t_s2, durations[s2["id"]])

        # ===================================================================
        # SCENE 3: 1st Floor Blueprint -> 2nd Floor Yellow Outliers (2F Huddle)
        # ===================================================================
        s3 = SCENES[2]
        t_s3 = time.monotonic()
        await ensure_hud(page, s3["beat"], s3["ai_pillar"], s3["captions"][0])

        await move_cursor_and_highlight(page, "Thermal Heatmap Overlay", by_text=True, click=True)
        await asyncio.sleep(2.2)
        await move_cursor_and_highlight(page, "Thermal Heatmap Overlay", by_text=True, click=True)
        await asyncio.sleep(1.0)

        await set_caption(page, s3["captions"][1])
        await move_cursor_and_highlight(page, "2nd Floor", by_text=True, click=True)
        await asyncio.sleep(2.0)

        # Click Huddle on the SVG map or inspect button
        await move_cursor_and_highlight(page, "Huddle", by_text=True, click=True)
        await asyncio.sleep(2.5)
        # Close slide-over drawer if open so full KPI strip is visible
        close_btn = page.locator('button:has-text("Close"), button[title*="Close"]').first
        if await close_btn.count() > 0:
            await close_btn.click(force=True)
        await move_cursor_and_highlight(page, "AI Failure Likelihood", by_text=True, click=False, pad=10)
        await wait_until_scene_end(t_s3, durations[s3["id"]])

        # ===================================================================
        # SCENE 4: Tab 2 — Knowledge Graph & AI Risk
        # ===================================================================
        s4 = SCENES[3]
        t_s4 = time.monotonic()
        await ensure_hud(page, s4["beat"], s4["ai_pillar"], s4["captions"][0])

        await move_cursor_and_highlight(page, "2. Knowledge Graph & AI Risk", by_text=True, click=True)
        await asyncio.sleep(2.5)

        await move_cursor_and_highlight(page, "2F Huddle PIU-1", by_text=True, click=True)
        await asyncio.sleep(2.5)

        await set_caption(page, s4["captions"][1])
        await move_cursor_and_highlight(page, "Connected Graph Neighbors", by_text=True, click=False, pad=10)
        await asyncio.sleep(3.0)
        await move_cursor_and_highlight(page, "AI Risk & Blast-Radius Assessment", by_text=True, click=False, pad=10)
        await wait_until_scene_end(t_s4, durations[s4["id"]])

        # ===================================================================
        # SCENE 5: Tab 5 — Energy Z-Scores & MTTR ($18,400/yr + WO-2026-0841)
        # ===================================================================
        s5 = SCENES[4]
        t_s5 = time.monotonic()
        await ensure_hud(page, s5["beat"], s5["ai_pillar"], s5["captions"][0])

        await move_cursor_and_highlight(page, "5. Energy Z-Scores & MTTR", by_text=True, click=True)
        await asyncio.sleep(2.2)

        await move_cursor_and_highlight(page, "$18,400/yr", by_text=True, click=False, pad=8)
        await asyncio.sleep(2.5)

        # Expand 2F Huddle row
        await move_cursor_and_highlight(page, "+3.42σ", by_text=True, click=True)
        await asyncio.sleep(2.5)

        await set_caption(page, s5["captions"][1])
        await move_cursor_and_highlight(page, "Typical Time-to-Fix (MTTR)", by_text=True, click=False, pad=8)
        await asyncio.sleep(3.0)
        await move_cursor_and_highlight(page, "WO-2026-0841", by_text=True, click=False, pad=8)
        await wait_until_scene_end(t_s5, durations[s5["id"]])

        # ===================================================================
        # SCENE 6: Multi-Site Portfolio Switch (Austin Manufacturing -> Back to HQ)
        # ===================================================================
        s6 = SCENES[5]
        t_s6 = time.monotonic()
        await ensure_hud(page, s6["beat"], s6["ai_pillar"], s6["captions"][0])

        await move_cursor_and_highlight(page, "ACME Sunbelt Precision Manufacturing", by_text=True, click=True, pad=8)
        await asyncio.sleep(3.0)
        await move_cursor_and_highlight(page, "SMT PCB Assembly Line", by_text=True, click=False, pad=8)
        await asyncio.sleep(3.2)

        await set_caption(page, s6["captions"][1])
        await move_cursor_and_highlight(page, "ACME Emerald Crest HQ", by_text=True, click=True, pad=8)
        await asyncio.sleep(1.5)
        await move_cursor_and_highlight(page, "1. Floor Plan & Devices", by_text=True, click=True)
        await move_cursor_and_highlight(page, "1st Floor", by_text=True, click=True)
        await wait_until_scene_end(t_s6, durations[s6["id"]])

        # ===================================================================
        # SCENE 7: What-If Counterfactual Blast-Radius Simulation
        # ===================================================================
        s7 = SCENES[6]
        t_s7 = time.monotonic()
        await ensure_hud(page, s7["beat"], s7["ai_pillar"], s7["captions"][0])

        await move_cursor_and_highlight(
            page, "What is the impact if RTU-1 (1st Floor Air Handler) fails?", by_text=True, click=True
        )
        await asyncio.sleep(3.0)

        await set_caption(page, s7["captions"][1])
        await move_cursor_and_highlight(page, "AI Blast-Radius & Root-Cause Simulator", by_text=True, click=True)
        await asyncio.sleep(4.2)

        # Close Blast-Radius modal before live fault trigger
        close_sim = page.get_by_text("Close Simulator", exact=False).first
        if await close_sim.count() > 0:
            await close_sim.click(force=True)
        await clear_spotlight(page)
        await wait_until_scene_end(t_s7, durations[s7["id"]])

        # ===================================================================
        # SCENE 8: Live Alarm Storm Injection (SCN-1 Cascading RTU-1 Failure)
        # ===================================================================
        s8 = SCENES[7]
        t_s8 = time.monotonic()
        await ensure_hud(page, s8["beat"], s8["ai_pillar"], s8["captions"][0])
        await asyncio.sleep(1.2)

        # Trigger SCN-1 on the backend and refresh cockpit state
        try:
            requests.post(
                f"{COCKPIT_URL}/api/admin/inject",
                json={"scenario_id": "SCN-1", "speed_multiplier": 3.0},
                timeout=15,
            )
        except Exception as e:
            print(f"[SCN-1] Trigger warning: {e}")

        await asyncio.sleep(2.4)

        await set_caption(page, s8["captions"][1])
        await move_cursor_and_highlight(page, "Primary Root Cause Isolated to RTU-1", by_text=True, click=False, pad=8)
        await asyncio.sleep(3.5)
        await move_cursor_and_highlight(page, "Trace Active Root Cause (1 Primary / 31 Muted)", by_text=True, click=False, pad=8)
        await wait_until_scene_end(t_s8, durations[s8["id"]])

        # ===================================================================
        # SCENE 9: Cross-Layer BACnet OT Network + Sympathetic Suppression
        # ===================================================================
        s9 = SCENES[8]
        t_s9 = time.monotonic()
        await ensure_hud(page, s9["beat"], s9["ai_pillar"], s9["captions"][0])

        await move_cursor_and_highlight(page, "3. BACnet OT Network", by_text=True, click=True)
        await asyncio.sleep(2.5)
        await move_cursor_and_highlight(page, "0.0% Packet Loss", by_text=True, click=False, pad=8)
        await asyncio.sleep(2.8)

        await set_caption(page, s9["captions"][1])
        await move_cursor_and_highlight(page, "6. Alarms & Heartbeats", by_text=True, click=True)
        await asyncio.sleep(2.8)
        await move_cursor_and_highlight(page, "1. Primary Root-Cause Equipment Failure", by_text=True, click=False, pad=8)
        await asyncio.sleep(2.5)

        await move_cursor_and_highlight(page, "Trace Active Root Cause (1 Primary / 31 Muted)", by_text=True, click=True)
        await asyncio.sleep(3.5)
        close_sim2 = page.get_by_text("Close Simulator", exact=False).first
        if await close_sim2.count() > 0:
            await close_sim2.click(force=True)
        await clear_spotlight(page)
        await wait_until_scene_end(t_s9, durations[s9["id"]])

        # ===================================================================
        # SCENE 10: Google Cloud Agent Platform Governance & OTel Traceability
        # ===================================================================
        s10 = SCENES[9]
        t_s10 = time.monotonic()
        await ensure_hud(page, s10["beat"], s10["ai_pillar"], s10["captions"][0])

        await move_cursor_and_highlight(page, "1. Floor Plan & Devices", by_text=True, click=True)
        await asyncio.sleep(1.2)
        await move_cursor_and_highlight(page, "Vertex AI Agent Runtime", by_text=True, click=False, pad=8)
        await asyncio.sleep(3.0)
        await move_cursor_and_highlight(page, "Gateway: acme-abo-agent-gateway", by_text=True, click=False, pad=8)
        await asyncio.sleep(2.8)

        await set_caption(page, s10["captions"][1])
        await move_cursor_and_highlight(page, "OTel: Cloud Trace + Monitoring", by_text=True, click=False, pad=8)
        await asyncio.sleep(3.0)
        await move_cursor_and_highlight(page, "acme-abo-client-to-agent (ALLOW)", by_text=True, click=False, pad=6)
        await wait_until_scene_end(t_s10, durations[s10["id"]])

        # ===================================================================
        # SCENE 11: Symbolic Safety Guardrails & 1-Click Closed-Loop Recovery
        # ===================================================================
        s11 = SCENES[10]
        t_s11 = time.monotonic()
        await ensure_hud(page, s11["beat"], s11["ai_pillar"], s11["captions"][0])

        await move_cursor_and_highlight(
            page, "SAFETY CHECK: PASSED (ASHRAE-36 & SHACL Verified)", by_text=True, click=False, pad=8
        )
        await asyncio.sleep(4.2)

        await set_caption(page, s11["captions"][1])
        await move_cursor_and_highlight(
            page, "Approve & Execute Closed-Loop Recovery", by_text=True, click=True, pad=10
        )
        await asyncio.sleep(2.2)

        await move_cursor_and_highlight(
            page, "CLOSED-LOOP REMEDIATION VERIFIED", by_text=True, click=False, pad=8
        )
        await asyncio.sleep(3.5)
        await clear_spotlight(page)
        await wait_until_scene_end(t_s11, durations[s11["id"]])

        # Hold final resolved frame for 1.5s
        await asyncio.sleep(1.5)
        video_obj = page.video
        await context.close()
        await browser.close()

        recorded_path = Path(await video_obj.path())
        return recorded_path, trim_start_sec


# ---------------------------------------------------------------------------
# Step 4: FFmpeg Audio Concatenation & 1080p MP4 Mastering
# ---------------------------------------------------------------------------
def master_final_video(
    recorded_webm: Path,
    trim_start_sec: float,
    audio_dir: Path,
    output_mp4: Path,
) -> None:
    concat_list_path = audio_dir / "concat_audio.txt"
    with concat_list_path.open("w") as f:
        for scene in SCENES:
            wav_file = audio_dir / f"{scene['id']}.wav"
            f.write(f"file '{wav_file.resolve()}'\n")

    full_audio_wav = audio_dir / "full_narration.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            str(full_audio_wav),
        ],
        check=True,
    )

    # Mux trimmed 1080p Playwright video + full Google Cloud TTS audio into H.264/AAC MP4
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{trim_start_sec:.2f}",
            "-i",
            str(recorded_webm),
            "-i",
            str(full_audio_wav),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_mp4),
        ],
        check=True,
    )


async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audio_dir = OUTPUT_DIR / "audio"
    raw_video_dir = OUTPUT_DIR / "raw_video"
    audio_dir.mkdir(parents=True, exist_ok=True)
    raw_video_dir.mkdir(parents=True, exist_ok=True)

    print("=== [1/3] Synthesizing Executive Narration via Google Cloud Text-to-Speech API ===")
    token = get_gcp_access_token()
    durations: Dict[str, float] = {}
    total_audio_sec = 0.0
    for scene in SCENES:
        dur = synthesize_scene_audio(scene, audio_dir, token)
        durations[scene["id"]] = dur
        total_audio_sec += dur

    print(f"Total synthesized narration duration: {total_audio_sec:.1f}s ({total_audio_sec/60:.2f} mins)")

    print("=== [2/3] Recording Live 1920x1080 UI Walkthrough against Cloud Run ===")
    recorded_webm, trim_start_sec = await run_ui_walkthrough(durations, raw_video_dir)
    print(f"Recorded raw walkthrough video: {recorded_webm} (trim_start={trim_start_sec:.2f}s)")

    print("=== [3/3] Mastering Final 1080p H.264 + AAC Presentation Video ===")
    master_final_video(recorded_webm, trim_start_sec, audio_dir, FINAL_MP4_PATH)

    size_mb = FINAL_MP4_PATH.stat().st_size / (1024 * 1024)
    print(f"SUCCESS: Generated {FINAL_MP4_PATH} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    asyncio.run(main())
