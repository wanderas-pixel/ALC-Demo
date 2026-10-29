import { create } from "zustand";

export interface BasAlarmEvent {
  event_id: string;
  timestamp: string;
  building_id: string;
  scenario_id: string;
  node_id: string;
  point_id: string;
  event_category: string;
  severity: string;
  is_root_cause: boolean;
  suppressed_by_agent: boolean;
  root_cause_event_id: string;
  alarm_message: string;
}

export interface AgentReasoningStep {
  agent_name: string;
  subagent: string;
  tool_called: string;
  user_question?: string;
  summary: string;
  shacl_status?: string;
  otel_trace_id?: string;
  otel_span_id?: string;
  traceparent?: string;
  cloud_trace_console_url?: string;
  agent_runtime?: string;
  agent_runtime_invoked?: boolean;
  agent_runtime_latency_ms?: number;
  agent_gateway?: string;
  agent_gateway_url?: string;
  agent_identity?: string;
  agent_identity_token_sha256?: string;
  agent_registry_uri?: string;
}

export interface StagedHitlAction {
  action_id: string;
  target_point_id: string;
  proposed_value: number;
  unit: string;
  bacnet_priority: number;
  shacl_validation: string;
  rationale: string;
  plain_english_title?: string;
  why_ai_chose_this?: string;
  safety_verification_explained?: string;
  expected_outcome?: string;
  what_happens_on_approve?: string;
  verification_summary?: string;
  work_order_id?: string;
  status?: string;
}

export type CockpitTabId =
  | "floorplan"
  | "graph"
  | "bacnet"
  | "telemetry"
  | "energy"
  | "alarms";

interface CockpitState {
  activeBuildingId: string;
  selectedFloorId: string;
  activeTab: CockpitTabId;
  selectedNodeId: string;
  entityDrawerOpen: boolean;
  activeScenario: string | null;
  buildingHealed: boolean;
  remediatedScenario: string | null;
  injectedEvents: BasAlarmEvent[];
  agentSteps: AgentReasoningStep[];
  stagedHitlActions: StagedHitlAction[];
  lastResetTs: string | null;
  lastResetLatencyMs: number | null;
  rootCauseModalOpen: boolean;
  setActiveBuildingId: (siteId: string) => void;
  setSelectedFloorId: (floorId: string) => void;
  setActiveTab: (tab: CockpitTabId) => void;
  setSelectedNodeId: (nodeId: string) => void;
  setEntityDrawerOpen: (open: boolean) => void;
  setRootCauseModalOpen: (open: boolean) => void;
  triggerScenario: (scenarioId: string, speedMultiplier?: number) => Promise<void>;
  resetDemo: () => Promise<void>;
  decideHitlAction: (actionId: string, decision: "APPROVE" | "REJECT") => Promise<void>;
  analyzeNodeWithAgent: (
    nodeId: string,
    mode?: "ROOT_CAUSE_TRACE" | "GRAPH_AUDIT" | "ENERGY_COHORT_CHECK"
  ) => Promise<void>;
  askBuildingQuestion: (
    siteId: string,
    selectedNodeId: string,
    question: string
  ) => Promise<void>;
  connectSseStream: () => () => void;
}

