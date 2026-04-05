import { useEffect, useState } from "react";
import Dashboard from "./Dashboard.jsx";

import "./app.css";
import { Link, Route, Routes } from "react-router-dom";
import Login from "./Login.jsx";
import Signup from "./Signup.jsx";

const TASK_REFRESH_MS = 2000;

function HomePage() {
  const [data, setData] = useState("");

  useEffect(() => {
    const loadTask = async () => {
      try {
        const res = await fetch("http://127.0.0.1:8000/api/task");
        const nextData = await res.json();
        setData(nextData.task);
      } catch (error) {
        console.error("Failed to refresh task", error);
      }
    };
    loadTask();
    const intervalId = window.setInterval(loadTask, TASK_REFRESH_MS);
    return () => window.clearInterval(intervalId);
  }, []);

  const features = [
    {
      title: "Task Decomposition",
      desc: "Automatically break complex problems into structured subtasks.",
    },
    {
      title: "Multi-Agent Execution",
      desc: "Assign specialized AI agents to each step dynamically.",
    },
    {
      title: "Smart Orchestration",
      desc: "Merge outputs into a single intelligent result.",
    },
  ];

  return (
    <div className="relative min-h-screen text-white px-6 py-10 bg-gradient-to-r from-black via-slate-900 to-black bg-[length:200%_200%] animate-gradient">
      <div className="absolute inset-0 bg-gradient-to-tr from-emerald-500/10 via-transparent to-purple-500/10 blur-3xl pointer-events-none"></div>
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-end items-center">
          <div className="flex gap-2">
            <Link to="/login" className="border border-white/10 px-5 py-2 rounded-xl hover:bg-white/5 hover:translate-y-[-5px] transition">Login</Link>
            <Link to="/signup" className="bg-emerald-400 text-black px-5 py-2 rounded-xl font-medium hover:bg-emerald-300 hover:translate-y-[-5px] transition">Sign Up</Link>
          </div>
        </div>
        <div className="text-center">
          <p className="text-sm text-emerald-400 mb-4">Multi-Agent Management Orchestration</p>
          <h1 className="text-4xl sm:text-6xl font-bold tracking-tight">Build with</h1>
          <p className="text-xl sm:text-2xl text-gray-400 mt-2">Coordinated Management System</p>
          <p className="mt-6 text-slate-400 max-w-xl mx-auto">Apex transforms complex workflows into structured pipelines —assign agents, orchestrate execution, and get unified results.</p>

          <div className="mt-8 flex justify-center gap-4 flex-wrap">
            <Link to="/dashboard" className="bg-emerald-400 text-black px-6 py-3 rounded-xl font-medium hover:bg-emerald-300 transform hover:translate-y-1 transition">Get Started</Link>
            <Link to="/dashboard" className="border border-white/10 px-6 py-3 rounded-xl hover:bg-white/5 hover:translate-y-1 transition">Live Demo</Link>
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-6 mt-16">
          {features.map((f) => (
            <div key={f.title} className="p-6 rounded-2xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] hover:translate-y-[-10px] transition">
              <h3 className="text-lg font-semibold text-emerald-300">{f.title}</h3>
              <p className="text-sm text-slate-400 mt-3">{f.desc}</p>
            </div>
          ))}
        </div>

        <div className="mt-16">
          <div className="rounded-3xl border border-white/10 bg-white/[0.03] backdrop-blur-xl p-6 shadow-2xl">
            <div className="flex justify-between items-center border-b border-white/10 pb-4">
              <div>
                <p className="text-xs text-slate-400">System Status</p>
                <h3 className="text-lg font-semibold">Agent Console</h3>
              </div>
              <span className="text-xs px-3 py-1 rounded-full bg-emerald-400/10 text-emerald-300 border border-emerald-400/30">Online</span>
            </div>

            <div className="mt-6 space-y-4">
              <div className="p-4 rounded-xl bg-black/40 border border-white/10">
                <p className="text-xs text-emerald-300 mb-2">Current Execution</p>
                <p className="text-sm text-white">{data || "Waiting for orchestrator..."}</p>
              </div>
            </div>
          </div>
        </div>

        <section className="text-center mt-20">
          <h2 className="text-3xl font-semibold">Start building with intelligent systems</h2>
          <p className="text-slate-400 mt-4">Apex is designed for developers who think beyond single-model AI.</p>
        </section>
      </div>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/dashboard" element={<Dashboard />} />
    </Routes>
  );
}

export default App;
