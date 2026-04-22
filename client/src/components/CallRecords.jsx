"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card } from "./ui/Card";
import { Button } from "./ui/Button";
import { 
  Phone, Clock, MessageSquare, ChevronDown, ChevronUp, User, 
  Bot, Coins, Headphones, Globe, Smartphone, ArrowUpRight, 
  ArrowDownLeft, FileText, Activity 
} from "lucide-react";

export function CallRecords({ agentId }) {
  const [calls, setCalls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedCall, setExpandedCall] = useState(null);

  useEffect(() => {
    fetchCalls();
  }, [agentId]);

  const fetchCalls = async () => {
    try {
      const data = await api.calls.list(agentId);
      setCalls(data);
    } catch (err) {
      console.error("Failed to fetch calls:", err);
    } finally {
      setLoading(false);
    }
  };

  const toggleExpand = (callId) => {
    setExpandedCall(expandedCall === callId ? null : callId);
  };

  if (loading) return <div className="py-12 text-center text-slate-400 font-medium">Loading call history...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between px-1">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Call History</h2>
          <p className="text-xs text-slate-500 mt-0.5">Records of all AI interactions</p>
        </div>
        <Button variant="ghost" className="h-9 text-xs font-semibold bg-slate-100 hover:bg-slate-200" onClick={fetchCalls}>
          Refresh Logs
        </Button>
      </div>

      {calls.length === 0 ? (
        <Card className="p-16 text-center text-slate-400 border-dashed bg-slate-50/50">
          <div className="bg-white w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 shadow-sm">
            <Phone className="text-slate-300" size={28} />
          </div>
          <p className="font-medium">No call records yet.</p>
          <p className="text-xs mt-1">Start a call to see logs here.</p>
        </Card>
      ) : (
        <div className="space-y-4">
          {calls.map((call) => (
            <div key={call.id} className={`group transition-all duration-300 ${expandedCall === call.id ? 'ring-2 ring-blue-500/20 rounded-2xl' : ''}`}>
              <Card className={`p-0 overflow-hidden border-slate-200 transition-all duration-300 ${expandedCall === call.id ? 'shadow-lg border-blue-200' : 'hover:border-slate-300 hover:shadow-md'}`}>
                <div 
                  className={`p-5 flex items-center justify-between cursor-pointer transition-colors ${expandedCall === call.id ? 'bg-blue-50/30' : 'bg-white'}`}
                  onClick={() => toggleExpand(call.id)}
                >
                  <div className="flex items-center space-x-5">
                    {/* Direction Icon */}
                    <div className={`w-11 h-11 rounded-2xl flex items-center justify-center shadow-sm ${
                      call.call_type === 'inbound' 
                        ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' 
                        : 'bg-indigo-50 text-indigo-600 border border-indigo-100'
                    }`}>
                      {call.call_type === 'inbound' ? <ArrowDownLeft size={22} /> : <ArrowUpRight size={22} />}
                    </div>
                    
                    <div>
                      <div className="flex items-center space-x-3 mb-1">
                         <p className="font-bold text-slate-900 tracking-tight">{call.from_number || "Anonymous"}</p>
                         <div className={`flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${
                           call.call_mode === 'web' 
                             ? 'bg-sky-50 text-sky-600 border-sky-100' 
                             : 'bg-purple-50 text-purple-600 border-purple-100'
                         }`}>
                           {call.call_mode === 'web' ? <Globe size={10} className="mr-1" /> : <Smartphone size={10} className="mr-1" />}
                           {call.call_mode || 'Phone'}
                         </div>
                      </div>
                      <div className="flex items-center text-[11px] text-slate-400 font-medium">
                        <Clock size={12} className="mr-1.5" />
                        {new Date(call.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-8">
                    <div className="text-right hidden md:block">
                      <div className="flex items-center justify-end space-x-2 mb-1">
                        <span className={`h-2 w-2 rounded-full ${call.status === 'completed' ? 'bg-emerald-500' : 'bg-amber-500'}`}></span>
                        <p className={`text-[10px] font-black uppercase tracking-widest ${call.status === 'completed' ? 'text-emerald-600' : 'text-amber-600'}`}>
                          {call.status}
                        </p>
                      </div>
                      <div className="flex items-center justify-end text-[11px] text-slate-500 font-mono">
                        <Activity size={12} className="mr-1.5 opacity-40" />
                        <span>{Math.floor((new Date(call.updated_at) - new Date(call.created_at)) / 1000)}s duration</span>
                      </div>
                    </div>
                    
                    <div className={`p-2 rounded-full transition-colors ${expandedCall === call.id ? 'bg-blue-100 text-blue-600' : 'text-slate-300 group-hover:text-slate-400 group-hover:bg-slate-100'}`}>
                      {expandedCall === call.id ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                    </div>
                  </div>
                </div>

                {expandedCall === call.id && (
                  <div className="bg-white border-t border-slate-100 animate-in slide-in-from-top-4 duration-300">
                    <div className="p-6 space-y-8">
                      
                      {/* Summary Section */}
                      {call.call_summary && (
                        <div className="bg-slate-50 rounded-2xl p-5 border border-slate-100 relative overflow-hidden group/summary">
                          <div className="absolute top-0 right-0 p-3 opacity-10 group-hover/summary:opacity-20 transition-opacity">
                            <FileText size={48} />
                          </div>
                          <h3 className="text-xs font-black text-slate-400 uppercase tracking-[0.2em] mb-3 flex items-center">
                            <Bot size={14} className="mr-2 text-blue-500" />
                            AI Session Summary
                          </h3>
                          <p className="text-sm text-slate-700 leading-relaxed font-medium italic">
                            "{call.call_summary}"
                          </p>
                        </div>
                      )}

                      {/* Stats Grid */}
                      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                        <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block mb-2">Cost / Tokens</span>
                          <div className="flex items-center text-slate-900 font-mono text-lg font-bold">
                            <Coins size={18} className="mr-2 text-amber-500" />
                            {call.total_tokens?.toLocaleString() || 0}
                          </div>
                        </div>
                        <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block mb-2">Input/Cached</span>
                          <div className="flex items-baseline space-x-2">
                            <span className="text-slate-900 font-mono text-lg font-bold">{call.input_tokens?.toLocaleString() || 0}</span>
                            {call.cached_tokens > 0 && (
                              <span className="text-[9px] font-black text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded border border-indigo-100 uppercase">
                                {call.cached_tokens} hit
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block mb-2">Output Generated</span>
                          <span className="text-slate-900 font-mono text-lg font-bold">{call.output_tokens?.toLocaleString() || 0}</span>
                        </div>
                        {call.recording_url ? (
                          <a 
                            href={call.recording_url} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="bg-blue-600 text-white rounded-2xl p-4 flex flex-col justify-center items-center hover:bg-blue-700 transition-all shadow-md shadow-blue-200 group/btn"
                          >
                            <Headphones size={20} className="mb-1 group-hover/btn:scale-110 transition-transform" />
                            <span className="text-[11px] font-bold uppercase tracking-wider">Listen Audio</span>
                          </a>
                        ) : (
                          <div className="bg-slate-50 border border-slate-100 rounded-2xl p-4 flex flex-col justify-center items-center opacity-50 grayscale">
                            <Headphones size={20} className="mb-1 text-slate-400" />
                            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">No Audio</span>
                          </div>
                        )}
                      </div>

                      {/* Transcript Section */}
                      <div>
                        <div className="flex items-center justify-between mb-6">
                          <div className="h-px bg-slate-100 flex-1"></div>
                          <div className="mx-6 flex items-center text-[10px] font-black text-slate-300 uppercase tracking-[0.3em]">
                            <MessageSquare size={14} className="mr-2" />
                            Conversation Transcript
                          </div>
                          <div className="h-px bg-slate-100 flex-1"></div>
                        </div>
                        
                        {call.transcript && call.transcript.length > 0 ? (
                          <div className="space-y-6 max-h-[500px] overflow-y-auto px-2 py-4 custom-scrollbar bg-slate-50/50 rounded-3xl border border-slate-100">
                            {call.transcript.map((msg, idx) => (
                              <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                <div className={`group/msg relative max-w-[80%] ${msg.role === 'user' ? 'items-end' : 'items-start'} flex flex-col`}>
                                  <div className={`mb-1.5 px-1 flex items-center text-[9px] font-black uppercase tracking-widest ${msg.role === 'user' ? 'text-blue-500' : 'text-slate-400'}`}>
                                    {msg.role === 'user' ? (
                                      <>Customer <User size={10} className="ml-1.5" /></>
                                    ) : (
                                      <><Bot size={10} className="mr-1.5" /> AI Assistant</>
                                    )}
                                  </div>
                                  <div className={`px-5 py-3.5 text-sm leading-relaxed shadow-sm transition-all ${
                                    msg.role === 'user' 
                                      ? 'bg-blue-600 text-white rounded-[24px] rounded-tr-none' 
                                      : 'bg-white border border-slate-200 text-slate-800 rounded-[24px] rounded-tl-none'
                                  }`}>
                                    {msg.text}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-center py-12 border-2 border-dashed border-slate-100 rounded-3xl">
                            <p className="text-sm text-slate-400 font-medium">No transcript available for this session.</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </Card>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
