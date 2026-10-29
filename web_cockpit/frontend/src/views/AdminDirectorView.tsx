import React from "react";
import { useCockpitStore } from "../store/useCockpitStore";

export default function AdminDirectorView() {
  const {
    activeScenario,
    injectedEvents,
    triggerScenario,
    resetDemo,
    lastResetTs,
    lastResetLatencyMs,
  } = useCockpitStore();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-8 max-w-5xl mx-auto space-y-6">
      <header className="border-b border-slate-800 pb-4 flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-widest text-amber-400 font-bold">
            Companion Chrome Tab • Backstage Presenter Console (/admin)
          </div>
          <h1 className="text-2xl font-bold text-white mt-1">
            ACME Co. — Live Demo Director & Fault Injector
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Trigger dynamic multi-wave fault scenarios in real time on the Main Operations Cockpit (
            <code className="text-cyan-400">/</code>) or reset to clean baseline in &lt;1 second.
          </p>
        </div>
        <button
          onClick={() => resetDemo()}
          className="px-5 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-sm shadow-lg"
        >
          ↺ Reset Demo to Clean Baseline (&lt;1s)
        </button>
      </header>

      {/* Live Telemetry & Reset Status */}
      <div className="grid grid-cols-3 gap-4">
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs text-slate-400">Active Scenario Overlay</div>
          <div className="text-lg font-bold text-cyan-400 mt-1">
            {activeScenario || "NONE (T=0 Clean Baseline)"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs text-slate-400">Live Injected Alarms</div>
          <div className="text-lg font-bold text-rose-400 mt-1">{injectedEvents.length}</div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs text-slate-400">Last Reset Latency</div>
          <div className="text-lg font-bold text-emerald-400 mt-1">
            {lastResetLatencyMs !== null ? `${lastResetLatencyMs} ms` : "Ready"}
          </div>
          {lastResetTs && <div className="text-[11px] text-slate-500">{lastResetTs}</div>}
        </div>
      </div>

      {/* Primary Demo Scenario Trigger Cards: Option A & Option B */}
      <div className="grid grid-cols-2 gap-6">
        {/* Option A — SCN-1 */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-rose-500/40 flex flex-col justify-between space-y-4">
          <div className="space-y-2">
            <span className="px-2.5 py-1 text-xs font-bold rounded bg-rose-950 text-rose-300 border border-rose-700">
              OPTION A • SCENARIO SCN-1
            </span>
            <h2 className="text-xl font-bold text-white">
              Cascading Rooftop Unit Failure (bldg:rtu_1)
            </h2>
            <p className="text-xs text-slate-300 leading-relaxed">
              Injects a jammed outdoor-air economizer damper on <code>bldg:rtu_1</code> during an
              88°F afternoon, followed 3 seconds later by 8 sympathetic high-discharge and warm-space
              alarms across downstream VAV boxes (<code>VAV-1-101</code> to <code>VAV-1-108</code>).
              Demonstrates GQL topological storm deduplication (9 alarms → 1 root cause) and
              SHACL-gated BACnet Priority 8 mitigation.
            </p>
          </div>
          <button
            onClick={() => triggerScenario("SCN-1", 1.0)}
            className="w-full py-3 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-sm"
          >
            ▶ Trigger Option A — Cascading RTU-1 Failure
          </button>
        </div>

        {/* Option B — SCN-4 */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-amber-500/40 flex flex-col justify-between space-y-4">
          <div className="space-y-2">
            <span className="px-2.5 py-1 text-xs font-bold rounded bg-amber-950 text-amber-300 border border-amber-700">
              OPTION B • SCENARIO SCN-4
            </span>
            <h2 className="text-xl font-bold text-white">
              Critical Server Room Predictive Alert (bldg:zone_server_room)
            </h2>
            <p className="text-xs text-slate-300 leading-relaxed">
              Injects an abnormal compressor current surge (<code>29.4 A</code>) on dedicated unit{" "}
              <code>bldg:cooling_only_rtu_2</code> while Server Room temperature is still{" "}
              <code>73.6°F</code> (below the <code>78.0°F</code> hard BAS alarm threshold).
              Demonstrates <code>AI.FORECAST</code> thermal breach prediction 22 minutes in advance
              and proactive staging of backup cooling.
            </p>
          </div>
          <button
            onClick={() => triggerScenario("SCN-4", 1.0)}
            className="w-full py-3 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-bold text-sm"
          >
            ▶ Trigger Option B — Critical Server Room Predictive Alert
          </button>
        </div>
      </div>
    </div>
  );
}

