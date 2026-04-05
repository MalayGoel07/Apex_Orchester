import { useEffect, useMemo, useRef, useState } from "react";
import AgentPanel from "./AgentPanel.jsx";
import Topbar from "./Topbar.jsx";

/*Initializing the agent card*/
const AGENT_BLUEPRINT = [
  { id: 1, key: "gemini", name: "Gemini", idleUsage: "Output Quality Checker", status: "idle", startTime: null, endTime: null, duration: null },
  { id: 2, key: "llama3", name: "Llama3:8B", idleUsage: "Waiting for a task", status: "idle", startTime: null, endTime: null, duration: null },
  { id: 3, key: "mistral", name: "Mistral", idleUsage: "Waiting for a task", status: "idle", startTime: null, endTime: null, duration: null },
  { id: 4, key: "deepseek", name: "Deepseek-coder", idleUsage: "Waiting for a task", status: "idle", startTime: null, endTime: null, duration: null },
  { id: 5, key: "phi", name: "Phi", idleUsage: "Fallback agent standby", status: "idle", startTime: null, endTime: null, duration: null },
];

const Dashboard = () => {

  /*Setting status*/
  const [task, setTask] = useState("");
  const [agents, setAgents] = useState(AGENT_BLUEPRINT.map((agent) => ({ ...agent, usage: agent.idleUsage })));
  const [isRunning, setIsRunning] = useState(false);
  const [statusLabel, setStatusLabel] = useState("");
  const [output, setOutput] = useState("");
  const [useQualityCheck, setUseQualityCheck] = useState(false);
  const [geminiQuota, setGeminiQuota] = useState(10);
  const [totalRunTime, setTotalRunTime] = useState(null);
  const [liveElapsed, setLiveElapsed] = useState("0.00");

  /*Gemini use check*/
  const isGeminiAvailable = geminiQuota > 0 && !isRunning;

  /*Check for run*/
  const runRef = useRef(false);
  const runStartedAtRef = useRef(null);
  const resetIdleTimerRef = useRef(null);

  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

  useEffect(() => {
    if (!isRunning || !runStartedAtRef.current) return;
    const timer = window.setInterval(() => {
      const seconds = ((Date.now() - runStartedAtRef.current) / 1000).toFixed(1);
      setLiveElapsed(seconds);
    }, 100);
    return () => window.clearInterval(timer);
  }, [isRunning]);

  useEffect(() => () => {
    if (resetIdleTimerRef.current) {
      window.clearTimeout(resetIdleTimerRef.current);
    }
  }, []);

  /*Agent handling*/
  const setAgentsIdle = () => {
    setAgents(
      AGENT_BLUEPRINT.map((agent) => {
        if (agent.key === "gemini") {
          if (geminiQuota <= 0) {
            return { ...agent, status: "error", usage: "Quota exhausted", startTime: null, endTime: null, duration: null };
          }
          if (useQualityCheck) {
            return { ...agent, status: "idle", usage: "Quality check armed", startTime: null, endTime: null, duration: null };
          }
        }
        return { ...agent, status: "idle", usage: agent.idleUsage, startTime: null, endTime: null, duration: null };
      })
    );
  };
  const setBusyAgent = (busyKey, usage, startAt = Date.now()) => {setAgents((prev) =>prev.map((agent) =>agent.key === busyKey ? { ...agent, status: "busy", usage, startTime: startAt, endTime: null, duration: null } : agent));};

  /*Run task or etcs*/
  const handleRun = async () => {

    const trimmedTask = task.trim(); if (!trimmedTask || isRunning) return;

    const shouldUseGemini = useQualityCheck && geminiQuota > 0;

    const managerStartedAt = Date.now();
    runStartedAtRef.current = managerStartedAt;
    if (resetIdleTimerRef.current) {
      window.clearTimeout(resetIdleTimerRef.current);
      resetIdleTimerRef.current = null;
    }

    setIsRunning(true);
    runRef.current = true;

    setStatusLabel("AI models working on Task!");

    setOutput("");
    setTotalRunTime(null);
    setLiveElapsed("0.00");

    setBusyAgent("llama3", "Classifying task type", managerStartedAt);
    setBusyAgent("deepseek", "Running CODE subtask", managerStartedAt);
    setBusyAgent("mistral", "Running TXT subtask", managerStartedAt);
    if (shouldUseGemini) {setBusyAgent("gemini", "Running quality check", managerStartedAt);}

    try {
      const runtask = await fetch(`${API_BASE_URL}/api/run-task`, {method: "POST",headers: { "Content-Type": "application/json" },body: JSON.stringify({ task: trimmedTask, enable_quality_check: useQualityCheck }),});
      const taskdata = await runtask.json();

      if (typeof taskdata.gemini_quota_remaining === "number") {setGeminiQuota(taskdata.gemini_quota_remaining);}
      setOutput(taskdata?.output || "No output returned.");
      if (!runtask.ok) throw new Error(taskdata?.detail || "Failed to classify task");

      const agents_used = Array.isArray(taskdata?.agents_used) ? taskdata.agents_used : [];
      const fallbackUsed = Boolean(taskdata?.fallback_used);
      const now = Date.now();
      const managerFinishedAt = Date.now();

      setAgents((prevAgents) =>
        prevAgents.map((agent) => {
          if (agent.key !== "llama3") return agent;
          return {...agent,status: "complete",usage: "Routing completed",endTime: managerFinishedAt,duration: null,};
        })
      );

      setAgents((prev) =>
        prev.map((agent) => {
          if (agent.key === "gemini" && shouldUseGemini) {
            return { ...agent, status: "complete", usage: "Quality check applied", endTime: now, duration: null };
          }
          if (agents_used.includes(agent.key)) {
            return {...agent,status: "complete",usage: fallbackUsed ? "Completed via fallback" : "Task completed",endTime: now,duration: null,};
          }
          if (agent.key === "llama3") return agent;
          return { ...agent, status: "idle", usage: agent.idleUsage };
        })
      );

      const selectedLabel = agents_used.length ? ` (${agents_used.join(", ")})` : "";
      setStatusLabel(fallbackUsed ? `Task completed via fallback route${selectedLabel}` : `Task completed${selectedLabel}`);
      if (fallbackUsed) {
        setAgents((prev) =>
          prev.map((agent) => {
            if (agent.key !== "phi") return agent;
            return { ...agent, status: "complete", usage: "Fallback executed", endTime: now, duration: null };
          })
        );
      }

    } catch (error) {

      setOutput(`Error: ${error?.message || "Unknown error while connecting to backend."}`);
      setStatusLabel("Execution failed");
      setAgents((prev) =>prev.map((agent) =>agent.key === "phi" ? { ...agent, status: "error", usage: "Global fallback reported an error" } : { ...agent, status: "idle", usage: agent.idleUsage }));

    } finally {
      const totalSeconds = ((Date.now() - managerStartedAt) / 1000).toFixed(2);
      setTotalRunTime(totalSeconds);

      runRef.current = false;
      runStartedAtRef.current = null;
      setIsRunning(false);
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
        if (geminiQuota <= 0) {
          return { ...agent, status: "error", usage: "Quota exhausted", startTime: null, endTime: null, duration: null };
        }
        if (useQualityCheck) {
          return { ...agent, status: "idle", usage: "Quality check armed", startTime: null, endTime: null, duration: null };
        }
        return { ...agent, status: "idle", usage: "Output Quality Checker", startTime: null, endTime: null, duration: null };
      })
    );
  }, [useQualityCheck, geminiQuota, isRunning]);

  const healthcolor = (health) => {
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

  const handleClearOutput = () => {setOutput("Output cleared");};

  return (
    <div className="relative min-h-screen bg-gradient-to-r from-black via-slate-900 to-black bg-[length:200%_200%] animate-gradient">
      <Topbar />
      <main className="relative z-10 mx-auto flex max-w-7xl flex-col gap-8 px-4 pb-8 pt-24 sm:px-6 lg:px-8 bg-gradient-to-r from-black via-slate-900 to-black bg-[length:200%_200%] animate-gradient">
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
                  <p className={`text-2xl font-semibold ${item.label === "Runtime Health" ? healthcolor(item.value) : ""}`}>{item.value}</p>
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
              <div className="mb-2 flex-1 bg-white/[0.04] backdrop-blur-xl p-3 rounded-[28px] overflow-y-auto text-sm font-mono text-gray-200 whitespace-pre-wrap">{output || "No output yet..."}</div>
              <button onClick={handleClearOutput} className="bg-gradient-to-r from-emerald-500 to-emerald-400 text-black px-4 py-2 rounded-xl text-sm font-medium hover:from-emerald-400 hover:to-emerald-300 hover:-translate-y-1 transition-all duration-200 shadow-lg">Clear Output</button>
            </div>
          </div>
        </section>

        <section className="rounded-[28px] border border-white/10 bg-white/[0.04] p-6 shadow-2xl backdrop-blur-xl">
          <div className="flex-1">
            <label className="block text-sm font-medium text-slate-300 mb-3">Describe your task</label>

            <div className="relative">
              <textarea value={task} onChange={(e) => setTask(e.target.value)} placeholder="e.g., Create a responsive landing page with modern glassmorphism design..." rows={4} className="w-full p-5 rounded-3xl bg-black/50 backdrop-blur-xl border border-white/20 text-white placeholder-slate-500 focus:border-emerald-400/50 focus:ring-2 focus:ring-emerald-400/20 focus:outline-none resize-vertical transition-all duration-200 shadow-2xl min-h-[120px] hover:border-white/30"/>
              <div className="absolute bottom-4 right-4 text-xs text-slate-500">{task.length}/500</div>
            </div>

            <div className="mt-4 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
              <p className="text-xs text-slate-500"> Llama3 manager routes tasks to Deepseek (code) or Mistral (text), with fallback chain support</p>
              <button onClick={handleRun} disabled={!task.trim() || isRunning} className={`px-6 py-3 rounded-xl font-semibold flex items-center gap-2 ${   !task.trim() || isRunning     ? "bg-gray-600 text-gray-400 cursor-not-allowed"     : "bg-green-500 hover:bg-green-600 text-black" }`}>{isRunning ? "Running..." : "Run Task"}</button>
              <label className={`flex items-center gap-3 ${!isGeminiAvailable ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}>

                <div className="relative">
                  <input type="checkbox" className="sr-only peer" checked={useQualityCheck} onChange={(e) => geminiQuota > 0 && setUseQualityCheck(e.target.checked)} disabled={geminiQuota <= 0 || isRunning}/>
                  <div className={`w-11 h-6 rounded-full peer peer-checked:bg-emerald-500 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-full ${!isGeminiAvailable ? "bg-gray-700" : "bg-gray-600"}`}></div>
                </div>

                <span className="text-sm text-slate-300">
                  Gemini Quality Check {useQualityCheck ? `(ON • ${geminiQuota}/10 left)` : "(OFF)"}
                  {!isGeminiAvailable && geminiQuota === 0 && (<span className="ml-2 text-xs text-red-400">• Quota exhausted</span>)}
                </span>

              </label>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};

export default Dashboard;
