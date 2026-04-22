"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { 
  Phone, ArrowUpRight, ArrowDownLeft, Globe, Smartphone, 
  ExternalLink, Clock, Coins, RefreshCcw 
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export default function GlobalCallRecords() {
  const router = useRouter();
  const [calls, setCalls] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCalls();
  }, []);

  const fetchCalls = async () => {
    setLoading(true);
    try {
      const data = await api.calls.list();
      setCalls(data);
    } catch (err) {
      console.error("Failed to fetch calls:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12 font-sans">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase">Call History</h1>
          <p className="text-slate-500 mt-2 font-bold tracking-widest uppercase text-xs opacity-60">View all calls made by your agents</p>
        </div>
        <Button 
          variant="ghost" 
          onClick={fetchCalls} 
          disabled={loading}
          className="bg-white/5 border border-white/5 shadow-lg text-slate-400 hover:bg-white/10 hover:text-white transition-all h-10 px-6 rounded-xl text-[10px] font-black uppercase tracking-widest"
        >
          <RefreshCcw size={14} className={`mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <Card className="p-0 overflow-hidden border-white/5 shadow-2xl bg-[#111113] rounded-2xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-white/[0.02] border-b border-white/5">
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Call ID</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Agent</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Type</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Status</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Tokens</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Time</th>
                <th className="px-8 py-5 text-right"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {loading ? (
                <tr>
                  <td colSpan="7" className="px-8 py-20 text-center text-slate-500 font-mono text-xs uppercase tracking-[0.3em]">
                    Loading Calls...
                  </td>
                </tr>
              ) : calls.length === 0 ? (
                <tr>
                  <td colSpan="7" className="px-8 py-20 text-center text-slate-500 font-bold uppercase tracking-widest text-xs opacity-50">
                    No calls found.
                  </td>
                </tr>
              ) : (
                calls.map((call) => (
                  <tr 
                    key={call.id} 
                    className="hover:bg-white/[0.03] transition-all group cursor-pointer"
                    onClick={() => router.push(`/calls/${call.id}`)}
                  >
                    <td className="px-8 py-6">
                      <p className="font-mono text-[10px] text-slate-600 truncate max-w-[120px] uppercase tracking-tighter group-hover:text-blue-500 transition-colors">
                        {call.call_sid}
                      </p>
                    </td>
                    <td className="px-8 py-6">
                      <div className="flex flex-col">
                        <span className="font-black text-white text-sm tracking-tight">{call.agent_name || "Unknown Agent"}</span>
                        <span className="text-[9px] font-mono text-slate-600 uppercase mt-0.5 tracking-tighter">AGENT_ID: {String(call.agent_id).slice(0, 12)}</span>
                      </div>
                    </td>
                    <td className="px-8 py-6">
                      <div className="flex items-center space-x-3">
                        <div className={`w-9 h-9 rounded-xl flex items-center justify-center border transition-colors ${
                          call.call_type === 'inbound' 
                            ? 'bg-emerald-500/5 border-emerald-500/10 text-emerald-500 group-hover:bg-emerald-500/10' 
                            : 'bg-blue-500/5 border-blue-500/10 text-blue-500 group-hover:bg-blue-500/10'
                        }`}>
                          {call.call_type === 'inbound' ? <ArrowDownLeft size={16} /> : <ArrowUpRight size={16} />}
                        </div>
                        <div className={`flex items-center px-2.5 py-1 rounded-lg text-[9px] font-black uppercase tracking-widest border ${
                          call.call_mode === 'web' 
                            ? 'bg-white/5 text-blue-400 border-white/5' 
                            : 'bg-white/5 text-purple-400 border-white/5'
                        }`}>
                          {call.call_mode === 'web' ? <Globe size={10} className="mr-1.5" /> : <Smartphone size={10} className="mr-1.5" />}
                          {call.call_mode || 'Phone'}
                        </div>
                      </div>
                    </td>
                    <td className="px-8 py-6">
                      <div className="flex flex-col">
                        <span className={`text-[10px] font-black uppercase tracking-[0.2em] ${
                          call.status === 'completed' ? 'text-emerald-500' : 'text-amber-500'
                        }`}>
                          {call.status}
                        </span>
                        <div className="flex items-center text-[10px] text-slate-600 font-mono mt-1">
                          <Clock size={10} className="mr-1" />
                          {Math.floor((new Date(call.updated_at) - new Date(call.created_at)) / 1000)}s DURATION
                        </div>
                      </div>
                    </td>
                    <td className="px-8 py-6">
                      <div className="flex items-center text-xs font-mono font-black text-slate-300">
                        <Coins size={14} className="mr-2 text-amber-500/50" />
                        {call.total_tokens?.toLocaleString() || 0}
                      </div>
                    </td>
                    <td className="px-8 py-6">
                      <p className="text-[10px] text-slate-400 font-black uppercase tracking-widest">
                        {new Date(call.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                      </p>
                      <p className="text-[10px] text-slate-600 font-mono mt-0.5">
                        {new Date(call.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </td>
                    <td className="px-8 py-6 text-right" onClick={(e) => e.stopPropagation()}>
                      <Link href={`/calls/${call.id}`}>
                        <div className="inline-flex h-9 w-9 items-center justify-center bg-white/5 border border-white/5 rounded-xl text-slate-500 hover:text-white hover:bg-blue-600 hover:border-blue-500 transition-all">
                          <ExternalLink size={14} />
                        </div>
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

