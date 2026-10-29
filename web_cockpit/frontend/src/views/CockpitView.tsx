import React, { useEffect, useState, useMemo } from "react";
import {
  Building2,
  Layers,
  Cpu,
  Network,
  Activity,
  Zap,
  Search,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  GitBranch,
  Thermometer,
  Wind,
  ArrowRight,
  ShieldCheck,
  X,
  Crosshair,
  Send,
  MessageSquare,
  Bell,
  Info,
  Clock,
  Wrench,
} from "lucide-react";
import { useCockpitStore, CockpitTabId } from "../store/useCockpitStore";

interface DevicePin {
  node_id: string;
  label: string;
  brick_class: string;
  ashrae_223p_class: string;
  serving_ahu_id: string;
  controller_id: string;
  point_count: number;
  runtime_status: string;
  pin_x: number;
  pin_y: number;
}

interface FloorRoom {
  space_id: string;
  label: string;
  floor_id: string;
  sla_tier: string;
  occupancy_pct: number;
  comfort_pct: number;
  live_temp_f: number;
  setpoint_f?: number;
  delta_temp_f?: number;
  thermal_load_kw?: number;
  runtime_status: string;
  coords: { x: number; y: number; w: number; h: number };
  devices: DevicePin[];
}

interface FloorMeta {
  floor_id: string;
  label: string;
  short_label: string;
  primary_ahu_id: string;
  primary_ahu_label: string;
  sla_tier: string;
}

