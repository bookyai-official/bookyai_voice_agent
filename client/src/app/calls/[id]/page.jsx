"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { 
  Phone, Clock, MessageSquare, User, Bot, Coins, Headphones, 
  Globe, Smartphone, ArrowUpRight, ArrowDownLeft, FileText, 
  Activity, ArrowLeft, ExternalLink
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

export default function CallDetailPage() {
  const params = useParams();
  const [call, setCall] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCall();
  }, [params.id]);

  const fetchCall = async () => {
    try {
      const data = await api.calls.get(params.id);
      setCall(data);
    } catch (err) {
      console.error("Failed to fetch call detail:", err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div className="p-12 text-center text-slate-400 font-medium">Loading call details...</div>;
  if (!call) return <div className="p-12 text-center text-slate-400 font-medium">Call record not found.</div>;

  const duration = Math.floor((new Date(call.updated_at) - new Date(call.created_at)) / 1000);

  return (
    <div className="max-w-7xl mx-auto space-y-10 pb-20 font-sans">
      {/* Header */}
      <div className="flex items-center space-x-6">
        <Link href="/calls">
          <div className="w-10 h-10 bg-white/5 rounded-xl flex items-center justify-center hover:bg-white/10 transition-colors text-slate-400">
            <ArrowLeft size={20} />
          </div>
        </Link>
        <div>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase">Call Details</h1>
          <p className="text-[10px] text-slate-500 uppercase tracking-[0.3em] font-black mt-2">CALL_ID: {call.call_sid}</p>
        </div>
        <div className="flex-1" />
        <Link href={`/agents/${call.agent_id}`}>
          <Button variant="ghost" className="border border-white/5 hover:bg-white/5 px-6 h-10 rounded-xl">
            View Agent
            <ExternalLink size={14} className="ml-2" />
          </Button>
        </Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-10">
        
        {/* Left Column: Info & Stats */}
        <div className="lg:col-span-1 space-y-8">
          
          {/* Agent Information */}
          <Card className="p-8 bg-[#111113] border-white/5 shadow-2xl rounded-3xl">
            <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.3em] mb-6">Agent Info</h3>
            <div className="flex items-center space-x-5">
              <div className="w-14 h-14 bg-white/5 rounded-2xl flex items-center justify-center text-blue-500 border border-white/5 shadow-inner">
                <Bot size={28} />
              </div>
              <div>
                <p className="font-black text-white text-lg tracking-tight">{call.agent_name}</p>
                <p className="text-[9px] font-mono text-slate-600 uppercase mt-1 tracking-tighter">AGENT_ID: {String(call.agent_id).slice(0, 12)}</p>
              </div>
            </div>
          </Card>

          {/* Call Metadata */}
          <Card className="p-8 bg-[#111113] border-white/5 shadow-2xl rounded-3xl space-y-8">
            <div>
              <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.3em] mb-6">Call Info</h3>
              <div className="space-y-5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Type</span>
                  <div className={`flex items-center px-2.5 py-1 rounded-lg text-[9px] font-black uppercase tracking-widest border ${
                    call.call_type === 'inbound' 
                      ? 'bg-emerald-500/5 border-emerald-500/10 text-emerald-400' 
                      : 'bg-blue-500/5 border-blue-500/10 text-blue-400'
                  }`}>
                    {call.call_type === 'inbound' ? <ArrowDownLeft size={10} className="mr-1.5" /> : <ArrowUpRight size={10} className="mr-1.5" />}
                    {call.call_type}
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Device</span>
                  <div className={`flex items-center px-2.5 py-1 rounded-lg text-[9px] font-black uppercase tracking-widest border bg-white/5 text-slate-400 border-white/5`}>
                    {call.call_mode === 'web' ? <Globe size={10} className="mr-1.5" /> : <Smartphone size={10} className="mr-1.5" />}
                    {call.call_mode || 'Phone'}
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Status</span>
                  <span className={`text-[10px] font-black uppercase tracking-[0.2em] ${call.status === 'completed' ? 'text-emerald-500' : 'text-amber-500'}`}>
                    {call.status}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Duration</span>
                  <div className="flex items-center text-xs font-mono font-black text-slate-300">
                    <Clock size={12} className="mr-2 text-slate-600" />
                    {duration}S
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-8 border-t border-white/5">
              <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.3em] mb-6">Tokens Used</h3>
              <div className="space-y-5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Total Tokens</span>
                  <span className="font-mono text-sm font-black text-blue-400">{call.total_tokens?.toLocaleString() || 0} T</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Input</span>
                  <span className="font-mono text-xs text-slate-500">{call.input_tokens?.toLocaleString() || 0}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Output</span>
                  <span className="font-mono text-xs text-slate-500">{call.output_tokens?.toLocaleString() || 0}</span>
                </div>
                {call.cached_tokens > 0 && (
                  <div className="flex items-center justify-between p-3 bg-blue-500/5 rounded-xl border border-blue-500/10">
                    <span className="text-[10px] font-black text-blue-400 uppercase tracking-widest">Saved</span>
                    <span className="text-[10px] font-black text-blue-400 uppercase">
                      {call.cached_tokens} CACHED
                    </span>
                  </div>
                )}
              </div>
            </div>
          </Card>

          {/* Recording Player */}
          {call.recording_url ? (
            <Card className="p-8 bg-blue-600/5 border-blue-500/10 shadow-2xl rounded-3xl">
              <h3 className="text-[10px] font-black text-blue-400 uppercase tracking-[0.3em] mb-6 flex items-center">
                <Headphones size={14} className="mr-2" />
                Call Recording
              </h3>
              <audio controls className="w-full h-10 brightness-90 contrast-125 invert">
                <source src={call.recording_url} type="audio/mpeg" />
              </audio>
              <a 
                href={call.recording_url} 
                target="_blank" 
                className="block text-center mt-6 text-[10px] font-black text-blue-500 uppercase tracking-widest hover:text-blue-400 transition-colors"
              >
                Download Recording
              </a>
            </Card>
          ) : (
            <Card className="p-10 bg-white/[0.02] border-white/5 flex flex-col items-center justify-center rounded-3xl opacity-50">
              <Headphones size={32} className="text-slate-700 mb-4" />
              <p className="text-[10px] font-black text-slate-600 uppercase tracking-[0.2em]">No Recording Found</p>
            </Card>
          )}

        </div>

        {/* Right Column: Summary & Transcript */}
        <div className="lg:col-span-2 space-y-10">
          
          {/* Summary */}
          {call.call_summary && (
            <Card className="p-10 bg-gradient-to-br from-blue-600/10 to-purple-600/10 border-white/5 shadow-2xl rounded-3xl relative overflow-hidden group/summary">
              <div className="absolute -top-10 -right-10 p-6 opacity-[0.03] group-hover/summary:opacity-[0.06] transition-all duration-700 group-hover/summary:scale-110">
                <FileText size={200} />
              </div>
              <div className="relative">
                <h3 className="text-[10px] font-black text-blue-400 uppercase tracking-[0.4em] mb-6 flex items-center">
                  <Activity size={16} className="mr-3" />
                  Call Summary
                </h3>
                <p className="text-xl text-slate-200 leading-relaxed font-bold italic tracking-tight">
                  "{call.call_summary}"
                </p>
              </div>
            </Card>
          )}

          {/* Transcript */}
          <Card className="p-0 bg-[#111113] border-white/5 shadow-2xl rounded-3xl overflow-hidden">
            <div className="bg-white/[0.02] px-10 py-6 border-b border-white/5 flex items-center justify-between">
              <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.4em] flex items-center">
                <MessageSquare size={16} className="mr-3 text-blue-500" />
                Chat History
              </h3>
              <div className="text-[10px] font-black text-slate-600 uppercase tracking-widest">
                {call.transcript?.length || 0} Messages
              </div>
            </div>
            
            <div className="p-10 space-y-10 max-h-[800px] overflow-y-auto custom-scrollbar">
              {call.transcript && call.transcript.length > 0 ? (
                <div className="space-y-12">
                  {call.transcript.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[85%] flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                        <div className={`mb-3 px-1 flex items-center text-[9px] font-black uppercase tracking-[0.2em] ${msg.role === 'user' ? 'text-blue-400' : 'text-slate-600'}`}>
                          {msg.role === 'user' ? (
                            <>You <User size={10} className="ml-2" /></>
                          ) : (
                            <><Bot size={10} className="mr-2" /> Agent</>
                          )}
                        </div>
                        <div className={`px-6 py-5 text-sm leading-relaxed ${
                          msg.role === 'user' 
                            ? 'bg-blue-600 text-white rounded-3xl rounded-tr-none shadow-xl shadow-blue-600/20 font-bold' 
                            : 'bg-white/5 border border-white/5 text-slate-200 rounded-3xl rounded-tl-none font-medium'
                        }`}>
                          {msg.text}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-24 text-center">
                  <Activity size={48} className="mx-auto text-white/5 mb-6 animate-pulse" />
                  <p className="text-slate-600 font-black uppercase tracking-[0.3em] text-xs">Waiting for chat history...</p>
                </div>
              )}
            </div>
          </Card>

        </div>

      </div>
    </div>
  );
}
