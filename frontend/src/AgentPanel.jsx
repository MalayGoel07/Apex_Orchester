const AgentPanel = ({ agents }) => {
  const statusDot = {
    idle: "bg-slate-500",
    busy: "bg-amber-400",
    complete: "bg-emerald-400",
    error: "bg-rose-400",
  };
  const statusText = {
    idle: "text-slate-400",
    busy: "text-amber-300",
    complete: "text-emerald-300",
    error: "text-rose-300",
  };

  return (
    <div className="bg-white/[0.04] backdrop-blur-xl border border-zinc-700 rounded-xl p-4">
      <h3 className="text-lg font-semibold mb-4">Agents</h3>
      <div className="space-y-2">
        {agents.map((agent) => (
          <div key={agent.id} className="flex items-center justify-between p-3 rounded-lg bg-white/[0.04] backdrop-blur-xl">
            <div className="flex items-center gap-3 min-w-0">
              <div className={`w-3 h-3 rounded-full ${statusDot[agent.status]}`}/>
              <div className="min-w-0">
                <p className="truncate">{agent.name}</p>
                <p className="text-xs text-slate-400 truncate">{agent.usage}</p>
              </div>
            </div>
            <div className={`text-sm flex items-center gap-1 capitalize ${statusText[agent.status]}`}>
              ● {agent.status}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default AgentPanel;