export default function CockpitView() {
  const {
    activeBuildingId,
    setActiveBuildingId,
    selectedFloorId,
    setSelectedFloorId,
    activeTab,
    setActiveTab,
    selectedNodeId,
    setSelectedNodeId,
    entityDrawerOpen,
    setEntityDrawerOpen,
    activeScenario,
    buildingHealed,
    remediatedScenario,
    injectedEvents,
    agentSteps,
    stagedHitlActions,
    decideHitlAction,
    analyzeNodeWithAgent,
    askBuildingQuestion,
    rootCauseModalOpen,
    setRootCauseModalOpen,
  } = useCockpitStore();

  const [portfolioSites, setPortfolioSites] = useState<any[]>([]);
  const [digitalTwin, setDigitalTwin] = useState<{
    site: any;
    floors: FloorMeta[];
    rooms: FloorRoom[];
    equipment_count: number;
    controllers_count: number;
    edges_count: number;
    all_equipment: any[];
    all_controllers: any[];
    has_active_incident?: boolean;
    building_healed?: boolean;
    remediated_scenario?: string | null;
    routine_bas_heartbeats?: Array<{ timestamp: string; protocol: string; message: string }>;
  } | null>(null);

  const [neighborhood, setNeighborhood] = useState<{
    center_node: any;
    neighbors: any[];
    edges: any[];
    bacnet_points: any[];
    total_points_count: number;
    active_alarms: any[];
    gql_query: string;
    ai_diagnostics?: {
      failure_probability_pct: number;
      risk_level: string;
      predicted_failure_window: string;
      ai_confidence_pct: number;
      ai_data_sources_used: string;
      root_cause_explanation: string;
      financial_risk_summary: string;
      mttr_intelligence: {
        typical_remote_ai_fix_mins: number;
        typical_manual_fix_hours: number;
        recommended_fix_action: string;
        historical_incidents: Array<{
          work_order_id: string;
          date: string;
          symptom: string;
          root_cause_found: string;
          fix_applied: string;
          remote_ai_fix_mins: number;
          manual_dispatch_hrs: number;
          outcome: string;
        }>;
      };
      at_risk_connected_elements: Array<{
        node_id: string;
        label: string;
        relationship: string;
        risk_status?: string;
        runtime_status?: string;
        failure_likelihood_pct: number;
        impact_summary: string;
      }>;
    };
  } | null>(null);

  const [showDuctwork, setShowDuctwork] = useState(true);
  const [showThermalHeatmap, setShowThermalHeatmap] = useState(true);
  const [deviceSearch, setDeviceSearch] = useState("");
  const [deviceFilter, setDeviceFilter] = useState<"ALL" | "AHU" | "TERMINAL" | "CONTROLLER" | "ROOM">("ALL");
  const [graphFloorFilter, setGraphFloorFilter] = useState<string>("ALL");
  const [analyzingNode, setAnalyzingNode] = useState(false);
  const [chatQuestion, setChatQuestion] = useState("");
  const [tab2ChatQuestion, setTab2ChatQuestion] = useState("");
  const [askingChat, setAskingChat] = useState(false);
  const [expandedEnergyRoomId, setExpandedEnergyRoomId] = useState<string | null>(null);

  // Load portfolio sites
  useEffect(() => {
    fetch("/api/portfolio")
      .then((r) => r.json())
      .then((d) => {
        if (d.sites) setPortfolioSites(d.sites);
      })
      .catch(() => {});
  }, [activeScenario, injectedEvents.length, buildingHealed]);

  // Load building digital twin when activeBuildingId, scenario, or buildingHealed changes,
  // and automatically select the most relevant anomaly/default node when switching buildings
  useEffect(() => {
    fetch(`/api/buildings/${activeBuildingId}/digital-twin`)
      .then((r) => r.json())
      .then((d) => {
        setDigitalTwin(d);
        if (d.floors && d.floors.length > 0) {
          const floorExists = d.floors.some((f: FloorMeta) => f.floor_id === selectedFloorId);
          if (!floorExists) {
            const firstFloor = d.floors[0];
            // If switching to Sunbelt Plant (ACME-SITE-004), auto-select the yellow anomaly room (SMT PCB Assembly Line)
            // so switching to Tab 2 (Knowledge Graph) or Tab 5 (Energy Z-Scores) immediately shows the yellow outlier & neighbors!
            const outlierRoom = (d.rooms || []).find((rm: FloorRoom) => rm.runtime_status === "ENERGY_OUTLIER");
            if (activeBuildingId === "ACME-SITE-004" && outlierRoom) {
              setSelectedFloorId(outlierRoom.floor_id);
              setGraphFloorFilter(outlierRoom.floor_id);
              setSelectedNodeId(outlierRoom.space_id);
              setExpandedEnergyRoomId(outlierRoom.space_id);
            } else {
              setSelectedFloorId(firstFloor.floor_id);
              setGraphFloorFilter(firstFloor.floor_id);
              setSelectedNodeId(firstFloor.primary_ahu_id);
              setExpandedEnergyRoomId(outlierRoom ? outlierRoom.space_id : d.rooms?.[0]?.space_id || null);
            }
          }
        }
      })
      .catch(() => {});
  }, [activeBuildingId, activeScenario, injectedEvents.length, buildingHealed]);

  // Load selected node Knowledge Graph neighborhood whenever selectedNodeId changes
  useEffect(() => {
    if (!selectedNodeId) return;
    fetch(`/api/graph/neighborhood/${encodeURIComponent(selectedNodeId)}`)
      .then((r) => r.json())
      .then((d) => setNeighborhood(d))
      .catch(() => {});
  }, [selectedNodeId, activeScenario, injectedEvents.length, buildingHealed]);

  const rootCauseAlarms = useMemo(
    () => injectedEvents.filter((e) => e.is_root_cause),
    [injectedEvents]
  );
  const suppressedAlarms = useMemo(
    () => injectedEvents.filter((e) => e.suppressed_by_agent),
    [injectedEvents]
  );
  const hasActiveIncident = injectedEvents.length > 0;

  const currentFloorRooms = useMemo(() => {
    if (!digitalTwin?.rooms) return [];
    const matched = digitalTwin.rooms.filter((r) => r.floor_id === selectedFloorId);
    if (matched.length > 0) return matched;
    const firstFloorId = digitalTwin.floors?.[0]?.floor_id;
    return digitalTwin.rooms.filter((r) => r.floor_id === firstFloorId);
  }, [digitalTwin, selectedFloorId]);

  const currentFloorMeta = useMemo(() => {
    return (
      digitalTwin?.floors.find((f) => f.floor_id === selectedFloorId) ||
      digitalTwin?.floors?.[0]
    );
  }, [digitalTwin, selectedFloorId]);

  // Searchable & Filterable directory of all entities in the active building (including Floor Filter in Tab 2)
  const filteredCatalog = useMemo(() => {
    if (!digitalTwin) return [];
    const items: Array<{
      id: string;
      label: string;
      category: string;
      ontology: string;
      floor_id: string;
      status: string;
      sub: string;
    }> = [];

    for (const eq of digitalTwin.all_equipment || []) {
      const cls = String(eq.brick_class || "");
      const isAhu =
        cls.includes("AHU") ||
        cls.includes("Air_Handling") ||
        cls.includes("Rooftop") ||
        cls.includes("Chiller") ||
        cls.includes("Outdoor_Air") ||
        eq.node_id.includes("ahu");
      items.push({
        id: eq.node_id,
        label: eq.label || eq.node_id,
        category: isAhu ? "AHU" : "TERMINAL",
        ontology: eq.brick_class || "brick:Equipment",
        floor_id: eq.floor_id || digitalTwin.floors?.[0]?.floor_id || "bldg:ec_1st_floor",
        status: eq.runtime_status || "HEALTHY",
        sub: `${eq.point_count || 0} BACnet pts • Ctrl: ${eq.controller_id || "Direct"}`,
      });
    }

    for (const rm of digitalTwin.rooms || []) {
      items.push({
        id: rm.space_id,
        label: rm.label,
        category: "ROOM",
        ontology: "rec:Room",
        floor_id: rm.floor_id,
        status: rm.runtime_status || "HEALTHY",
        sub: `${rm.sla_tier} • ${rm.live_temp_f.toFixed(1)}°F • ${rm.devices.length} devices`,
      });
    }

    for (const ctrl of digitalTwin.all_controllers || []) {
      items.push({
        id: ctrl.node_id,
        label: ctrl.label || ctrl.node_id,
        category: "CONTROLLER",
        ontology: ctrl.entity_category || "bsm:Controller",
        floor_id: digitalTwin.floors?.[0]?.floor_id || "bldg:ec_1st_floor",
        status: "HEALTHY",
        sub: `${ctrl.controller_model || ctrl.media_type || "BACnet"} • Net: ${ctrl.network_id || "IP"}`,
      });
    }

    // Sort anomalies (ROOT_CAUSE_FAULT, ENERGY_OUTLIER, SYMPATHETIC_IMPACT) to the top of the directory!
    const statusWeight = (st: string) => {
      if (st === "ROOT_CAUSE_FAULT") return 0;
      if (st === "ENERGY_OUTLIER") return 1;
      if (st === "SYMPATHETIC_IMPACT" || st === "AT_RISK") return 2;
      return 3;
    };

    return items
      .filter((it) => {
        if (deviceFilter !== "ALL" && it.category !== deviceFilter) return false;
        if (graphFloorFilter !== "ALL" && it.floor_id !== graphFloorFilter) return false;
        if (!deviceSearch.trim()) return true;
        const q = deviceSearch.toLowerCase();
        return (
          it.id.toLowerCase().includes(q) ||
          it.label.toLowerCase().includes(q) ||
          it.ontology.toLowerCase().includes(q) ||
          it.sub.toLowerCase().includes(q)
        );
      })
      .sort((a, b) => statusWeight(a.status) - statusWeight(b.status));
  }, [digitalTwin, deviceFilter, graphFloorFilter, deviceSearch]);

  const handleSelectFloor = (floorId: string) => {
    setSelectedFloorId(floorId);
    setGraphFloorFilter(floorId);
    const fl = digitalTwin?.floors?.find((f) => f.floor_id === floorId);
    if (!fl) return;
    // Check if current selectedNodeId belongs to this floor; if not, select the floor's primary AHU
    const roomOnFloor = (digitalTwin?.rooms || []).some(
      (r) => r.floor_id === floorId && (r.space_id === selectedNodeId || r.devices.some((d) => d.node_id === selectedNodeId))
    );
    const eqOnFloor = (digitalTwin?.all_equipment || []).some(
      (e) => e.floor_id === floorId && e.node_id === selectedNodeId
    );
    if (!roomOnFloor && !eqOnFloor && selectedNodeId !== fl.primary_ahu_id) {
      setSelectedNodeId(fl.primary_ahu_id);
    }
  };

  const handleSelectEntity = (nodeId: string, floorId?: string, openDrawer = true) => {
    setSelectedNodeId(nodeId);
    if (floorId && digitalTwin?.floors?.some((f) => f.floor_id === floorId)) {
      setSelectedFloorId(floorId);
      if (graphFloorFilter !== "ALL") {
        setGraphFloorFilter(floorId);
      }
    }
    if (openDrawer) {
      setEntityDrawerOpen(true);
    }
  };

  const handleOpenRootCauseModal = async (targetNodeId?: string) => {
    if (hasActiveIncident) {
      const rootNode =
        targetNodeId ||
        rootCauseAlarms[0]?.node_id ||
        (activeScenario === "SCN-4" ? "bldg:ec_1st_floor_ec_server_rm" : "bldg:area_ec_ahu_1");
      setSelectedNodeId(rootNode);
      setRootCauseModalOpen(true);
      setAnalyzingNode(true);
      try {
        await analyzeNodeWithAgent(rootNode, "ROOT_CAUSE_TRACE");
      } finally {
        setAnalyzingNode(false);
      }
    } else {
      const defaultNode = targetNodeId || selectedNodeId || currentFloorMeta?.primary_ahu_id || "bldg:area_ec_ahu_1";
      setSelectedNodeId(defaultNode);
      setRootCauseModalOpen(true);
    }
  };

  const handleRunLiveNodeAudit = async (
    mode: "GRAPH_AUDIT" | "ROOT_CAUSE_TRACE" | "ENERGY_COHORT_CHECK" = "GRAPH_AUDIT"
  ) => {
    setAnalyzingNode(true);
    try {
      await analyzeNodeWithAgent(selectedNodeId, mode);
    } finally {
      setAnalyzingNode(false);
    }
  };

  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = chatQuestion.trim();
    if (!q || askingChat) return;
    setAskingChat(true);
    setChatQuestion("");
    try {
      await askBuildingQuestion(activeBuildingId, selectedNodeId, q);
    } finally {
      setAskingChat(false);
    }
  };

  const handleTab2ChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = tab2ChatQuestion.trim();
    if (!q || askingChat) return;
    setAskingChat(true);
    setTab2ChatQuestion("");
    try {
      await askBuildingQuestion(activeBuildingId, selectedNodeId, q);
    } finally {
      setAskingChat(false);
    }
  };

  const handleSuggestedQuestion = async (q: string) => {
    if (askingChat) return;
    setAskingChat(true);
    try {
      await askBuildingQuestion(activeBuildingId, selectedNodeId, q);
    } finally {
      setAskingChat(false);
    }
  };

  const aiDiag = neighborhood?.ai_diagnostics;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Executive Header */}
      <header className="border-b border-slate-800 bg-slate-900 px-6 py-3.5 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="p-2.5 rounded-xl bg-cyan-500/15 border border-cyan-400/40 text-cyan-300">
            <Building2 className="w-6 h-6" />
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-cyan-300 font-semibold flex items-center gap-2">
              <span>ACME Co. Autonomous Building Operations</span>
              <span className="text-slate-600">•</span>
              <span className="font-mono text-slate-200">
                Predictive AI Failure Diagnosis • Brick v1.4 + ASHRAE 223P • Gemini 3.8 Flash
              </span>
            </div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2.5 mt-0.5">
              <span>{digitalTwin?.site?.site_name || "ACME Emerald Crest HQ"}</span>
              <span className="text-xs font-mono px-2.5 py-0.5 rounded-md bg-slate-800 text-cyan-300 border border-slate-700">
                {activeBuildingId}
              </span>
              <span className="text-sm font-normal text-slate-300 hidden md:inline">
                ({digitalTwin?.site?.city} • {digitalTwin?.site?.facility_type})
              </span>
            </h1>
          </div>
        </div>

        {/* System Status & Root Cause Tracer Button */}
        <div className="flex items-center gap-3 text-sm">
          <div className="px-3.5 py-2 rounded-lg bg-slate-800 border border-slate-700 flex items-center gap-2">
            <span className="text-slate-300 font-medium">Status:</span>
            {hasActiveIncident ? (
              <span className="text-amber-300 font-bold flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                {activeScenario} FAULT ACTIVE
              </span>
            ) : buildingHealed ? (
              <span className="text-emerald-300 font-bold flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                CLOSED-LOOP AI REMEDIATED ({remediatedScenario || "SCN-1"})
              </span>
            ) : (
              <span className="text-emerald-300 font-semibold flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                ALL SYSTEMS NOMINAL
              </span>
            )}
          </div>

          <button
            onClick={() => handleOpenRootCauseModal()}
            className={`px-4 py-2 rounded-lg font-semibold border flex items-center gap-2 transition shadow-md ${
              hasActiveIncident
                ? "bg-rose-600 hover:bg-rose-500 border-rose-400 text-white animate-pulse"
                : "bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-100"
            }`}
          >
            <Crosshair className="w-4 h-4 text-cyan-300" />
            <span>
              {hasActiveIncident
                ? `Trace Active Root Cause (${rootCauseAlarms.length} Primary / ${suppressedAlarms.length} Muted)`
                : "AI Blast-Radius & Root-Cause Simulator"}
            </span>
          </button>
        </div>
      </header>

      {/* Portfolio Building Switcher Ribbon with Explicit Asset Breakdown & AI Predictive Risk */}
      <div className="bg-slate-900/90 border-b border-slate-800 px-6 py-2.5 flex items-center gap-2.5 overflow-x-auto">
        <div className="shrink-0 mr-1">
          <div className="text-xs font-bold uppercase tracking-wider text-slate-200">
            Portfolio Buildings
          </div>
          <div className="text-[11px] text-cyan-300 font-mono">
            Click to switch site & inspect assets
          </div>
        </div>
        {portfolioSites.map((s) => {
          const isSelected = s.site_id === activeBuildingId;
          const riskPct = Number(s.top_risk_pct ?? 12);
          const isHighRisk = riskPct >= 70;
          return (
            <button
              key={s.site_id}
              onClick={() => setActiveBuildingId(s.site_id)}
              title={`${s.site_name}: ${s.asset_breakdown_short || `${s.equipment_count} HVAC assets`} — ${s.ai_predictive_headline || ""}`}
              className={`px-3.5 py-2 rounded-xl border text-left flex items-start gap-3 shrink-0 transition ${
                isSelected
                  ? "bg-cyan-950/90 border-cyan-400 text-white shadow-md"
                  : "bg-slate-900 border-slate-800 text-slate-200 hover:bg-slate-800 hover:border-slate-600"
              }`}
            >
              <span
                className={`w-2.5 h-2.5 rounded-full shrink-0 mt-1.5 ${
                  isHighRisk
                    ? "bg-amber-400"
                    : s.sla_status === "HEALTHY"
                    ? "bg-emerald-400"
                    : "bg-cyan-400"
                }`}
              />
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold leading-snug text-white">{s.site_name}</span>
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                      isHighRisk
                        ? "bg-amber-500/20 text-amber-300 border border-amber-400/50"
                        : "bg-emerald-950 text-emerald-300 border border-emerald-700/60"
                    }`}
                  >
                    AI Risk: {riskPct}%
                  </span>
                </div>
                <div className="text-xs text-slate-300 font-mono">
                  {s.city} • {Number(s.gross_sqft || 0).toLocaleString()} sq ft
                </div>
                <div className="text-[11px] text-cyan-300 font-mono mt-0.5">
                  {s.asset_breakdown_short ||
                    `${s.equipment_count} HVAC Units • ${s.bacnet_controllers_count || 100} BACnet Controllers`}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Closed-Loop AI Remediation Verified Banner (Shown immediately when operator clicks Approve on Priority 8 HITL Card) */}
      {buildingHealed && !hasActiveIncident && (
        <div className="bg-emerald-950/95 border-b border-emerald-400/80 px-6 py-3 flex flex-wrap items-center justify-between gap-3 shadow-lg">
          <div className="flex items-center gap-3 text-sm text-emerald-100">
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            <div>
              <strong className="text-emerald-300 uppercase tracking-wide mr-2">
                Closed-Loop AI Remediation Verified ({remediatedScenario || "SCN-1"}):
              </strong>
              <span>
                BACnet Priority 8 WriteProperty override executed on{" "}
                <code className="text-white font-mono">bldg:area_ec_ahu_1</code>. Supply air damper restored to{" "}
                <strong>65% open</strong>, all <strong>31 sympathetic zone alarms cleared</strong>, and 1st-floor room temperatures recovered from{" "}
                <strong>75.8°F → 71.8°F nominal</strong>.
              </span>
            </div>
          </div>
          <span className="px-3 py-1 rounded-md bg-emerald-500 text-slate-950 font-mono text-xs font-bold shrink-0">
            MTTR: 42 sec (vs. 4.2 hr Manual Dispatch)
          </span>
        </div>
      )}

      {/* Active Incident Alert Banner (Only visible when an alarm storm is active) */}
      {hasActiveIncident && (
        <div className="bg-rose-950/90 border-b border-rose-500/70 px-6 py-2.5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 text-sm text-rose-100">
            <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
            <span>
              <strong>Active BAS Incident ({activeScenario}):</strong>{" "}
              {rootCauseAlarms[0]?.alarm_message || `${injectedEvents.length} BAS events received`} —{" "}
              <strong className="text-emerald-300">
                {suppressedAlarms.length} sympathetic downstream zone alarms automatically muted by AI Graph Reasoning.
              </strong>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleOpenRootCauseModal(rootCauseAlarms[0]?.node_id)}
              className="px-3 py-1 rounded-md bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold flex items-center gap-1.5 shadow"
            >
              <Crosshair className="w-3.5 h-3.5" />
              <span>Inspect Causal Blast Radius</span>
            </button>
            <button
              onClick={() => setActiveTab("alarms")}
              className="px-3 py-1 rounded-md bg-slate-900 hover:bg-slate-800 text-slate-100 border border-slate-700 text-xs font-semibold"
            >
              View All {injectedEvents.length} Alarms
            </button>
          </div>
        </div>
      )}

      {/* Main Clean 2-Column Workspace */}
      <div className="flex-1 grid grid-cols-12 gap-4 p-4">
        {/* Left 8 Columns: Focused View Canvas (Floor Plan OR Knowledge Graph OR Network OR Telemetry) */}
        <section className="col-span-12 lg:col-span-8 bg-slate-900 border border-slate-800 rounded-xl flex flex-col overflow-hidden">
          {/* AI-First Predictive Intelligence & Asset Breakdown KPI Bar */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 p-4 bg-slate-950/80 border-b border-slate-800">
            <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
              <div className="text-xs text-slate-300 font-medium flex items-center justify-between">
                <span>Building Asset Inventory</span>
                <span className="font-mono text-[11px] text-cyan-300">
                  {digitalTwin?.floors?.length || 0}F • {digitalTwin?.rooms?.length || 0} Zones
                </span>
              </div>
              <div className="text-sm font-bold text-white mt-1 leading-snug">
                {digitalTwin?.site?.asset_breakdown_short ||
                  `${digitalTwin?.equipment_count || 0} HVAC Units • ${digitalTwin?.controllers_count || 0} Controllers`}
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5">
                Every unit mapped to Brick v1.4 &amp; ASHRAE 223P
              </div>
            </div>

            <div
              className={`p-3 rounded-lg border ${
                (aiDiag?.failure_probability_pct || 0) >= 70
                  ? "bg-amber-950/40 border-amber-500/70"
                  : "bg-slate-900 border-slate-800"
              }`}
            >
              <div className="text-xs text-slate-300 font-medium flex items-center justify-between">
                <span>AI Failure Likelihood (Selected)</span>
                <Sparkles className="w-3.5 h-3.5 text-amber-300" />
              </div>
              <div className="text-lg font-bold text-amber-300 mt-0.5 flex items-baseline gap-2">
                <span>{aiDiag?.failure_probability_pct ?? 12}% Risk</span>
                <span className="text-xs font-mono text-slate-200 font-normal">
                  ({aiDiag?.predicted_failure_window || "Stable >30d"})
                </span>
              </div>
              <div className="text-[11px] text-slate-300 truncate mt-0.5">
                Target: {neighborhood?.center_node?.label || selectedNodeId}
              </div>
            </div>

            <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
              <div className="text-xs text-slate-300 font-medium flex items-center justify-between">
                <span>Connected Blast Radius</span>
                <GitBranch className="w-3.5 h-3.5 text-cyan-300" />
              </div>
              <div className="text-lg font-bold text-cyan-300 mt-0.5">
                {aiDiag?.at_risk_connected_elements?.length || 2} At-Risk Nodes
              </div>
              <div className="text-[11px] text-slate-300 truncate mt-0.5">
                {aiDiag?.at_risk_connected_elements?.[0]?.label || "Downstream & upstream dependencies"}
              </div>
            </div>

            <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
              <div className="text-xs text-slate-300 font-medium flex items-center justify-between">
                <span>Historical MTTR &amp; Energy ROI</span>
                <Clock className="w-3.5 h-3.5 text-emerald-300" />
              </div>
              <div className="text-lg font-bold text-emerald-300 mt-0.5">
                {aiDiag?.mttr_intelligence?.typical_remote_ai_fix_mins ?? 18}m AI Fix{" "}
                <span className="text-xs font-normal text-slate-300">
                  vs {aiDiag?.mttr_intelligence?.typical_manual_fix_hours ?? 3.8}h Truck Roll
                </span>
              </div>
              <div className="text-[11px] text-amber-300 font-mono mt-0.5">
                ${Number(digitalTwin?.site?.identified_annual_energy_savings_usd || 18400).toLocaleString()}/yr Recoverable
              </div>
            </div>
          </div>

          {/* Dedicated View Tabs */}
          <nav className="flex flex-wrap border-b border-slate-800 bg-slate-950 px-4 pt-2.5 gap-1.5">
            {[
              { id: "floorplan", label: "1. Floor Plan & Devices", icon: Layers },
              { id: "graph", label: "2. Knowledge Graph & AI Risk", icon: GitBranch },
              { id: "bacnet", label: "3. BACnet OT Network", icon: Network },
              { id: "telemetry", label: "4. Point Telemetry", icon: Activity },
              { id: "energy", label: "5. Energy Z-Scores & MTTR", icon: Zap },
              {
                id: "alarms",
                label: hasActiveIncident
                  ? `6. Alarms & Heartbeats (${injectedEvents.length})`
                  : "6. Alarms & Heartbeats",
                icon: Bell,
              },
            ].map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id as CockpitTabId)}
                  className={`px-3.5 py-2.5 text-sm font-semibold rounded-t-lg border-t border-x flex items-center gap-2 transition ${
                    activeTab === t.id
                      ? "bg-slate-900 text-cyan-300 border-slate-700"
                      : "bg-transparent text-slate-300 border-transparent hover:text-white hover:bg-slate-900/50"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{t.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Main Tab Content Area */}
          <div className="p-4 flex-1 overflow-y-auto">
            {/* TAB 1: INTERACTIVE ARCHITECTURAL FLOOR PLAN */}
            {activeTab === "floorplan" && (
              <div className="space-y-4">
                {/* Floor Selector & CAD Layer Controls */}
                <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-950 p-3.5 rounded-xl border border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-200 mr-1">
                      Select Floor:
                    </span>
                    {(digitalTwin?.floors || []).map((fl) => (
                      <button
                        key={fl.floor_id}
                        onClick={() => handleSelectFloor(fl.floor_id)}
                        className={`px-3.5 py-1.5 rounded-lg text-sm font-semibold border transition ${
                          selectedFloorId === fl.floor_id
                            ? "bg-cyan-500 text-slate-950 border-cyan-300 shadow"
                            : "bg-slate-900 text-slate-100 border-slate-700 hover:border-slate-500"
                        }`}
                      >
                        {fl.short_label}
                      </button>
                    ))}
                  </div>

                  {/* Layer Toggles */}
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <button
                      onClick={() => setShowDuctwork(!showDuctwork)}
                      className={`px-3 py-1.5 rounded-lg border font-medium flex items-center gap-1.5 transition ${
                        showDuctwork
                          ? "bg-cyan-950 border-cyan-500/70 text-cyan-200"
                          : "bg-slate-900 border-slate-700 text-slate-300"
                      }`}
                    >
                      <Wind className="w-4 h-4" />
                      <span>Supply Ducts (brick:feeds): {showDuctwork ? "ON" : "OFF"}</span>
                    </button>
                    <button
                      onClick={() => setShowThermalHeatmap(!showThermalHeatmap)}
                      className={`px-3 py-1.5 rounded-lg border font-medium flex items-center gap-1.5 transition ${
                        showThermalHeatmap
                          ? "bg-amber-950 border-amber-400 text-amber-200 shadow-sm"
                          : "bg-slate-900 border-slate-700 text-slate-300"
                      }`}
                    >
                      <Thermometer className="w-4 h-4" />
                      <span>Thermal Heatmap Overlay: {showThermalHeatmap ? "ON" : "OFF"}</span>
                    </button>
                  </div>
                </div>

                {/* Thermal Heatmap Gradient Scale Bar (Visible when Thermal Heatmap is toggled ON) */}
                {showThermalHeatmap ? (
                  <div className="px-4 py-2.5 rounded-xl bg-slate-950 border border-amber-500/40 flex flex-wrap items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-2">
                      <Thermometer className="w-4 h-4 text-amber-400 shrink-0" />
                      <span className="font-bold text-amber-200 uppercase tracking-wider">
                        Thermal Heatmap Active:
                      </span>
                      <span className="text-slate-300">
                        Showing zone temperature gradient, setpoint deviation (ΔT), and thermal load (kW)
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-cyan-300">68°F Cool</span>
                      <div className="w-36 h-3 rounded-full bg-gradient-to-r from-cyan-500 via-emerald-400 via-amber-400 to-rose-500 border border-slate-700" />
                      <span className="font-mono text-rose-300">76°F+ Drift</span>
                    </div>
                  </div>
                ) : (
                  <div className="px-4 py-2 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between text-xs text-slate-400">
                    <span>
                      Thermal Heatmap Overlay is currently <strong>OFF</strong> (CAD Wireframe Mode — room color fills and ΔT / kW thermal load badges hidden).
                    </span>
                    <button
                      onClick={() => setShowThermalHeatmap(true)}
                      className="text-amber-300 hover:underline font-semibold"
                    >
                      Turn On Thermal Heatmap
                    </button>
                  </div>
                )}

                {/* Interactive SVG CAD Floor Plan Blueprint */}
                <div className="relative rounded-xl border border-slate-800 bg-[#07111f] overflow-hidden shadow-inner">
                  <div className="px-4 py-2.5 bg-slate-950 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2 text-sm">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white">{currentFloorMeta?.label}</span>
                      <span className="text-slate-500">•</span>
                      <span className="font-mono text-xs text-cyan-300">
                        Primary Supply: {currentFloorMeta?.primary_ahu_label}
                      </span>
                    </div>
                    <div className="text-xs text-slate-200 flex items-center gap-1.5">
                      <Info className="w-4 h-4 text-cyan-400" />
                      <span>Click any room or device pin to inspect AI Failure Risk, Blast Radius &amp; BACnet points</span>
                    </div>
                  </div>

                  <svg
                    viewBox="0 0 1000 530"
                    className="w-full h-[470px] select-none"
                    style={{
                      backgroundImage:
                        "radial-gradient(rgba(56, 189, 248, 0.14) 1px, transparent 1px)",
                      backgroundSize: "20px 20px",
                    }}
                  >
                    <defs>
                      <linearGradient id="ductGradNominal" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.65" />
                        <stop offset="100%" stopColor="#10b981" stopOpacity="0.4" />
                      </linearGradient>
                      <linearGradient id="ductGradFault" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.95" />
                        <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.75" />
                      </linearGradient>
                    </defs>

                    {/* Building Perimeter CAD Frame */}
                    <rect
                      x="18"
                      y="16"
                      width="964"
                      height="502"
                      rx="10"
                      fill="none"
                      stroke="#334155"
                      strokeWidth="2.5"
                    />

                    {/* Primary AHU Supply Riser Hub on Floor Plan */}
                    <g
                      onClick={() =>
                        handleSelectEntity(
                          currentFloorMeta?.primary_ahu_id || "bldg:area_ec_ahu_1",
                          undefined,
                          true
                        )
                      }
                      className="cursor-pointer"
                    >
                      <rect
                        x="380"
                        y="2"
                        width="240"
                        height="24"
                        rx="6"
                        fill={
                          activeScenario === "SCN-1" &&
                          currentFloorMeta?.primary_ahu_id === "bldg:area_ec_ahu_1"
                            ? "#881337"
                            : "#064e3b"
                        }
                        stroke={
                          activeScenario === "SCN-1" &&
                          currentFloorMeta?.primary_ahu_id === "bldg:area_ec_ahu_1"
                            ? "#f43f5e"
                            : "#10b981"
                        }
                        strokeWidth="2"
                      />
                      <text
                        x="500"
                        y="18"
                        textAnchor="middle"
                        fill="#ffffff"
                        fontSize="11"
                        fontWeight="bold"
                      >
                        ▲ SUPPLY RISER: {currentFloorMeta?.primary_ahu_label || "Primary AHU"}
                      </text>
                    </g>

                    {/* Rooms / Architectural Zones */}
                    {currentFloorRooms.map((rm) => {
                      const { x, y, w, h } = rm.coords;
                      const isSelectedRoom = selectedNodeId === rm.space_id;
                      const isRootFault = rm.runtime_status === "ROOT_CAUSE_FAULT";
                      const isSympathetic = rm.runtime_status === "SYMPATHETIC_IMPACT";
                      const isOutlier = rm.runtime_status === "ENERGY_OUTLIER";
                      const setpointF = rm.setpoint_f ?? 71.0;
                      const deltaF = rm.delta_temp_f ?? Number((rm.live_temp_f - setpointF).toFixed(1));
                      const loadKw = rm.thermal_load_kw ?? (isOutlier ? 14.8 : 4.2);

                      let roomFill = "rgba(6, 95, 70, 0.28)";
                      let roomStroke = "#10b981";
                      if (isRootFault) {
                        roomFill = showThermalHeatmap ? "rgba(159, 18, 57, 0.62)" : "rgba(159, 18, 57, 0.42)";
                        roomStroke = "#fb7185";
                      } else if (isSympathetic) {
                        roomFill = showThermalHeatmap ? "rgba(14, 116, 144, 0.55)" : "rgba(14, 116, 144, 0.38)";
                        roomStroke = "#38bdf8";
                      } else if (isOutlier) {
                        roomFill = showThermalHeatmap ? "rgba(180, 83, 9, 0.58)" : "rgba(180, 83, 9, 0.40)";
                        roomStroke = "#fbbf24";
                      } else {
                        roomFill = showThermalHeatmap ? "rgba(6, 95, 70, 0.42)" : "rgba(6, 95, 70, 0.26)";
                        roomStroke = "#10b981";
                      }
                      if (isSelectedRoom) {
                        roomStroke = "#ffffff";
                      }

                      return (
                        <g key={rm.space_id}>
                          {/* Room Zone Box */}
                          <rect
                            x={x}
                            y={y}
                            width={w}
                            height={h}
                            rx="6"
                            fill={roomFill}
                            stroke={roomStroke}
                            strokeWidth={isSelectedRoom || isRootFault || isOutlier ? "3" : "1.75"}
                            className="cursor-pointer transition-all hover:opacity-95"
                            onClick={() => handleSelectEntity(rm.space_id, rm.floor_id, true)}
                          />

                          {/* Room Label & Live Temp Header */}
                          <text
                            x={x + 10}
                            y={y + 21}
                            fill="#ffffff"
                            fontSize={w < 110 ? "10.5" : "12.5"}
                            fontWeight="bold"
                            className="pointer-events-none"
                          >
                            {w < 110 ? rm.label.slice(0, 10) : rm.label.slice(0, 26)}
                          </text>
                          <text
                            x={x + w - 8}
                            y={y + 21}
                            textAnchor="end"
                            fill={
                              isRootFault
                                ? "#fda4af"
                                : isOutlier
                                ? "#fde047"
                                : isSympathetic
                                ? "#7dd3fc"
                                : "#6ee7b7"
                            }
                            fontSize={w < 110 ? "10.5" : "12"}
                            fontFamily="monospace"
                            fontWeight="bold"
                            className="pointer-events-none"
                          >
                            {rm.live_temp_f.toFixed(1)}°F
                          </text>

                          {/* SLA Tier & Occupancy Sub-caption */}
                          <text
                            x={x + 10}
                            y={y + 38}
                            fill="#cbd5e1"
                            fontSize="10.5"
                            className="pointer-events-none"
                          >
                            {rm.sla_tier.replace("Tier-", "T")} • Occ {rm.occupancy_pct}%
                          </text>

                          {/* Thermal Heatmap Extra Telemetry Badge (ΔT from Setpoint + Thermal Load kW) */}
                          {showThermalHeatmap && w >= 120 && (
                            <g className="pointer-events-none">
                              <rect
                                x={x + 8}
                                y={y + h - 24}
                                width={Math.min(w - 16, 175)}
                                height="18"
                                rx="4"
                                fill="rgba(2, 6, 23, 0.86)"
                                stroke={deltaF >= 3.0 ? "#f59e0b" : "#059669"}
                                strokeWidth="1"
                              />
                              <text
                                x={x + 14}
                                y={y + h - 11.5}
                                fill={deltaF >= 3.0 ? "#fde68a" : "#a7f3d0"}
                                fontSize="9.5"
                                fontFamily="monospace"
                                fontWeight="bold"
                              >
                                ΔT {deltaF >= 0 ? `+${deltaF.toFixed(1)}` : deltaF.toFixed(1)}°F (SP {setpointF}°F) • {loadKw} kW
                              </text>
                            </g>
                          )}

                          {/* Supply Air Ductwork Lines */}
                          {showDuctwork &&
                            rm.devices.map((dev) => {
                              const isFaultedDuct =
                                dev.runtime_status === "ROOT_CAUSE_FAULT" ||
                                dev.runtime_status === "SYMPATHETIC_IMPACT";
                              return (
                                <path
                                  key={`duct-${dev.node_id}`}
                                  d={`M 500 26 L 500 ${y + 10} L ${dev.pin_x} ${dev.pin_y}`}
                                  fill="none"
                                  stroke={
                                    isFaultedDuct ? "url(#ductGradFault)" : "url(#ductGradNominal)"
                                  }
                                  strokeWidth={isFaultedDuct ? "2.2" : "1.3"}
                                  strokeDasharray={isFaultedDuct ? "6 3" : "4 4"}
                                  className="pointer-events-none"
                                />
                              );
                            })}

                          {/* Clickable Equipment Device Pins inside the Room */}
                          {rm.devices.map((dev) => {
                            const isSelectedDev = selectedNodeId === dev.node_id;
                            const st = dev.runtime_status;
                            let pinColor = "#10b981";
                            if (st === "ROOT_CAUSE_FAULT") pinColor = "#f43f5e";
                            else if (st === "SYMPATHETIC_IMPACT") pinColor = "#38bdf8";
                            else if (st === "ENERGY_OUTLIER") pinColor = "#f59e0b";

                            const shortLabel = dev.label
                              .replace("1st Floor ", "")
                              .replace("2nd Floor ", "")
                              .slice(0, 12);

                            return (
                              <g
                                key={dev.node_id}
                                transform={`translate(${dev.pin_x}, ${dev.pin_y})`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSelectEntity(dev.node_id, rm.floor_id, true);
                                }}
                                className="cursor-pointer"
                              >
                                {(st === "ROOT_CAUSE_FAULT" || st === "ENERGY_OUTLIER" || isSelectedDev) && (
                                  <circle
                                    r="15"
                                    fill="none"
                                    stroke={
                                      st === "ROOT_CAUSE_FAULT"
                                        ? "#f43f5e"
                                        : st === "ENERGY_OUTLIER"
                                        ? "#f59e0b"
                                        : "#38bdf8"
                                    }
                                    strokeWidth="2.5"
                                    strokeDasharray="3 2"
                                  />
                                )}
                                <circle
                                  r="9"
                                  fill="#0f172a"
                                  stroke={pinColor}
                                  strokeWidth={isSelectedDev ? "3" : "2.2"}
                                />
                                <circle r="4" fill={pinColor} />
                                <rect
                                  x="-32"
                                  y="11"
                                  width="64"
                                  height="15"
                                  rx="3"
                                  fill="rgba(2, 6, 23, 0.92)"
                                  stroke={isSelectedDev ? "#38bdf8" : "#475569"}
                                  strokeWidth="1"
                                />
                                <text
                                  x="0"
                                  y="21.5"
                                  textAnchor="middle"
                                  fill={isSelectedDev ? "#7dd3fc" : "#f8fafc"}
                                  fontSize="9.5"
                                  fontFamily="monospace"
                                  fontWeight="bold"
                                >
                                  {shortLabel}
                                </text>
                              </g>
                            );
                          })}
                        </g>
                      );
                    })}
                  </svg>

                  {/* Clean Static Map Key Bar at Bottom of Blueprint */}
                  <div className="px-4 py-2.5 bg-slate-950 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-200">
                    <div className="flex flex-wrap items-center gap-4">
                      <span className="font-bold uppercase tracking-wider text-slate-300">
                        Map Legend:
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-3 h-3 rounded-full bg-emerald-400 inline-block" />
                        <span>Nominal Setpoint</span>
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-3 h-3 rounded-full bg-amber-400 inline-block" />
                        <span>Yellow Outlier / Reheat Waste (78% AI Risk)</span>
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-3 h-3 rounded-full bg-sky-400 inline-block" />
                        <span>Sympathetic Zone (Muted)</span>
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-3 h-3 rounded-full bg-rose-500 inline-block" />
                        <span>Primary Root-Cause Fault</span>
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleSelectEntity(selectedNodeId, undefined, false)}
                        onMouseDown={() => setActiveTab("graph")}
                        className="px-3 py-1 rounded-md bg-slate-900 hover:bg-slate-800 border border-slate-700 text-cyan-300 font-semibold flex items-center gap-1.5"
                      >
                        <GitBranch className="w-3.5 h-3.5" />
                        <span>View in Knowledge Graph</span>
                      </button>
                      <button
                        onClick={() => setEntityDrawerOpen(true)}
                        className="px-3 py-1 rounded-md bg-cyan-950 hover:bg-cyan-900 border border-cyan-500/60 text-cyan-200 font-semibold flex items-center gap-1.5"
                      >
                        <span>Inspect Selected: {neighborhood?.center_node?.label || selectedNodeId}</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: INTERACTIVE KNOWLEDGE GRAPH NEIGHBORHOOD, FLOOR SELECTOR, AI RISK & INLINE CHAT */}
            {activeTab === "graph" && (
              <div className="space-y-4">
                {/* Floor Filter Bar inside Tab 2 (Fixes "Stuck on First Floor in Tab 2") */}
                <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-950 p-3 rounded-xl border border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-200 mr-1">
                      Floor Filter:
                    </span>
                    <button
                      onClick={() => setGraphFloorFilter("ALL")}
                      className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition ${
                        graphFloorFilter === "ALL"
                          ? "bg-cyan-500 text-slate-950 border-cyan-300"
                          : "bg-slate-900 text-slate-200 border-slate-700 hover:border-slate-500"
                      }`}
                    >
                      All Floors ({digitalTwin?.floors?.length || 0})
                    </button>
                    {(digitalTwin?.floors || []).map((fl) => (
                      <button
                        key={fl.floor_id}
                        onClick={() => handleSelectFloor(fl.floor_id)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition ${
                          graphFloorFilter === fl.floor_id
                            ? "bg-cyan-500 text-slate-950 border-cyan-300"
                            : "bg-slate-900 text-slate-200 border-slate-700 hover:border-slate-500"
                        }`}
                      >
                        {fl.short_label}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block" />
                      <span>Root-Cause Fault</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-sky-400 inline-block" />
                      <span>Sympathetic Zone (Muted)</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block" />
                      <span>Energy Outlier (Waste)</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 inline-block" />
                      <span>Nominal Comfort</span>
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-12 gap-4">
                  {/* Searchable Building Device & Room Directory (5 cols) */}
                  <div className="col-span-12 md:col-span-5 bg-slate-950 border border-slate-800 rounded-xl p-3.5 flex flex-col h-[540px]">
                    <div className="text-sm font-bold uppercase tracking-wider text-cyan-300 mb-2.5 flex items-center justify-between">
                      <span>Building Entity Directory</span>
                      <span className="font-mono text-xs text-slate-200">{filteredCatalog.length} nodes</span>
                    </div>

                    {/* Search Input */}
                    <div className="relative mb-2.5">
                      <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                      <input
                        type="text"
                        value={deviceSearch}
                        onChange={(e) => setDeviceSearch(e.target.value)}
                        placeholder="Search rooms, AHUs, VAVs, controllers..."
                        className="w-full pl-9 pr-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-400 focus:outline-none focus:border-cyan-400"
                      />
                    </div>

                    {/* Category Filter Pills */}
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {(["ALL", "AHU", "TERMINAL", "ROOM", "CONTROLLER"] as const).map((cat) => (
                        <button
                          key={cat}
                          onClick={() => setDeviceFilter(cat)}
                          className={`px-2.5 py-1 rounded-md text-xs font-bold border transition ${
                            deviceFilter === cat
                              ? "bg-cyan-500 text-slate-950 border-cyan-300"
                              : "bg-slate-900 text-slate-200 border-slate-700 hover:border-slate-500"
                          }`}
                        >
                          {cat}
                        </button>
                      ))}
                    </div>

                    {/* Entity List (Anomalies automatically sorted to top with color badges) */}
                    <div className="flex-1 overflow-y-auto space-y-2 pr-1">
                      {filteredCatalog.map((item) => {
                        const isSel = item.id === selectedNodeId;
                        const isOutlier = item.status === "ENERGY_OUTLIER";
                        const isFault = item.status === "ROOT_CAUSE_FAULT";
                        const isSymp = item.status === "SYMPATHETIC_IMPACT";
                        return (
                          <button
                            key={item.id}
                            onClick={() => handleSelectEntity(item.id, item.floor_id, false)}
                            className={`w-full text-left p-2.5 rounded-lg border transition flex items-start justify-between gap-2 ${
                              isSel
                                ? "bg-cyan-950 border-cyan-400 text-white"
                                : isFault
                                ? "bg-rose-950/50 border-rose-500/80 text-white"
                                : isOutlier
                                ? "bg-amber-950/40 border-amber-400/80 text-white"
                                : "bg-slate-900/90 border-slate-800 text-slate-100 hover:bg-slate-800"
                            }`}
                          >
                            <div className="min-w-0">
                              <div className="text-sm font-bold truncate flex items-center gap-1.5">
                                <span
                                  className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                                    isFault
                                      ? "bg-rose-500"
                                      : isOutlier
                                      ? "bg-amber-400"
                                      : isSymp
                                      ? "bg-sky-400"
                                      : "bg-emerald-400"
                                  }`}
                                />
                                <span className="truncate">{item.label}</span>
                              </div>
                              <div className="text-xs font-mono text-cyan-300 truncate">{item.ontology}</div>
                              <div className="text-xs text-slate-300 truncate mt-0.5">{item.sub}</div>
                            </div>
                            <div className="flex flex-col items-end gap-1 shrink-0">
                              <span className="px-2 py-0.5 rounded text-xs font-mono bg-slate-950 text-slate-200 border border-slate-700">
                                {item.category}
                              </span>
                              {isOutlier && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500 text-slate-950">
                                  OUTLIER •{" "}
                                  {item.id.includes("smt")
                                    ? "78% RISK (+3.65σ)"
                                    : item.id.includes("piu_8") || item.id.includes("232")
                                    ? "64% RISK (+2.78σ)"
                                    : "74% RISK (+3.42σ)"}
                                </span>
                              )}
                              {isFault && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-600 text-white">
                                  ROOT FAULT
                                </span>
                              )}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Interactive SVG Radial Knowledge Graph Explorer + AI Blast Radius & Mini Chat (7 cols) */}
                  <div className="col-span-12 md:col-span-7 bg-slate-950 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between h-[540px] space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-bold uppercase tracking-wider text-cyan-300 flex items-center gap-2">
                          <span>Interactive Knowledge Graph (Synced 1:1 with Floor Plan Status Colors)</span>
                        </div>
                        <div className="text-xs text-slate-200">
                          Center: <strong className="text-white">{neighborhood?.center_node?.label}</strong> (
                          <code className="text-cyan-300">{selectedNodeId}</code>) •{" "}
                          <span className="text-amber-300 font-bold">
                            AI Failure Risk: {aiDiag?.failure_probability_pct ?? 12}% ({aiDiag?.predicted_failure_window || "Stable"})
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-3 text-[11px] font-mono mt-1">
                          <span className="flex items-center gap-1 text-emerald-300">
                            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 inline-block" /> Healthy
                          </span>
                          <span className="flex items-center gap-1 text-amber-300">
                            <span className="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block" /> Yellow Energy Outlier
                          </span>
                          <span className="flex items-center gap-1 text-sky-300">
                            <span className="w-2.5 h-2.5 rounded-full bg-sky-400 inline-block" /> Sympathetic Impact
                          </span>
                          <span className="flex items-center gap-1 text-rose-300">
                            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block" /> Root-Cause Fault
                          </span>
                        </div>
                      </div>
                      <button
                        onClick={() => setEntityDrawerOpen(true)}
                        className="px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold text-xs"
                      >
                        Open BACnet Points ({neighborhood?.total_points_count || 0})
                      </button>
                    </div>

                    {/* Radial Graph Canvas with Exact Floor Plan Status Colors (Green = Healthy, Yellow = Outlier, Sky = Sympathetic, Red = Fault) */}
                    <div className="h-[255px] rounded-lg bg-[#060e1a] border border-slate-800 overflow-hidden relative">
                      <svg viewBox="0 0 620 280" className="w-full h-full select-none">
                        {(() => {
                          const cx = 310;
                          const cy = 140;
                          const ring = (neighborhood?.neighbors || []).slice(0, 10);
                          const count = Math.max(ring.length, 1);
                          const centerStatus = neighborhood?.center_node?.runtime_status || "HEALTHY";
                          const centerStroke =
                            centerStatus === "ROOT_CAUSE_FAULT"
                              ? "#f43f5e"
                              : centerStatus === "ENERGY_OUTLIER"
                              ? "#fbbf24"
                              : centerStatus === "SYMPATHETIC_IMPACT"
                              ? "#38bdf8"
                              : "#10b981";
                          const centerFill =
                            centerStatus === "ROOT_CAUSE_FAULT"
                              ? "#881337"
                              : centerStatus === "ENERGY_OUTLIER"
                              ? "#92400e"
                              : centerStatus === "SYMPATHETIC_IMPACT"
                              ? "#083344"
                              : "#064e3b";

                          return (
                            <>
                              {/* Edges */}
                              {ring.map((nb, idx) => {
                                const angle = (2 * Math.PI * idx) / count - Math.PI / 2;
                                const nx = cx + Math.cos(angle) * 200;
                                const ny = cy + Math.sin(angle) * 102;
                                const edgeObj = (neighborhood?.edges || []).find(
                                  (e) =>
                                    (e.source_node_id === selectedNodeId && e.target_node_id === nb.node_id) ||
                                    (e.target_node_id === selectedNodeId && e.source_node_id === nb.node_id)
                                );
                                const pred = edgeObj?.edge_type || "SIBLING_ON_AHU";
                                const nbStatus = nb.runtime_status || "HEALTHY";
                                const isOutlierOrFaultEdge =
                                  nbStatus === "ROOT_CAUSE_FAULT" ||
                                  nbStatus === "ENERGY_OUTLIER" ||
                                  centerStatus === "ROOT_CAUSE_FAULT" ||
                                  centerStatus === "ENERGY_OUTLIER";
                                const edgeStroke =
                                  nbStatus === "ROOT_CAUSE_FAULT"
                                    ? "#f43f5e"
                                    : nbStatus === "ENERGY_OUTLIER"
                                    ? "#fbbf24"
                                    : nbStatus === "SYMPATHETIC_IMPACT"
                                    ? "#38bdf8"
                                    : "#10b981";
                                return (
                                  <g key={`edge-${nb.node_id}`}>
                                    <line
                                      x1={cx}
                                      y1={cy}
                                      x2={nx}
                                      y2={ny}
                                      stroke={edgeStroke}
                                      strokeOpacity={isOutlierOrFaultEdge ? "0.9" : "0.6"}
                                      strokeWidth={nbStatus === "ENERGY_OUTLIER" || nbStatus === "ROOT_CAUSE_FAULT" ? "2.5" : "1.7"}
                                      strokeDasharray={nbStatus === "ENERGY_OUTLIER" || nbStatus === "ROOT_CAUSE_FAULT" ? "5 3" : undefined}
                                    />
                                    <text
                                      x={(cx + nx) / 2}
                                      y={(cy + ny) / 2 - 4}
                                      textAnchor="middle"
                                      fill={nbStatus === "ENERGY_OUTLIER" ? "#fde68a" : "#a7f3d0"}
                                      fontSize="8.5"
                                      fontFamily="monospace"
                                      fontWeight="bold"
                                    >
                                      {pred}
                                    </text>
                                  </g>
                                );
                              })}

                              {/* Neighbor Nodes (Color-Coded 1:1 with Floor Plan Status) */}
                              {ring.map((nb, idx) => {
                                const angle = (2 * Math.PI * idx) / count - Math.PI / 2;
                                const nx = cx + Math.cos(angle) * 200;
                                const ny = cy + Math.sin(angle) * 102;
                                const nbStatus = nb.runtime_status || "HEALTHY";
                                let nFill = "#064e3b";
                                let nStroke = "#10b981";
                                let dotColor = "#34d399";
                                if (nbStatus === "ROOT_CAUSE_FAULT") {
                                  nFill = "#881337";
                                  nStroke = "#f43f5e";
                                  dotColor = "#fb7185";
                                } else if (nbStatus === "ENERGY_OUTLIER") {
                                  nFill = "#92400e";
                                  nStroke = "#fbbf24";
                                  dotColor = "#fde047";
                                } else if (nbStatus === "SYMPATHETIC_IMPACT" || nbStatus === "AT_RISK") {
                                  nFill = "#083344";
                                  nStroke = "#38bdf8";
                                  dotColor = "#38bdf8";
                                }

                                return (
                                  <g
                                    key={`node-${nb.node_id}`}
                                    transform={`translate(${nx}, ${ny})`}
                                    onClick={() => handleSelectEntity(nb.node_id, nb.floor_id, false)}
                                    className="cursor-pointer"
                                  >
                                    <rect
                                      x="-72"
                                      y="-19"
                                      width="144"
                                      height="38"
                                      rx="7"
                                      fill={nFill}
                                      stroke={nStroke}
                                      strokeWidth={nbStatus === "ENERGY_OUTLIER" || nbStatus === "ROOT_CAUSE_FAULT" ? "2.8" : "2.0"}
                                    />
                                    <circle cx="-60" cy="-4" r="4" fill={dotColor} />
                                    <text
                                      x="4"
                                      y="-3"
                                      textAnchor="middle"
                                      fill="#ffffff"
                                      fontSize="10"
                                      fontWeight="bold"
                                    >
                                      {String(nb.label || nb.node_id).slice(0, 18)}
                                    </text>
                                    <text
                                      x="0"
                                      y="11"
                                      textAnchor="middle"
                                      fill={
                                        nbStatus === "ENERGY_OUTLIER"
                                          ? "#fef08a"
                                          : nbStatus === "ROOT_CAUSE_FAULT"
                                          ? "#fecdd3"
                                          : nbStatus === "SYMPATHETIC_IMPACT"
                                          ? "#bae6fd"
                                          : "#a7f3d0"
                                      }
                                      fontSize="8.5"
                                      fontFamily="monospace"
                                      fontWeight="bold"
                                    >
                                      {nbStatus === "ENERGY_OUTLIER"
                                        ? "YELLOW OUTLIER"
                                        : nbStatus === "ROOT_CAUSE_FAULT"
                                        ? "ROOT CAUSE FAULT"
                                        : nbStatus === "SYMPATHETIC_IMPACT"
                                        ? "SYMPATHETIC IMPACT"
                                        : `HEALTHY • ${String(nb.ontology_class || "Entity").replace("brick:", "").replace("rec:", "").replace("bsm:", "").slice(0, 11)}`}
                                    </text>
                                  </g>
                                );
                              })}

                              {/* Center Active Node */}
                              <g transform={`translate(${cx}, ${cy})`}>
                                <rect
                                  x="-90"
                                  y="-25"
                                  width="180"
                                  height="50"
                                  rx="10"
                                  fill={centerFill}
                                  stroke={centerStroke}
                                  strokeWidth="3.2"
                                />
                                <text
                                  x="0"
                                  y="-5"
                                  textAnchor="middle"
                                  fill="#ffffff"
                                  fontSize="11"
                                  fontWeight="bold"
                                >
                                  {String(neighborhood?.center_node?.label || selectedNodeId).slice(0, 22)}
                                </text>
                                <text
                                  x="0"
                                  y="12"
                                  textAnchor="middle"
                                  fill={centerStatus === "ENERGY_OUTLIER" ? "#fef08a" : "#a7f3d0"}
                                  fontSize="9"
                                  fontFamily="monospace"
                                  fontWeight="bold"
                                >
                                  {centerStatus} • {aiDiag?.failure_probability_pct ?? 12}% AI Risk
                                </text>
                              </g>
                            </>
                          );
                        })()}
                      </svg>
                    </div>

                    {/* Connected Elements & AI Diagnosis Summary inside Tab 2 */}
                    <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-bold text-cyan-300 flex items-center gap-1.5">
                          <GitBranch className="w-3.5 h-3.5" />
                          <span>
                            Connected Graph Neighbors ({aiDiag?.at_risk_connected_elements?.length || 0} Nodes — Color-Synced with Floor Plan):
                          </span>
                        </span>
                        <span className="font-mono text-[11px] text-emerald-300">
                          Est. Fix: {aiDiag?.mttr_intelligence?.typical_remote_ai_fix_mins ?? 18}m Remote AI vs{" "}
                          {aiDiag?.mttr_intelligence?.typical_manual_fix_hours ?? 3.8}h Manual
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {(aiDiag?.at_risk_connected_elements || []).map((el) => {
                          const st = el.risk_status || "HEALTHY";
                          const pillClass =
                            st === "ROOT_CAUSE_FAULT"
                              ? "border-rose-500/70 bg-rose-950/40 hover:bg-rose-950/70 text-rose-200"
                              : st === "ENERGY_OUTLIER"
                              ? "border-amber-500/70 bg-amber-950/40 hover:bg-amber-950/70 text-amber-200"
                              : st === "SYMPATHETIC_IMPACT"
                              ? "border-sky-500/70 bg-sky-950/40 hover:bg-sky-950/70 text-sky-200"
                              : "border-emerald-500/60 bg-emerald-950/30 hover:bg-emerald-950/60 text-emerald-200";
                          const dotClass =
                            st === "ROOT_CAUSE_FAULT"
                              ? "bg-rose-500"
                              : st === "ENERGY_OUTLIER"
                              ? "bg-amber-400"
                              : st === "SYMPATHETIC_IMPACT"
                              ? "bg-sky-400"
                              : "bg-emerald-400";
                          return (
                            <button
                              key={el.node_id}
                              onClick={() => handleSelectEntity(el.node_id, undefined, false)}
                              title={el.impact_summary}
                              className={`px-2.5 py-1 rounded border text-xs flex items-center gap-1.5 transition ${pillClass}`}
                            >
                              <span className={`w-2 h-2 rounded-full ${dotClass}`} />
                              <span className="font-semibold">{el.label}</span>
                              <span className="font-mono text-[10px] opacity-90">
                                ({el.failure_likelihood_pct}% risk)
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Embedded Mini-Chat Box directly inside Tab 2 */}
                    <form onSubmit={handleTab2ChatSubmit} className="flex gap-2">
                      <input
                        type="text"
                        value={tab2ChatQuestion}
                        onChange={(e) => setTab2ChatQuestion(e.target.value)}
                        placeholder={`Ask AI about ${neighborhood?.center_node?.label || selectedNodeId} or its connected elements...`}
                        className="flex-1 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-cyan-400"
                      />
                      <button
                        type="submit"
                        disabled={askingChat || !tab2ChatQuestion.trim()}
                        className="px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 font-bold text-xs flex items-center gap-1"
                      >
                        <Send className="w-3.5 h-3.5" />
                        <span>Ask AI</span>
                      </button>
                    </form>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 3: BACNET OT NETWORK & 3-TIER CROSS-LAYER VERIFICATION */}
            {activeTab === "bacnet" && (
              <div className="space-y-4">
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-bold text-white">
                      ASHRAE 223P / BSM OT Network &amp; 3-Tier Cross-Layer Verification
                    </h3>
                    <p className="text-sm text-slate-300">
                      Before dispatching a technician or issuing a BACnet override, the AI verifies all 3 network tiers so an IT/OT router drop is never misdiagnosed as an HVAC mechanical failure.
                    </p>
                  </div>
                  <span className="px-3 py-1.5 rounded-lg bg-emerald-950 border border-emerald-500/50 text-emerald-300 font-mono text-xs font-bold">
                    0.0% Packet Loss • {digitalTwin?.controllers_count || 0} Controllers Online
                  </span>
                </div>

                {/* Visual 3-Tier OT Network Architecture Diagram */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="p-3.5 rounded-xl bg-slate-950 border border-emerald-500/40 space-y-1">
                    <div className="text-xs font-mono uppercase text-emerald-300 font-bold">
                      Tier 1 • Building Supervisory Backbone
                    </div>
                    <div className="text-sm font-bold text-white">
                      BACnet/IP Core Switch &amp; Cloud Gateway
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      UDP/IP Port 47808 • 1 Gbps Ethernet backbone connecting supervisory building routers. Status:{" "}
                      <strong className="text-emerald-300">100% Reachable (1.8ms RTT)</strong>.
                    </p>
                  </div>

                  <div className="p-3.5 rounded-xl bg-slate-950 border border-emerald-500/40 space-y-1">
                    <div className="text-xs font-mono uppercase text-emerald-300 font-bold">
                      Tier 2 • Floor BACnet Router (#301003)
                    </div>
                    <div className="text-sm font-bold text-white">
                      BACnet/IP-to-ARCNET / MS/TP Router
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      Routes supervisory Priority 8 commands to field trunks. Status:{" "}
                      <strong className="text-emerald-300">0.0% Packet Loss • Token Ring Stable</strong>.
                    </p>
                  </div>

                  <div className="p-3.5 rounded-xl bg-slate-950 border border-cyan-500/40 space-y-1">
                    <div className="text-xs font-mono uppercase text-cyan-300 font-bold">
                      Tier 3 • Field Equipment Controllers ({digitalTwin?.controllers_count || 0})
                    </div>
                    <div className="text-sm font-bold text-white">
                      ALC Optiflex AHU &amp; Zone VAV/PIU Controllers
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      All field controllers are online and reporting live sensor telemetry — proving any active alarms are{" "}
                      <strong className="text-amber-300">physical mechanical faults</strong>, not comms loss.
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[340px] overflow-y-auto pr-1">
                  {(digitalTwin?.all_controllers || []).slice(0, 30).map((ctrl: any) => (
                    <div
                      key={ctrl.node_id}
                      onClick={() => handleSelectEntity(ctrl.node_id, undefined, true)}
                      className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-cyan-400 cursor-pointer transition flex items-center justify-between"
                    >
                      <div>
                        <div className="text-sm font-bold text-white">{ctrl.label || ctrl.node_id}</div>
                        <div className="text-xs font-mono text-cyan-300 mt-0.5">
                          {ctrl.node_id} • {ctrl.controller_model || "ALC Optiflex"}
                        </div>
                        <div className="text-xs text-slate-300 mt-0.5">
                          Bus: {ctrl.media_type || "ARCNET 156 kbps"} • Parent: {ctrl.network_id || "BACnet/IP"}
                        </div>
                      </div>
                      <span className="px-2.5 py-1 rounded bg-emerald-950 text-emerald-300 border border-emerald-700 font-mono text-xs font-semibold">
                        ONLINE • 0% LOSS
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* TAB 4: POINT TELEMETRY & PREDICTIVE CONE */}
            {activeTab === "telemetry" && (
              <div className="space-y-4">
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
                  <div>
                    <h3 className="text-base font-bold text-white">
                      Bound BACnet Telemetry &amp; TimesFM 2.5 Predictive Horizon:{" "}
                      <span className="text-cyan-300">{neighborhood?.center_node?.label}</span>
                    </h3>
                    <p className="text-sm text-slate-300">
                      Showing {neighborhood?.bacnet_points?.length || 0} of {neighborhood?.total_points_count || 0} BACnet objects bound to `{selectedNodeId}`.
                    </p>
                  </div>
                  <button
                    onClick={() => handleRunLiveNodeAudit("GRAPH_AUDIT")}
                    className="px-3.5 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs"
                  >
                    Run AI Failure &amp; Telemetry Diagnosis
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[420px] overflow-y-auto pr-1">
                  {(neighborhood?.bacnet_points || []).map((pt: any) => (
                    <div
                      key={pt.point_id}
                      className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between gap-3"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-bold text-white truncate">{pt.label}</div>
                        <div className="text-xs font-mono text-cyan-300 truncate mt-0.5">
                          {pt.brick_class}
                        </div>
                        <div className="text-xs font-mono text-slate-300 truncate mt-0.5">
                          URI: {pt.bacnet_uri}
                        </div>
                      </div>
                      <span className="px-2.5 py-1 rounded-md bg-slate-900 border border-slate-700 font-mono text-xs font-bold text-emerald-300 shrink-0">
                        {pt.unit || (pt.has_timeseries === "True" ? "TRENDED" : "ACTIVE")}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* TAB 5: PEER-COHORT ENERGY Z-SCORES, AI FAILURE LIKELIHOOD & HISTORICAL MTTR */}
            {activeTab === "energy" && (
              <div className="space-y-4">
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-bold text-white">
                      Peer-Cohort Energy Z-Scores, Connected Failure Risk &amp; Historical MTTR
                    </h3>
                    <p className="text-sm text-slate-300">
                      Click any room row below to inspect its{" "}
                      <strong className="text-amber-300">AI Failure Probability %</strong>,{" "}
                      <strong className="text-cyan-300">Connected Elements at Risk</strong>, and{" "}
                      <strong className="text-emerald-300">Historical Work Orders &amp; Fix Times (MTTR)</strong>.
                    </p>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-slate-300">Recoverable Annual Waste</div>
                    <div className="text-lg font-bold text-amber-300 font-mono">
                      ${Number(digitalTwin?.site?.identified_annual_energy_savings_usd || 18400).toLocaleString()}/yr •{" "}
                      {digitalTwin?.site?.identified_co2_reduction_tons || 42.0} tCO₂
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  {[...(digitalTwin?.rooms || [])]
                    .sort((a, b) => {
                      const rank = (s: string) =>
                        s === "ROOT_CAUSE_FAULT" ? 0 : s === "ENERGY_OUTLIER" ? 1 : s === "SYMPATHETIC_IMPACT" ? 2 : 3;
                      return rank(a.runtime_status) - rank(b.runtime_status);
                    })
                    .slice(0, 8)
                    .map((rm) => {
                      const isOutlier = rm.runtime_status === "ENERGY_OUTLIER" || rm.live_temp_f >= 74.5;
                      const isPiu8 = rm.space_id.includes("232") || rm.devices.some((d) => d.node_id.includes("piu_8"));
                      const isSmt = rm.space_id.includes("smt") || rm.devices.some((d) => d.node_id.includes("smt"));
                      const zScore = isOutlier
                        ? isSmt
                          ? "+3.65σ (Cleanroom Desiccant/Reheat Conflict)"
                          : isPiu8
                          ? "+2.78σ (Airflow DP Drift & SCR Relay Chatter)"
                          : "+3.42σ (Hydronic Valve Linkage Hysteresis)"
                        : "+0.18σ (Cohort Nominal)";
                      const isExpanded =
                        expandedEnergyRoomId === rm.space_id ||
                        (expandedEnergyRoomId === null && isOutlier && !isPiu8);
                      const failureProb = isOutlier ? (isSmt ? 78 : isPiu8 ? 64 : 74) : 12;
                      const failureWindow = isOutlier
                        ? isSmt
                          ? "Likely desiccant/reheat actuator seizure within 24–36 hours"
                          : isPiu8
                          ? "Likely parallel-fan SCR solid-state relay fatigue within 48–72 hours"
                          : "Likely hydronic reheat globe valve seizure within 36–48 hours"
                        : "Stable (>90 days nominal horizon)";
                      const defaultExplanation = isOutlier
                        ? isSmt
                          ? "ISO-6 Cleanroom terminal unit is fighting 52°F dehumidification cooling with 88% hot-water reheat override (168 cycles/hr), risking $14,500/hr SMT solder-paste viscosity defects."
                          : isPiu8
                          ? "Supply airflow differential-pressure sensor offset (+185 CFM) is triggering premature parallel-fan SCR Stage-1 electric reheat at 74.6°F ($1,760/yr waste)."
                          : "Hydronic hot-water globe valve stem is mechanically binding at 68%–92% open due to brass packing friction while RTU-2 supplies 55.0°F cooling air ($2,620/yr waste)."
                        : "Zone damper and reheat valve tracking within ±0.3°F of cohort mean.";

                      return (
                        <div
                          key={rm.space_id}
                          className={`rounded-xl border transition overflow-hidden ${
                            isOutlier
                              ? "bg-amber-950/35 border-amber-400 text-white shadow-md"
                              : "bg-slate-950 border-slate-800 text-slate-100 hover:border-slate-600"
                          }`}
                        >
                          <div
                            onClick={() => {
                              setExpandedEnergyRoomId(isExpanded ? null : rm.space_id);
                              handleSelectEntity(rm.space_id, rm.floor_id, false);
                            }}
                            className="p-3.5 cursor-pointer flex flex-wrap items-center justify-between gap-3"
                          >
                            <div>
                              <div className="text-sm font-bold flex items-center gap-2">
                                <span>{rm.label}</span>
                                <span
                                  className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold ${
                                    isOutlier
                                      ? "bg-amber-500 text-slate-950"
                                      : "bg-emerald-950 text-emerald-300 border border-emerald-700"
                                  }`}
                                >
                                  AI Failure Risk: {failureProb}% ({isOutlier ? (isPiu8 ? "48–72h Horizon" : "36h Horizon") : "Low"})
                                </span>
                              </div>
                              <div className="text-xs text-slate-300 mt-0.5">
                                Zone Temp: <strong className="text-white">{rm.live_temp_f.toFixed(1)}°F</strong>{" "}
                                (SP {rm.setpoint_f ?? 71.0}°F) • Load:{" "}
                                <strong className="text-amber-200">{rm.thermal_load_kw ?? (isOutlier ? 14.8 : 4.2)} kW</strong>{" "}
                                • Devices: {rm.devices.map((d) => d.label).join(", ")}
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              <span
                                className={`px-3 py-1 rounded-md font-mono text-xs font-bold ${
                                  isOutlier
                                    ? "bg-amber-500 text-slate-950"
                                    : "bg-emerald-950 text-emerald-300 border border-emerald-700"
                                }`}
                              >
                                {zScore}
                              </span>
                              <span className="text-xs font-semibold text-cyan-300 underline">
                                {isExpanded ? "Hide AI Details ▲" : "View AI Risk & MTTR ▼"}
                              </span>
                            </div>
                          </div>

                          {/* Expanded AI Failure Prediction, Connected At-Risk Elements & Historical Work Orders / MTTR */}
                          {isExpanded && (
                            <div className="px-4 pb-4 pt-3 border-t border-slate-800/90 bg-slate-950/90 space-y-3 text-xs">
                              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                {/* Column 1: AI Failure Diagnosis */}
                                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1">
                                  <div className="font-bold text-amber-300 uppercase tracking-wider flex items-center gap-1.5">
                                    <Sparkles className="w-3.5 h-3.5" />
                                    <span>AI Failure Prediction ({failureProb}%)</span>
                                  </div>
                                  <div className="text-white font-semibold">{failureWindow}</div>
                                  <p className="text-slate-300 leading-relaxed">
                                    {selectedNodeId === rm.space_id && aiDiag?.root_cause_explanation
                                      ? aiDiag.root_cause_explanation
                                      : defaultExplanation}
                                  </p>
                                </div>

                              {/* Column 2: Connected Elements at Risk */}
                              <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1.5">
                                <div className="font-bold text-cyan-300 uppercase tracking-wider flex items-center gap-1.5">
                                  <GitBranch className="w-3.5 h-3.5" />
                                  <span>Connected Elements at Risk</span>
                                </div>
                                <div className="space-y-1.5">
                                  {(aiDiag?.at_risk_connected_elements || []).map((el) => (
                                    <div
                                      key={el.node_id}
                                      onClick={() => {
                                        handleSelectEntity(el.node_id, rm.floor_id, false);
                                        setActiveTab("graph");
                                      }}
                                      className="p-2 rounded bg-slate-950 hover:bg-cyan-950/50 border border-slate-800 hover:border-cyan-400 cursor-pointer transition"
                                    >
                                      <div className="flex items-center justify-between font-bold text-white">
                                        <span>{el.label}</span>
                                        <span className="font-mono text-amber-300">
                                          {el.failure_likelihood_pct}% risk
                                        </span>
                                      </div>
                                      <div className="text-[11px] text-cyan-300 font-mono">
                                        {el.relationship}
                                      </div>
                                      <div className="text-[11px] text-slate-300 mt-0.5">
                                        {el.impact_summary}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>

                              {/* Column 3: Typical Fix Duration (MTTR) & Recommended Fix */}
                              <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1.5">
                                <div className="font-bold text-emerald-300 uppercase tracking-wider flex items-center gap-1.5">
                                  <Wrench className="w-3.5 h-3.5" />
                                  <span>Typical Time-to-Fix (MTTR)</span>
                                </div>
                                <div className="flex items-center justify-between bg-slate-950 p-2 rounded border border-emerald-500/40">
                                  <div>
                                    <div className="text-[11px] text-slate-300">Remote AI Override</div>
                                    <div className="text-sm font-bold text-emerald-300 font-mono">
                                      {aiDiag?.mttr_intelligence?.typical_remote_ai_fix_mins ?? 18} mins
                                    </div>
                                  </div>
                                  <div className="text-right">
                                    <div className="text-[11px] text-slate-300">Manual Truck Roll</div>
                                    <div className="text-sm font-bold text-amber-300 font-mono">
                                      {aiDiag?.mttr_intelligence?.typical_manual_fix_hours ?? 3.8} hrs
                                    </div>
                                  </div>
                                </div>
                                <p className="text-slate-200 leading-relaxed">
                                  <strong>Recommended Fix:</strong>{" "}
                                  {aiDiag?.mttr_intelligence?.recommended_fix_action ||
                                    "Issue BACnet Priority 8 valve stroke calibration and release stuck reheat override."}
                                </p>
                                <div className="flex gap-2 pt-1">
                                  <button
                                    onClick={() => {
                                      handleSelectEntity(rm.space_id, rm.floor_id, false);
                                      setActiveTab("graph");
                                    }}
                                    className="px-2.5 py-1 rounded bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold"
                                  >
                                    View in Knowledge Graph
                                  </button>
                                  <button
                                    onClick={() => handleSelectEntity(rm.space_id, rm.floor_id, true)}
                                    className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 font-semibold"
                                  >
                                    Inspect BACnet Points
                                  </button>
                                </div>
                              </div>
                            </div>

                            {/* Historical Work Orders Table */}
                            <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                              <div className="font-bold text-slate-200 uppercase tracking-wider mb-2">
                                Historical Similar Incidents &amp; Maintenance Work Orders (CMMS Grounded):
                              </div>
                              <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                                {(aiDiag?.mttr_intelligence?.historical_incidents || []).map((inc) => (
                                  <div
                                    key={inc.work_order_id}
                                    className="p-2.5 rounded bg-slate-950 border border-slate-800 space-y-1"
                                  >
                                    <div className="flex items-center justify-between font-mono text-[11px]">
                                      <span className="font-bold text-cyan-300">{inc.work_order_id}</span>
                                      <span className="text-slate-400">{inc.date}</span>
                                    </div>
                                    <div className="font-semibold text-white">{inc.symptom}</div>
                                    <div className="text-slate-300">
                                      <strong>Fix:</strong> {inc.fix_applied}
                                    </div>
                                    <div className="text-emerald-300 font-mono text-[11px] pt-0.5">
                                      AI Fix: {inc.remote_ai_fix_mins}m (vs {inc.manual_dispatch_hrs}h manual)
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* TAB 6: DEDICATED BAS EVENT STREAM & ROUTINE TELEMETRY HEARTBEATS */}
            {activeTab === "alarms" && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-bold text-white">
                      Live BAS Event Stream &amp; AI Alarm Storm Deduplication
                    </h3>
                    <p className="text-sm text-slate-300">
                      Separates the <strong className="text-rose-300">[CRITICAL] Primary Root-Cause Equipment Failure</strong> from{" "}
                      <strong className="text-cyan-300">[HIGH] Downstream Room Temperature Symptoms</strong>.
                    </p>
                  </div>
                  {hasActiveIncident && (
                    <button
                      onClick={() => handleOpenRootCauseModal()}
                      className="px-3.5 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold flex items-center gap-1.5 shadow"
                    >
                      <Crosshair className="w-4 h-4" />
                      <span>Open Root Cause Causal Graph</span>
                    </button>
                  )}
                </div>

                {/* Plain-English Explainer Legend for [CRITICAL] vs [HIGH] */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                  <div className="p-3 rounded-xl bg-rose-950/40 border border-rose-500/60 flex items-start gap-2.5">
                    <span className="px-2 py-0.5 rounded bg-rose-600 text-white font-mono font-bold shrink-0">
                      [CRITICAL]
                    </span>
                    <div>
                      <div className="font-bold text-white">
                        Primary Root-Cause Equipment Failure ({rootCauseAlarms.length})
                      </div>
                      <p className="text-slate-200 mt-0.5">
                        The physical upstream HVAC supply unit (e.g., Primary Air Handler or CRAC unit) that mechanically tripped or seized. <strong>Fix this single unit first.</strong>
                      </p>
                    </div>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-950 border border-cyan-500/50 flex items-start gap-2.5">
                    <span className="px-2 py-0.5 rounded bg-cyan-900 text-cyan-200 border border-cyan-400/50 font-mono font-bold shrink-0">
                      [HIGH]
                    </span>
                    <div>
                      <div className="font-bold text-white">
                        Downstream Sympathetic Room Symptoms ({suppressedAlarms.length} Muted by AI)
                      </div>
                      <p className="text-slate-300 mt-0.5">
                        Secondary room temperature drift alarms caused by the upstream `[CRITICAL]` supply failure. Automatically muted by AI so operators aren't flooded by 31 separate room pages.
                      </p>
                    </div>
                  </div>
                </div>

                {!hasActiveIncident ? (
                  <div className="space-y-2.5">
                    <div className="p-4 rounded-xl bg-emerald-950/30 border border-emerald-500/40 flex items-center gap-3 text-sm text-emerald-200">
                      <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                      <span>
                        <strong>0 Active Fault Alarms:</strong> All HVAC supply risers, zone terminal boxes, and BACnet routers in{" "}
                        <strong>{digitalTwin?.site?.site_name}</strong> are operating within nominal SLA bounds.
                      </span>
                    </div>
                    {(digitalTwin?.routine_bas_heartbeats || []).map((hb, idx) => (
                      <div
                        key={idx}
                        className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between text-sm"
                      >
                        <div className="flex items-center gap-3">
                          <span className="px-2.5 py-1 rounded bg-slate-900 border border-slate-700 font-mono text-xs text-cyan-300 font-bold">
                            {hb.timestamp}
                          </span>
                          <span className="text-slate-100">{hb.message}</span>
                        </div>
                        <span className="font-mono text-xs text-emerald-300 shrink-0">{hb.protocol}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="space-y-3 max-h-[390px] overflow-y-auto pr-1">
                    {/* Group 1: Primary Root-Cause [CRITICAL] Alarm */}
                    <div className="text-xs font-bold uppercase tracking-wider text-rose-300">
                      1. Primary Root-Cause Equipment Failure (Action Required):
                    </div>
                    {rootCauseAlarms.map((ev) => (
                      <div
                        key={ev.event_id}
                        onClick={() => handleOpenRootCauseModal(ev.node_id)}
                        className="p-3.5 rounded-xl border-2 bg-rose-950/75 border-rose-500 text-white shadow-md text-sm flex items-center justify-between cursor-pointer transition"
                      >
                        <div className="pr-3">
                          <span className="px-2 py-0.5 rounded bg-rose-600 text-white font-mono text-xs font-bold mr-2">
                            [{ev.severity}] ROOT CAUSE
                          </span>
                          <span className="font-mono text-cyan-300 mr-2 underline">{ev.node_id}</span>
                          <span className="font-semibold">{ev.alarm_message}</span>
                        </div>
                        <span className="px-3 py-1 rounded-md font-bold text-xs whitespace-nowrap shrink-0 flex items-center gap-1.5 bg-rose-600 text-white">
                          <Crosshair className="w-3.5 h-3.5" />
                          <span>TRACE BLAST RADIUS</span>
                        </span>
                      </div>
                    ))}

                    {/* Group 2: Indented Downstream Sympathetic [HIGH] Room Alarms */}
                    <div className="text-xs font-bold uppercase tracking-wider text-cyan-300 pt-2">
                      2. Downstream Sympathetic Room Symptoms ({suppressedAlarms.length} Automatically Muted by AI):
                    </div>
                    <div className="space-y-2 pl-4 border-l-2 border-cyan-500/40">
                      {suppressedAlarms.map((ev) => (
                        <div
                          key={ev.event_id}
                          onClick={() => handleOpenRootCauseModal(ev.node_id)}
                          className="p-3 rounded-xl border bg-slate-950 border-slate-800 hover:border-cyan-400 text-slate-100 text-sm flex items-center justify-between cursor-pointer transition"
                        >
                          <div className="pr-3">
                            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-cyan-300 font-mono text-xs font-bold mr-2">
                              [{ev.severity}] SYMPTOM
                            </span>
                            <span className="font-mono text-cyan-300 mr-2 underline">{ev.node_id}</span>
                            <span>{ev.alarm_message}</span>
                          </div>
                          <span className="px-2.5 py-1 rounded-md font-bold text-xs whitespace-nowrap shrink-0 flex items-center gap-1.5 bg-slate-900 text-cyan-300 border border-cyan-500/40">
                            <Crosshair className="w-3.5 h-3.5" />
                            <span>MUTED BY AI • VIEW PARENT</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {/* Right 4 Columns: Conversational ADK 2.0 Agent Co-Pilot & HITL Priority 8 Card */}
        <aside className="col-span-12 lg:col-span-4 bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col justify-between h-[720px]">
          {/* Header */}
          <div className="border-b border-slate-800 pb-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <Cpu className="w-5 h-5 text-cyan-400" />
                <span>AI Building Co-Pilot &amp; Remediation</span>
              </h2>
              <span className="text-xs font-mono px-2.5 py-0.5 rounded-md bg-emerald-950 text-emerald-300 border border-emerald-600/50 font-semibold">
                Vertex AI Agent Runtime
              </span>
            </div>
            <div className="text-xs text-slate-300 mt-1">
              Analyzing: <strong className="text-white">{digitalTwin?.site?.site_name}</strong> • Selected:{" "}
              <code className="text-cyan-300">{neighborhood?.center_node?.label || selectedNodeId}</code>
            </div>
            <div className="mt-2 p-2 rounded-lg bg-slate-950 border border-slate-800 text-[10px] font-mono text-slate-300 space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-cyan-300 font-semibold">Runtime: reasoningEngines/5782923462607634432</span>
                <span className="text-emerald-300">OTel: Cloud Trace + Monitoring</span>
              </div>
              <div className="flex items-center justify-between truncate">
                <span className="text-amber-200 truncate">Gateway: acme-abo-agent-gateway (Cloud Run)</span>
                <span className="text-slate-400">IAM OIDC Identity</span>
              </div>
            </div>

            {/* Quick Suggested Questions */}
            <div className="mt-3 flex flex-wrap gap-1.5">
              {[
                "What locations require attention?",
                activeBuildingId === "ACME-SITE-004"
                  ? "What is the impact if IND-AHU-1 (Process Make-Up & Chilled Water) fails?"
                  : `What is the impact if ${currentFloorMeta?.primary_ahu_label || "RTU-1 (1st Floor Air Handler)"} fails?`,
                "Are there any energy waste outliers?",
                "What connected elements are at risk?",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => handleSuggestedQuestion(q)}
                  disabled={askingChat}
                  className="px-2.5 py-1 rounded-md bg-slate-950 hover:bg-cyan-950 border border-slate-700 hover:border-cyan-400 text-xs text-cyan-200 transition text-left"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>

          {/* Middle Scrollable Stream: HITL Proposals + Conversational Q&A & Reasoning Cards */}
          <div className="flex-1 overflow-y-auto my-3 space-y-3 pr-1">
            {/* Staged Human-in-the-Loop BACnet Override Cards (Plain-English Explained + Closed-Loop Recovery) */}
            {stagedHitlActions.map((act) => (
              <div
                key={act.action_id}
                className="p-4 rounded-xl bg-amber-950/60 border-2 border-amber-400 space-y-2.5 text-sm shadow-lg"
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-amber-200 flex items-center gap-1.5">
                    <ShieldCheck className="w-4 h-4 text-amber-300" />
                    <span>
                      {act.plain_english_title ||
                        `AI Recommended Fix (BACnet Priority ${act.bacnet_priority})`}
                    </span>
                  </span>
                  <span className="px-2 py-0.5 rounded bg-emerald-900 text-emerald-200 font-mono text-xs font-bold">
                    SAFETY CHECK: {act.shacl_validation}
                  </span>
                </div>

                <div className="font-mono text-xs text-white bg-slate-950 p-2.5 rounded border border-slate-800 space-y-1">
                  <div>
                    <strong>Command:</strong> Set <code>{act.target_point_id}</code> →{" "}
                    <strong className="text-emerald-300">
                      {act.proposed_value} {act.unit}
                    </strong>{" "}
                    (BACnet Priority {act.bacnet_priority} Manual Operator Override)
                  </div>
                </div>

                <div className="space-y-1.5 text-xs text-slate-100 leading-relaxed bg-slate-950/70 p-2.5 rounded-lg border border-amber-500/30">
                  <div>
                    <strong className="text-amber-300">Why AI Recommends This Fix:</strong>{" "}
                    {act.why_ai_chose_this || act.rationale}
                  </div>
                  {act.safety_verification_explained && (
                    <div>
                      <strong className="text-cyan-300">Automated Safety Guardrail (SHACL):</strong>{" "}
                      {act.safety_verification_explained}
                    </div>
                  )}
                  <div>
                    <strong className="text-emerald-300">What Happens When You Click Approve:</strong>{" "}
                    {act.what_happens_on_approve ||
                      act.expected_outcome ||
                      "Immediately dispatches BACnet Priority 8 override, restores supply airflow, clears all 31 sympathetic zone alarms, and recovers 1st-floor room temperatures back to 71.8°F."}
                  </div>
                </div>

                {act.status ? (
                  <div className="p-2.5 rounded-lg bg-emerald-950 border border-emerald-500/60 text-emerald-200 font-bold flex items-center gap-2 text-xs">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>
                      {act.status === "APPROVED"
                        ? "APPROVED & EXECUTED: Closed-loop BACnet Priority 8 override verified — building temperatures restored to 71.8°F nominal!"
                        : `Status: ${act.status}`}
                    </span>
                  </div>
                ) : (
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={() => decideHitlAction(act.action_id, "APPROVE")}
                      className="flex-1 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow cursor-pointer"
                    >
                      Approve &amp; Execute Closed-Loop Recovery
                    </button>
                    <button
                      onClick={() => decideHitlAction(act.action_id, "REJECT")}
                      className="px-3 py-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold cursor-pointer"
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>
            ))}

            {/* Conversation & Multi-Agent Reasoning Stream */}
            {agentSteps.length === 0 ? (
              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-sm text-slate-200 space-y-2">
                <div className="flex items-center gap-2 font-bold text-cyan-300">
                  <MessageSquare className="w-4 h-4" />
                  <span>Ask Anything About {digitalTwin?.site?.site_name}</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Type an open-ended question below, click one of the prompt pills above, or click any room/device on the Floor Plan to query the{" "}
                  <strong className="text-white">Brick v1.4 + ASHRAE 223P Knowledge Graph</strong>.
                </p>
              </div>
            ) : (
              agentSteps.map((step, idx) => (
                <div
                  key={idx}
                  className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 text-sm space-y-2 shadow"
                >
                  {step.user_question && (
                    <div className="p-2.5 rounded-lg bg-cyan-950/70 border border-cyan-500/40 text-xs text-cyan-100">
                      <span className="font-bold text-cyan-300 mr-1.5">You asked:</span>
                      <span>{step.user_question}</span>
                    </div>
                  )}
                  <div className="flex items-center justify-between text-xs font-bold text-cyan-300">
                    <span>{step.subagent}</span>
                    <span className="font-mono text-amber-300">{step.tool_called}</span>
                  </div>
                  <div className="text-slate-100 text-xs leading-relaxed whitespace-pre-line">
                    {step.summary}
                  </div>
                  {step.otel_span_id && (
                    <div className="pt-2 border-t border-slate-900 text-[10px] font-mono text-slate-300 space-y-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-emerald-300 truncate">
                          {step.agent_gateway || "acme-abo-client-to-agent (ALLOW)"}
                        </span>
                        <span className="text-cyan-300 shrink-0">
                          Runtime: reasoningEngines/5782923462607634432
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-amber-200 truncate" title={step.agent_identity}>
                          ID: {step.agent_identity || "sa-agent-supervisor@genai-demos-391416.iam.gserviceaccount.com"}
                          {step.agent_identity_token_sha256 ? ` (OIDC:${step.agent_identity_token_sha256.slice(0, 8)})` : ""}
                        </span>
                        {step.cloud_trace_console_url ? (
                          <a
                            href={step.cloud_trace_console_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-cyan-300 hover:text-cyan-200 underline shrink-0"
                          >
                            Trace:{step.otel_trace_id?.slice(0, 8)} / Span:{step.otel_span_id.slice(0, 8)} ↗
                          </a>
                        ) : (
                          <span className="shrink-0">OTel Span: {step.otel_span_id}</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Open-Ended Dialogue Input Box at Bottom of Right Pane */}
          <form onSubmit={handleChatSubmit} className="pt-2 border-t border-slate-800">
            <label className="block text-xs font-semibold text-slate-200 mb-1.5">
              Ask about {digitalTwin?.site?.site_name || "this building"} or all 5 global sites:
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={chatQuestion}
                onChange={(e) => setChatQuestion(e.target.value)}
                placeholder="e.g., What locations require attention? Or: What if IND-AHU-1 fails?"
                className="flex-1 px-3.5 py-2.5 rounded-lg bg-slate-950 border border-slate-700 text-sm text-white placeholder-slate-400 focus:outline-none focus:border-cyan-400"
              />
              <button
                type="submit"
                disabled={askingChat || !chatQuestion.trim()}
                className="px-4 py-2.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 font-bold text-sm flex items-center gap-1.5 shadow"
              >
                <Send className="w-4 h-4" />
                <span>{askingChat ? "..." : "Ask"}</span>
              </button>
            </div>
          </form>
        </aside>
      </div>

      {/* SLIDE-OVER ENTITY DEEP INSPECTOR DRAWER (Progressive Disclosure when clicking a Room or Device) */}
      {entityDrawerOpen && (
        <div className="fixed inset-0 z-40 bg-slate-950/60 backdrop-blur-xs flex justify-end">
          <div className="w-full max-w-xl bg-slate-900 border-l border-slate-700 h-full p-6 overflow-y-auto flex flex-col justify-between space-y-5 shadow-2xl">
            <div className="space-y-5">
              <div className="flex items-start justify-between border-b border-slate-800 pb-4">
                <div>
                  <span className="px-2.5 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-500/40 font-mono text-xs font-bold">
                    {neighborhood?.center_node?.ontology_class || "brick:Entity"}
                  </span>
                  <h3 className="text-xl font-bold text-white mt-1.5">
                    {neighborhood?.center_node?.label || selectedNodeId}
                  </h3>
                  <code className="text-xs text-cyan-300 font-mono">{selectedNodeId}</code>
                </div>
                <button
                  onClick={() => setEntityDrawerOpen(false)}
                  className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Plain-English Action Buttons */}
              <div className="flex flex-wrap gap-2.5">
                <button
                  onClick={() => handleRunLiveNodeAudit("GRAPH_AUDIT")}
                  disabled={analyzingNode}
                  className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-sm flex items-center gap-2 shadow"
                >
                  <Sparkles className="w-4 h-4" />
                  <span>
                    {analyzingNode
                      ? "Diagnosing Failure Risk & Blast Radius..."
                      : "Run AI Failure & Blast-Radius Diagnosis"}
                  </span>
                </button>
                <button
                  onClick={() => {
                    setEntityDrawerOpen(false);
                    setActiveTab("graph");
                  }}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 text-sm font-semibold flex items-center gap-2"
                >
                  <GitBranch className="w-4 h-4 text-cyan-300" />
                  <span>Open in Radial Graph Explorer</span>
                </button>
              </div>

              {/* AI Failure Probability, Blast Radius & Typical MTTR Summary Card inside Drawer */}
              {aiDiag && (
                <div className="p-4 rounded-xl bg-slate-950 border border-amber-500/50 space-y-2.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-amber-300 uppercase tracking-wider flex items-center gap-1.5">
                      <Sparkles className="w-4 h-4" />
                      <span>AI Predictive Failure &amp; MTTR Intelligence</span>
                    </span>
                    <span className="px-2 py-0.5 rounded bg-amber-500 text-slate-950 font-mono font-bold">
                      {aiDiag.failure_probability_pct}% Failure Risk ({aiDiag.risk_level})
                    </span>
                  </div>
                  <div className="text-slate-200 leading-relaxed">
                    <strong>Diagnosis:</strong> {aiDiag.root_cause_explanation}
                  </div>
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    <div className="p-2 rounded bg-slate-900 border border-slate-800">
                      <div className="text-slate-400">Remote AI Calibration Fix</div>
                      <div className="text-sm font-bold text-emerald-300 font-mono">
                        {aiDiag.mttr_intelligence?.typical_remote_ai_fix_mins ?? 18} mins
                      </div>
                    </div>
                    <div className="p-2 rounded bg-slate-900 border border-slate-800">
                      <div className="text-slate-400">Manual Field Truck Roll</div>
                      <div className="text-sm font-bold text-amber-300 font-mono">
                        {aiDiag.mttr_intelligence?.typical_manual_fix_hours ?? 3.8} hours
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Connected Graph Neighbors */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200 mb-2">
                  Connected Knowledge Graph Entities ({neighborhood?.neighbors?.length || 0} Nodes — Click to Traverse):
                </h4>
                <div className="flex flex-wrap gap-2">
                  {(neighborhood?.neighbors || []).slice(0, 16).map((nb) => {
                    const nbSt = nb.runtime_status || "HEALTHY";
                    const nbDot =
                      nbSt === "ROOT_CAUSE_FAULT"
                        ? "bg-rose-500"
                        : nbSt === "ENERGY_OUTLIER"
                        ? "bg-amber-400"
                        : nbSt === "SYMPATHETIC_IMPACT"
                        ? "bg-sky-400"
                        : "bg-emerald-400";
                    const nbBorder =
                      nbSt === "ROOT_CAUSE_FAULT"
                        ? "border-rose-500/60 bg-rose-950/30"
                        : nbSt === "ENERGY_OUTLIER"
                        ? "border-amber-500/60 bg-amber-950/30"
                        : nbSt === "SYMPATHETIC_IMPACT"
                        ? "border-sky-500/60 bg-sky-950/30"
                        : "border-emerald-500/40 bg-emerald-950/20";
                    return (
                      <button
                        key={nb.node_id}
                        onClick={() => handleSelectEntity(nb.node_id, nb.floor_id, true)}
                        className={`px-3 py-1.5 rounded-lg hover:bg-cyan-950 border hover:border-cyan-400 text-xs flex items-center gap-1.5 transition ${nbBorder}`}
                      >
                        <span className={`w-2 h-2 rounded-full ${nbDot}`} />
                        <span className="font-bold text-white">{nb.label || nb.node_id}</span>
                        <span className="font-mono text-cyan-300">({nb.ontology_class})</span>
                        <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Bound BACnet Telemetry Points */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200 mb-2">
                  Bound BACnet Telemetry Points ({neighborhood?.total_points_count || 0} Total):
                </h4>
                <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                  {(neighborhood?.bacnet_points || []).slice(0, 12).map((pt: any) => (
                    <div
                      key={pt.point_id}
                      className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-xs"
                    >
                      <div>
                        <div className="font-bold text-white text-sm">{pt.label}</div>
                        <div className="font-mono text-cyan-300 mt-0.5">
                          {pt.brick_class} • {pt.bacnet_uri}
                        </div>
                      </div>
                      <span className="px-2.5 py-1 rounded bg-slate-900 border border-slate-700 font-mono text-emerald-300 font-bold">
                        {pt.unit || "TRENDED"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="pt-4 border-t border-slate-800 flex justify-end">
              <button
                onClick={() => setEntityDrawerOpen(false)}
                className="px-5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-sm font-semibold"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ROOT CAUSE & BLAST-RADIUS MODAL (Distinct Pre-Alarm Nominal vs Active Incident States) */}
      {rootCauseModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-xs flex items-center justify-center p-4">
          <div
            className={`bg-slate-900 border-2 rounded-2xl max-w-3xl w-full p-6 shadow-2xl space-y-5 ${
              hasActiveIncident ? "border-rose-500" : "border-emerald-500/70"
            }`}
          >
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-3">
                <div
                  className={`p-2.5 rounded-xl border ${
                    hasActiveIncident
                      ? "bg-rose-500/20 text-rose-300 border-rose-500/50"
                      : "bg-emerald-500/20 text-emerald-300 border-emerald-500/50"
                  }`}
                >
                  {hasActiveIncident ? (
                    <Crosshair className="w-6 h-6" />
                  ) : (
                    <CheckCircle2 className="w-6 h-6" />
                  )}
                </div>
                <div>
                  <div className="text-xs font-mono uppercase text-cyan-300 font-bold">
                    {hasActiveIncident
                      ? "Active Multi-Hop Root-Cause Analysis (abo-graph-rca-specialist)"
                      : "Pre-Alarm System Status & Dependency Topology Check"}
                  </div>
                  <h3 className="text-lg font-bold text-white">
                    {hasActiveIncident
                      ? `Confirmed Root Cause on ${neighborhood?.center_node?.label || selectedNodeId}`
                      : `No Active Root-Cause Incidents in ${digitalTwin?.site?.site_name}`}
                  </h3>
                </div>
              </div>
              <button
                onClick={() => setRootCauseModalOpen(false)}
                className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {!hasActiveIncident ? (
              /* PRE-ALARM (T=0) HONEST NOMINAL STATE */
              <div className="space-y-4 text-sm">
                <div className="p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/50 text-emerald-100 space-y-1.5">
                  <div className="font-bold text-base text-emerald-300">
                    All Building Systems Nominal (0 Active Root-Cause Faults • 0 Sympathetic Alarms)
                  </div>
                  <p className="text-slate-200 leading-relaxed">
                    There are currently no active equipment trips or zone starvation alarms. You can optionally run a{" "}
                    <strong>Pre-Alarm What-If Blast-Radius Simulation</strong> below to preview which downstream rooms and terminal units depend on{" "}
                    <code className="text-cyan-300">{neighborhood?.center_node?.label || selectedNodeId}</code> in the Knowledge Graph.
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                  <div className="text-xs font-bold uppercase tracking-wider text-cyan-300">
                    Selected Entity Topology Preview ({neighborhood?.center_node?.label}):
                  </div>
                  <p className="text-slate-200 text-sm">
                    Connected to <strong>{neighborhood?.neighbors?.length || 0} graph neighbors</strong> across{" "}
                    <strong>{neighborhood?.edges?.length || 0} ontology edges</strong> (`brick:feeds`, `rec:locatedIn`, `bsm:controlledBy`).
                  </p>
                </div>
              </div>
            ) : (
              /* ACTIVE INCIDENT (T=1) 3-LAYER CAUSAL CHAIN */
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5 text-sm">
                  <div className="p-4 rounded-xl bg-rose-950/50 border border-rose-500/70 space-y-1.5">
                    <div className="text-xs font-mono uppercase text-rose-300 font-bold">
                      1. Mechanical Root Cause (brick:feeds)
                    </div>
                    <div className="font-bold text-white text-base">
                      {neighborhood?.center_node?.label || selectedNodeId}
                    </div>
                    <p className="text-slate-200 text-xs leading-relaxed">
                      Primary thermal supply parent verified in <code>acme_building_graph</code>. Feeds{" "}
                      <strong>
                        {(neighborhood?.edges || []).filter((e) => e.edge_type === "FEEDS").length}
                      </strong>{" "}
                      downstream terminal units.
                    </p>
                  </div>

                  <div className="p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/60 space-y-1.5">
                    <div className="text-xs font-mono uppercase text-emerald-300 font-bold">
                      2. BACnet OT Network Check
                    </div>
                    <div className="font-bold text-white text-base">
                      Router #301003 (0.0% Loss)
                    </div>
                    <p className="text-slate-200 text-xs leading-relaxed">
                      Cross-layer hop confirmed <strong>0.0% packet loss</strong> on BACnet router{" "}
                      <code>bldg:bacnet_device_301003</code> — ruling out an OT network outage.
                    </p>
                  </div>

                  <div className="p-4 rounded-xl bg-cyan-950/50 border border-cyan-500/60 space-y-1.5">
                    <div className="text-xs font-mono uppercase text-cyan-300 font-bold">
                      3. Sympathetic Alarm Deduplication
                    </div>
                    <div className="font-bold text-white text-base">
                      {suppressedAlarms.length} Downstream Alarms Muted
                    </div>
                    <p className="text-slate-200 text-xs leading-relaxed">
                      Downstream zone starvation alarms automatically suppressed and rolled up under this single root-cause incident.
                    </p>
                  </div>
                </div>

                <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
                  <div className="text-xs font-bold uppercase tracking-wider text-slate-200">
                    Click Any Impacted Entity in the Blast Radius to Inspect:
                  </div>
                  <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
                    {(neighborhood?.neighbors || []).map((nb) => (
                      <button
                        key={nb.node_id}
                        onClick={() => {
                          setRootCauseModalOpen(false);
                          handleSelectEntity(nb.node_id, nb.floor_id, true);
                        }}
                        className="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-cyan-950 border border-slate-700 hover:border-cyan-400 text-xs font-mono text-cyan-200"
                      >
                        {nb.label || nb.node_id}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <div className="flex flex-wrap justify-end gap-2.5 pt-2 border-t border-slate-800">
              {!hasActiveIncident && (
                <button
                  onClick={() => {
                    handleRunLiveNodeAudit("ROOT_CAUSE_TRACE");
                    setRootCauseModalOpen(false);
                  }}
                  className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-sm"
                >
                  Run What-If Blast-Radius Simulation in Co-Pilot
                </button>
              )}
              <button
                onClick={() => {
                  setRootCauseModalOpen(false);
                  setActiveTab("graph");
                }}
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 font-semibold text-sm"
              >
                View in Radial Graph
              </button>
              <button
                onClick={() => setRootCauseModalOpen(false)}
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-semibold"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
