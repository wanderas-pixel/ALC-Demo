import React, { useState, useEffect } from "react";
import { Shield, Lock, User, LogOut, Terminal, Building2, AlertCircle } from "lucide-react";
import { useCockpitStore } from "../store/useCockpitStore";

interface PortalAuthGateProps {
  portal: "cockpit" | "admin";
  children: React.ReactNode;
}

interface AuthSession {
  authenticated: boolean;
  portal: "cockpit" | "admin";
  username: string;
  role: string;
}

export default function PortalAuthGate({ portal, children }: PortalAuthGateProps) {
  const storageKey = `acme_portal_auth_${portal}`;
  const connectSseStream = useCockpitStore((s) => s.connectSseStream);

  const [session, setSession] = useState<AuthSession | null>(() => {
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (saved) {
        const parsed = JSON.parse(saved) as AuthSession;
        if (parsed?.authenticated && parsed?.portal === portal) {
          return parsed;
        }
      }
    } catch {
      // Ignore malformed sessionStorage
    }
    return null;
  });

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!session?.authenticated) return;
    const disconnect = connectSseStream();
    return () => disconnect();
  }, [session?.authenticated, connectSseStream]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          portal,
          username: username.trim(),
          password,
        }),
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || "Invalid username or password");
      }

      const data = (await res.json()) as AuthSession;
      sessionStorage.setItem(storageKey, JSON.stringify(data));
      setSession(data);
      setPassword("");
    } catch (err: any) {
      setError(err?.message || "Authentication failed. Please verify your credentials.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSignOut = () => {
    sessionStorage.removeItem(storageKey);
    setSession(null);
    setUsername("");
    setPassword("");
    setError(null);
  };

  if (session?.authenticated) {
    return (
      <div className="relative min-h-screen bg-slate-950">
        {/* Compact floating session bar in bottom-left so it never overlaps top headers */}
        <div className="fixed bottom-3 left-3 z-50 flex items-center gap-2.5 bg-slate-900/95 backdrop-blur border border-slate-700/80 rounded-full px-3 py-1.5 shadow-lg text-xs text-slate-300">
          <span
            className={`w-2 h-2 rounded-full ${
              portal === "admin" ? "bg-amber-400" : "bg-emerald-400"
            }`}
          />
          <span className="font-mono text-slate-200">{session.username}</span>
          <span className="text-slate-500">•</span>
          <span className="text-slate-400">{session.role}</span>
          <button
            onClick={handleSignOut}
            title="Sign out of portal"
            className="ml-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-800 hover:bg-rose-950/80 hover:text-rose-200 border border-slate-700 hover:border-rose-700/60 text-slate-300 transition"
          >
            <LogOut className="w-3 h-3" />
            Sign Out
          </button>
        </div>
        {children}
      </div>
    );
  }

  const isAdmin = portal === "admin";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-center items-center p-6 relative overflow-hidden">
      {/* Subtle background grid glow */}
      <div
        className={`pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[680px] h-[340px] rounded-full blur-3xl opacity-20 ${
          isAdmin ? "bg-amber-500" : "bg-sky-500"
        }`}
      />

      <div className="w-full max-w-md bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-2xl shadow-2xl overflow-hidden z-10">
        {/* Header Banner */}
        <div
          className={`px-6 py-5 border-b border-slate-800 ${
            isAdmin
              ? "bg-gradient-to-r from-amber-950/60 via-slate-900 to-slate-900"
              : "bg-gradient-to-r from-sky-950/60 via-slate-900 to-slate-900"
          }`}
        >
          <div className="flex items-center gap-3">
            <div
              className={`p-2.5 rounded-xl border ${
                isAdmin
                  ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                  : "bg-sky-500/10 border-sky-500/30 text-sky-400"
              }`}
            >
              {isAdmin ? <Terminal className="w-6 h-6" /> : <Building2 className="w-6 h-6" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                  ACME Co. • Agent Platform
                </span>
                <span
                  className={`text-[11px] font-mono uppercase tracking-wider px-2 py-0.5 rounded border ${
                    isAdmin
                      ? "bg-amber-950/70 text-amber-300 border-amber-700/60"
                      : "bg-emerald-950/70 text-emerald-300 border-emerald-700/60"
                  }`}
                >
                  {isAdmin ? "/admin" : "/"}
                </span>
              </div>
              <h1 className="text-lg font-bold tracking-tight text-white mt-1.5">
                {isAdmin
                  ? "Companion Demo Director Portal"
                  : "Autonomous Building Operations Cockpit"}
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                {isAdmin
                  ? "Authorized Demo Director credentials required for scenario injection & reset"
                  : "Sign in to access live Brick v1.4 digital twin, BAS telemetry & ADK 2.0 Co-Pilot"}
              </p>
            </div>
          </div>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4" autoComplete="off">
          {error && (
            <div className="flex items-center gap-2.5 p-3 rounded-lg bg-rose-950/60 border border-rose-700/70 text-xs text-rose-200">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Portal Username
            </label>
            <div className="relative">
              <User className="w-4 h-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                required
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={isAdmin ? "Enter admin username" : "Enter operator username"}
                className="w-full pl-10 pr-3.5 py-2.5 text-sm bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Password
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-10 pr-3.5 py-2.5 text-sm bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className={`w-full py-2.5 px-4 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition shadow-md disabled:opacity-50 ${
              isAdmin
                ? "bg-amber-500 hover:bg-amber-400 text-slate-950"
                : "bg-sky-500 hover:bg-sky-400 text-slate-950"
            }`}
          >
            <Shield className="w-4 h-4" />
            {submitting
              ? "Verifying Credentials..."
              : isAdmin
              ? "Unlock Demo Director (/admin)"
              : "Unlock Operations Cockpit (/)"}
          </button>
        </form>

        {/* Footer Security Badge */}
        <div className="px-6 py-3 bg-slate-950/80 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
          <span>Agent Gateway • Zero-Trust Access Gate</span>
          <span className="font-mono">Gemini 3.8 Flash • ADK 2.0</span>
        </div>
      </div>
    </div>
  );
}

