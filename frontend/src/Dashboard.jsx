import { useEffect, useMemo, useRef, useState } from "react";
import AgentPanel from "./AgentPanel.jsx";
import Topbar from "./Topbar.jsx";

const AGENT_BLUEPRINT = [
  { id: 1, key: "llama3", name: "Head Agent", idleUsage: "Classifies and routes tasks" },
  { id: 2, key: "deepseek", name: "DeepSeek Coder", idleUsage: "Handles code tasks" },
  { id: 3, key: "mistral", name: "Mistral", idleUsage: "Handles text tasks" },
  { id: 4, key: "phi", name: "Phi", idleUsage: "Fallback agent standby" },
  { id: 5, key: "gemini", name: "Gemini", idleUsage: "Optional quality check" },
];

const Dashboard = () => {
  const [task, setTask] = useState("");
const [agents, setAgents] = useState(AGENT_BLUEPRINT.map((a) => ({ ...a, status: "idle", usage: a.idleUsage, startTime: null, endTime: null, duration: null })));


  const [isRunning, setIsRunning] = useState(false);
  const [statusLabel, setStatusLabel] = useState("");
  const [output, setOutput] = useState("");
  const [useQualityCheck, setUseQualityCheck] = useState(false);
  const [geminiQuota, setGeminiQuota] = useState(10);
  const [totalRunTime, setTotalRunTime] = useState(null);
  const [liveElapsed, setLiveElapsed] = useState("0.00");
  const [classification, setClassification] = useState("Not yet classified");

  const runStartedAtRef = useRef(null);
  const resetIdleTimerRef = useRef(null);
  const abortControllerRef = useRef(null);
  const requestIdRef = useRef(null);

  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
  const isGeminiAvailable = geminiQuota > 0 && !isRunning;

  const delay = (ms) => new Promise((res) => setTimeout(res, ms));

  useEffect(() => {
    if (!isRunning || !runStartedAtRef.current) return;
    const timer = setInterval(() => {
      const seconds = ((Date.now() - runStartedAtRef.current) / 1000).toFixed(1);
      setLiveElapsed(seconds);
    }, 100);
    return () => clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    return () => {
      if (resetIdleTimerRef.current) clearTimeout(resetIdleTimerRef.current);
      if (abortControllerRef.current) abortControllerRef.current.abort();
    };
  }, []);

  const setAgentsIdle = () => {
    setAgents((prev) =>
      prev.map((agent) => {
        if (agent.key === "gemini") {
          if (geminiQuota <= 0) return { ...agent, status: "error", usage: "Quota exhausted" };
          if (useQualityCheck) return { ...agent, status: "idle", usage: "Quality check armed" };
        }
        return { ...agent, status: "idle", usage: agent.idleUsage, startTime: null, endTime: null, duration: null };
      })
    );
  };

  const setBusyAgent = (key, usage, startAt = Date.now()) => {
    setAgents((prev) => prev.map((a) => a.key === key ? { ...a, status: "busy", usage, startTime: startAt, endTime: null, duration: null } : a));
  };

  const updateAgentsFromResponse = (taskdata, now) => {
    const { agents_used = [], fallback_used = false, classification: cls } = taskdata;

    setAgents((prev) =>
      prev.map((agent) => {
        if (agent.key === "llama3") {
          const duration = agent.startTime ? ((now - agent.startTime) / 1000).toFixed(2) : null;
          return { ...agent, status: "complete", usage: `Classified: ${cls || "Unknown"}`, endTime: now, duration };
        }
        if (agent.key === "gemini") {
          if (useQualityCheck && geminiQuota > 0) {
            return { ...agent, status: "complete", usage: "Quality check complete", endTime: now };
          }
          return { ...agent, status: "idle", usage: agent.idleUsage };
        }
        if (agents_used.includes(agent.key)) {
          const duration = agent.startTime ? ((now - agent.startTime) / 1000).toFixed(2) : null;
          return { ...agent, status: "complete", usage: fallback_used && agent.key === "phi" ? "Fallback executed" : "Task completed", endTime: now, duration };
        }
        return { ...agent, status: "idle", usage: agent.idleUsage };
      })
    );
  };

  const streamOutput = async (text) => {
    setOutput("");
    const words = text.split(" ");
    for (let i = 0; i < words.length; i++) {
      setOutput((prev) => prev + words[i] + " ");
      await delay(10);
    }
  };

  const handleRun = async () => {
    const trimmedTask = task.trim();
    if (!trimmedTask || isRunning) return;

    if (abortControllerRef.current) abortControllerRef.current.abort();
    abortControllerRef.current = new AbortController();

    const reqId = Date.now();
    requestIdRef.current = reqId;

    const start = Date.now();
    runStartedAtRef.current = start;

    if (resetIdleTimerRef.current) clearTimeout(resetIdleTimerRef.current);

    setIsRunning(true);
    setStatusLabel("AI models working on task...");
    setOutput("");
    setTotalRunTime(null);
    setLiveElapsed("0.00");
    setClassification("Classifying...");

    setBusyAgent("llama3", "Classifying...", start);
    await delay(300);
    setBusyAgent("llama3", "Routing to agents...");

    try {
      const response = await fetch(`${API_BASE_URL}/api/run-task`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task: trimmedTask, enable_quality_check: useQualityCheck }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${response.status}`);
      }

      const data = await response.json();

      if (requestIdRef.current !== reqId) return;
      setClassification(data.classification || "Unknown");
      if (typeof data.gemini_quota_remaining === "number") {setGeminiQuota(data.gemini_quota_remaining);}

      await streamOutput(data.output || "No output returned.");
      updateAgentsFromResponse(data, Date.now());

      const agentsUsed = data.agents_used || [];
      const label = agentsUsed.length ? ` (${agentsUsed.join(", ")})` : "";

      setStatusLabel(
        data.fallback_used ? `Task completed via fallback${label}` : `Task completed${label}`);
    } catch (error) {
      if (error.name === "AbortError") {
        setStatusLabel("Request cancelled");
        return;
      }

      setOutput(`❌ Error: ${error.message || "Unknown error"}`);
      setStatusLabel("Execution failed");
      setAgents((prev) => prev.map((a) => a.key === "phi" ? { ...a, status: "error", usage: "Fallback triggered" } : { ...a, status: "idle", usage: a.idleUsage }));
    } finally {
      const total = ((Date.now() - start) / 1000).toFixed(2);
      setTotalRunTime(total);
      setIsRunning(false);
      runStartedAtRef.current = null;

      resetIdleTimerRef.current = setTimeout(() => {
        setAgentsIdle();
        resetIdleTimerRef.current = null;
      }, 5000);
    }
  };

  useEffect(() => {
    if (isRunning) return;
    setAgents((prev) =>
      prev.map((agent) => {
        if (agent.key !== "gemini") return agent;
        if (geminiQuota <= 0) return { ...agent, status: "error", usage: "Quota exhausted" };
        if (useQualityCheck) return { ...agent, status: "idle", usage: "Quality check armed" };
        return { ...agent, status: "idle", usage: agent.idleUsage };
      })
    );
  }, [useQualityCheck, geminiQuota, isRunning]);

  const healthColor = (health) => {
    const h = Number(String(health).replace("%", ""));
    if (h > 75) return "text-green-400";
    if (h > 40) return "text-yellow-400";
    return "text-red-400";
  };

  const metrics = useMemo(() => {
    const total = agents.length;
    const busy = agents.filter((a) => a.status === "busy").length;
    const health = total === 0 ? 100 : (((total - busy) / total) * 100).toFixed(2);
    return [
      { label: "Active Agents", value: busy, detail: "Currently processing" },
      { label: "Queue Depth", value: isRunning ? "1" : "0", detail: task.trim() ? "Task ready" : "No tasks" },
      { label: "Runtime Health", value: `${health}%`, detail: isRunning ? "Execution in progress" : "Stable" },
    ];
  }, [agents, isRunning, task]);

  const handleClearOutput = () => setOutput("Output cleared");

  return (
    <div className="relative min-h-screen bg-gradient-to-r from-black via-slate-900 to-black bg-[length:200%_200%] animate-gradient">
      <Topbar />
      <main className="relative z-10 mx-auto flex max-w-7xl flex-col gap-8 px-4 pb-8 pt-24 sm:px-6 lg:px-8">
        <section className="rounded-[28px] border border-white/10 bg-white/[0.04] p-6 shadow-2xl backdrop-blur-xl">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-4xl font-semibold">Multi-Agent Dashboard 🚀</h1>
              <p className="mt-2 text-slate-300">Run multiple AI agents in parallel</p>
            </div>
            <div className="grid w-full gap-3 sm:grid-cols-3 lg:max-w-xl rounded-[28px] border border-white/10 bg-white/[0.04] p-6 shadow-2xl backdrop-blur-xl">
              {metrics.map((item) => (
                <div key={item.label} className="rounded-2xl border border-white/10 p-4">
                  <p className="text-xs text-slate-400">{item.label}</p>
                  <p className={`text-2xl font-semibold ${item.label === "Runtime Health" ? healthColor(item.value) : ""}`}>{item.value}</p>
                  <p className="text-xs text-slate-400">{item.detail}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="flex gap-5">
          <aside className="w-[400px]"><AgentPanel agents={agents} /></aside>
          <div className="flex-1">
            <div className="bg-white/[0.04] backdrop-blur-xl border border-zinc-700 rounded-xl p-4 h-[430px] flex flex-col">
              <div className="flex justify-between mb-3">
                <h3 className="font-semibold">Output</h3>
                <span className="text-sm text-gray-400">
                  {isRunning ? statusLabel || "Running..." : "Ready"}
                  {isRunning ? ` • Total: ${liveElapsed}s` : ""}
                  {!isRunning && totalRunTime ? ` • Total: ${totalRunTime}s` : ""}
                </span>
              </div>

              {!isRunning && classification !== "Not yet classified" && (
                <div className="mb-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs inline-block">
                  🎯 Task Type: <strong>{classification}</strong>
                </div>
              )}

              <div className="mb-2 flex-1 bg-white/[0.04] backdrop-blur-xl p-3 rounded-[28px] overflow-y-auto text-sm font-mono text-gray-200 whitespace-pre-wrap">
                {output || "No output yet..."}
              </div>
              <button onClick={handleClearOutput} className="bg-gradient-to-r from-emerald-500 to-emerald-400 text-black px-4 py-2 rounded-xl text-sm font-medium hover:from-emerald-400 hover:to-emerald-300 hover:-translate-y-1 transition-all duration-200 shadow-lg">
                Clear Output
              </button>
            </div>
          </div>
        </section>

        <section className="rounded-[28px] border border-white/10 bg-white/[0.04] p-6 shadow-2xl backdrop-blur-xl">
          <div className="flex-1">
            <label className="block text-sm font-medium text-slate-300 mb-3">Describe your task</label>
            <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={4} className="w-full p-5 rounded-3xl bg-black/50 border border-white/20 text-white" placeholder="Write your task here (text: English)"/>
            <div className="mt-4 flex gap-4">
              <button onClick={handleRun} disabled={!task.trim() || isRunning} className="px-6 py-3 rounded-xl bg-green-500 text-black">
                {isRunning ? "Running..." : "Run Task"}
              </button>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};

export default Dashboard;