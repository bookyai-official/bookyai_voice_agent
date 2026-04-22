"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import Link from "next/link";
import { Plus, Mic2, Settings2 } from "lucide-react";

export default function Dashboard() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAgents();
  }, []);

  const fetchAgents = async () => {
    try {
      const data = await api.agents.list();
      setAgents(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 flex flex-col items-start w-full font-sans">
      <div className="flex w-full justify-between items-center">
        <div>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase">Agents</h1>
          <p className="text-slate-400 mt-1 text-sm font-bold tracking-widest uppercase opacity-60">Manage your ai voice assistants</p>
        </div>
        <Link href="/agents/new">
          <Button className="bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-500/20 h-11 px-8 rounded-xl text-xs font-black uppercase tracking-[0.2em] transition-all active:scale-95">
            <Plus size={18} className="mr-2" />
            New Agent
          </Button>
        </Link>
      </div>

      {loading ? (
        <div className="text-slate-500 font-mono text-xs uppercase tracking-[0.3em] py-12">Loading Agents...</div>
      ) : agents.length === 0 ? (
        <Card className="w-full py-20 flex flex-col items-center justify-center text-center bg-[#111113] border-white/5 shadow-2xl">
          <div className="w-20 h-20 bg-white/5 rounded-full flex items-center justify-center mb-6 text-slate-600">
             <Mic2 size={40} />
          </div>
          <h3 className="text-xl font-black text-white uppercase tracking-tight">No Agents Yet</h3>
          <p className="text-slate-500 max-w-sm mt-3 mb-8 text-sm leading-relaxed">Create your first voice agent to start handling inbound and outbound calls with Realtime Intelligence.</p>
          <Link href="/agents/new">
            <Button className="bg-white text-black hover:bg-slate-200 h-11 px-10 rounded-xl text-xs font-black uppercase tracking-[0.2em]">Create One Now</Button>
          </Link>
        </Card>
      ) : (
        <div className="w-full bg-[#111113] border border-white/5 rounded-2xl overflow-hidden shadow-2xl">
          <div className="grid grid-cols-12 gap-4 px-8 py-5 bg-white/[0.02] border-b border-white/5 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">
            <div className="col-span-4">Agent Name</div>
            <div className="col-span-2">Voice Model</div>
            <div className="col-span-2 text-center">Tools</div>
            <div className="col-span-2 text-center">Status</div>
            <div className="col-span-2 text-right">Settings</div>
          </div>
          <div className="divide-y divide-white/5">
            {agents.map((agent) => (
              <div key={agent.id} className="grid grid-cols-12 gap-4 px-8 py-6 items-center hover:bg-white/[0.03] transition-all group">
                <div className="col-span-4">
                  <div className="font-black text-white text-sm tracking-tight group-hover:text-blue-400 transition-colors">{agent.name}</div>
                  <div className="text-[9px] font-mono text-slate-600 mt-1 uppercase tracking-tighter">ID: {String(agent.id).slice(0, 12)}...</div>
                </div>
                <div className="col-span-2 text-xs font-bold text-slate-400 capitalize">
                  <span className="flex items-center">
                    <Mic2 size={12} className="mr-2 text-blue-500/50" />
                    {agent.voice}
                  </span>
                </div>
                <div className="col-span-2 text-center text-xs font-mono text-slate-500">
                  <span className="bg-white/5 px-2 py-1 rounded text-blue-400">
                    {agent.tools?.length || 0} Tools
                  </span>
                </div>
                <div className="col-span-2 flex justify-center">
                  <div className={`px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest border ${
                    agent.active 
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
                      : 'bg-slate-500/10 text-slate-500 border-white/5'
                  }`}>
                    {agent.active ? 'Online' : 'Offline'}
                  </div>
                </div>
                <div className="col-span-2 text-right">
                  <Link href={`/agents/${agent.id}`}>
                    <Button variant="ghost" className="text-slate-400 hover:text-white hover:bg-white/5 h-9 px-4 rounded-lg text-[10px] font-black uppercase tracking-widest border border-white/5">
                      <Settings2 size={14} className="mr-2" />
                      Settings
                    </Button>
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