export const useCockpitStore = create<CockpitState>((set) => ({
  activeBuildingId: "ACME-SITE-001",
  selectedFloorId: "bldg:ec_1st_floor",
  activeTab: "floorplan",
  selectedNodeId: "bldg:area_ec_ahu_1",
  entityDrawerOpen: false,
  activeScenario: null,
  buildingHealed: false,
  remediatedScenario: null,
  injectedEvents: [],
  agentSteps: [],
  stagedHitlActions: [],
  lastResetTs: null,
  lastResetLatencyMs: null,
  rootCauseModalOpen: false,

  setActiveBuildingId: (siteId) => set({ activeBuildingId: siteId, entityDrawerOpen: false }),
  setSelectedFloorId: (floorId) => set({ selectedFloorId: floorId }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setSelectedNodeId: (nodeId) => set({ selectedNodeId: nodeId }),
  setEntityDrawerOpen: (open) => set({ entityDrawerOpen: open }),
  setRootCauseModalOpen: (open) => set({ rootCauseModalOpen: open }),

  triggerScenario: async (scenarioId: string, speedMultiplier = 1.0) => {
    set({ buildingHealed: false, remediatedScenario: null });
    await fetch("/api/admin/inject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_id: scenarioId, speed_multiplier: speedMultiplier }),
    });
  },

  resetDemo: async () => {
    const res = await fetch("/api/admin/reset", { method: "POST" });
    const data = await res.json();
    set({
      activeScenario: null,
      buildingHealed: false,
      remediatedScenario: null,
      injectedEvents: [],
      agentSteps: [],
      stagedHitlActions: [],
      lastResetTs: data.last_reset_ts,
      lastResetLatencyMs: data.reset_latency_ms,
      rootCauseModalOpen: false,
      entityDrawerOpen: false,
    });
  },

  decideHitlAction: async (actionId: string, decision: "APPROVE" | "REJECT") => {
    const res = await fetch("/api/hitl/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId, decision }),
    });
    if (res.ok) {
      const updated = await res.json();
      set((state) => ({
        buildingHealed: updated.building_healed ? true : state.buildingHealed,
        remediatedScenario: updated.building_healed ? (state.activeScenario || "SCN-1") : state.remediatedScenario,
        activeScenario: updated.building_healed ? null : state.activeScenario,
        injectedEvents: updated.building_healed ? [] : state.injectedEvents,
        agentSteps: updated.verification_step
          ? [
              updated.verification_step,
              ...state.agentSteps.filter((s) => s.otel_span_id !== updated.verification_step.otel_span_id),
            ]
          : state.agentSteps,
        stagedHitlActions: state.stagedHitlActions.map((a) =>
          a.action_id === updated.action_id ? { ...a, ...updated } : a
        ),
      }));
    }
  },

  analyzeNodeWithAgent: async (nodeId, mode = "GRAPH_AUDIT") => {
    const res = await fetch("/api/agent/analyze-node", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node_id: nodeId, analysis_mode: mode }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.agent_step) {
        set((state) => ({
          selectedNodeId: nodeId,
          agentSteps: [
            data.agent_step,
            ...state.agentSteps.filter((s) => s.otel_span_id !== data.agent_step.otel_span_id),
          ],
        }));
      }
    }
  },

  askBuildingQuestion: async (siteId, selectedNodeId, question) => {
    const res = await fetch("/api/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        site_id: siteId,
        selected_node_id: selectedNodeId,
        question,
      }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.agent_step) {
        set((state) => ({
          agentSteps: [
            data.agent_step,
            ...state.agentSteps.filter((s) => s.otel_span_id !== data.agent_step.otel_span_id),
          ],
        }));
      }
    }
  },

  connectSseStream: () => {
    const es = new EventSource("/api/events/stream");

    es.addEventListener("INIT_STATE", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      set({
        activeScenario: data.active_scenario,
        buildingHealed: Boolean(data.building_healed),
        remediatedScenario: data.remediated_scenario || null,
        injectedEvents: data.injected_events || [],
        agentSteps: data.agent_reasoning_steps || [],
        stagedHitlActions: data.staged_hitl_actions || [],
        lastResetTs: data.last_reset_ts || null,
      });
    });

    es.addEventListener("SCENARIO_WAVE", (e: MessageEvent) => {
      const msg = JSON.parse(e.data);
      const payload = msg.payload || {};
      set((state) => ({
        buildingHealed: false,
        remediatedScenario: null,
        activeScenario: payload.scenario_id || state.activeScenario,
        injectedEvents: [...state.injectedEvents, ...(payload.events || [])],
        agentSteps: payload.agent_action
          ? [payload.agent_action, ...state.agentSteps]
          : state.agentSteps,
        stagedHitlActions: payload.hitl_proposal
          ? [...state.stagedHitlActions, payload.hitl_proposal]
          : state.stagedHitlActions,
      }));
    });

    es.addEventListener("AGENT_INSPECTION", (e: MessageEvent) => {
      const msg = JSON.parse(e.data);
      const payload = msg.payload || {};
      if (payload.agent_action) {
        set((state) => ({
          agentSteps: [
            payload.agent_action,
            ...state.agentSteps.filter(
              (s) => s.otel_span_id !== payload.agent_action.otel_span_id
            ),
          ],
        }));
      }
    });

    es.addEventListener("DEMO_RESET", (e: MessageEvent) => {
      const msg = JSON.parse(e.data);
      const payload = msg.payload || {};
      set({
        activeScenario: null,
        buildingHealed: false,
        remediatedScenario: null,
        injectedEvents: [],
        agentSteps: [],
        stagedHitlActions: [],
        lastResetTs: payload.last_reset_ts || null,
        lastResetLatencyMs: payload.reset_latency_ms || null,
        rootCauseModalOpen: false,
        entityDrawerOpen: false,
      });
    });

    es.addEventListener("HITL_DECISION", (e: MessageEvent) => {
      const msg = JSON.parse(e.data);
      const updated = msg.payload || {};
      set((state) => ({
        buildingHealed: updated.building_healed ? true : state.buildingHealed,
        remediatedScenario: updated.building_healed
          ? state.activeScenario || "SCN-1"
          : state.remediatedScenario,
        activeScenario: updated.building_healed ? null : state.activeScenario,
        injectedEvents: updated.building_healed ? [] : state.injectedEvents,
        agentSteps: updated.verification_step
          ? [
              updated.verification_step,
              ...state.agentSteps.filter(
                (s) => s.otel_span_id !== updated.verification_step.otel_span_id
              ),
            ]
          : state.agentSteps,
        stagedHitlActions: state.stagedHitlActions.map((a) =>
          a.action_id === updated.action_id ? { ...a, ...updated } : a
        ),
      }));
    });

    return () => es.close();
  },
}));
