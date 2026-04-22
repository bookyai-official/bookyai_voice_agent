"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { 
  ArrowLeft, Save, Wrench, Plus, Trash2, Pencil, 
  ShieldAlert, ChevronDown, ChevronUp, Globe, 
  Settings, Database, Mic2, MessageSquare, 
  ShieldCheck, Webhook, Boxes, Activity, Zap, Clock, Sparkles
} from "lucide-react";
import { WebCall } from "@/components/WebCall";
import { VoiceSelection } from "@/components/VoiceSelection";
import { useToast } from "@/lib/toast";

const SCHEMA_TEMPLATE = JSON.stringify({
  type: "object",
  properties: {
    param1: {
      type: "string",
      description: "description of the parameter"
    }
  },
  required: ["param1"]
}, null, 2);

export default function AgentDetail() {
  const params = useParams();
  const router = useRouter();
  const { addToast } = useToast();
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [activeAccordion, setActiveAccordion] = useState("functions");
  
  const [agent, setAgent] = useState({
    name: "",
    voice: "alloy",
    system_prompt: "",
    greeting_message: "",
    temperature: 0.8,
    silence_duration_ms: 1000,
    vad_threshold: 0.5,
    active: true,
    tools: []
  });

  // Modal State
  const [showToolModal, setShowToolModal] = useState(false);
  const [editingTool, setEditingTool] = useState(null);
  const [toolForm, setToolForm] = useState({
    name: "",
    description: "",
    tool_type: "webhook",
    url: "",
    tool_target: "",
    method: "POST",
    timeout_seconds: 5,
    json_schema: SCHEMA_TEMPLATE
  });

  useEffect(() => {
    fetchAgent();
  }, [params.id]);

  const fetchAgent = async () => {
    try {
      const data = await api.agents.get(params.id);
      setAgent(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async (e) => {
    e?.preventDefault();
    setSaving(true);
    try {
      const { tools, id, created_at, updated_at, ...updateData } = agent;
      await api.agents.update(params.id, updateData);
      addToast("Agent configuration updated successfully");
    } catch (err) {
      console.error(err);
      addToast("Failed to update agent", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAgent = async () => {
    if (!confirm("Are you sure?")) return;
    setDeleting(true);
    try {
      await api.agents.delete(params.id);
      addToast("Agent removed from studio");
      router.push("/");
    } catch (err) {
      console.error(err);
      addToast("Could not remove agent", "error");
      setDeleting(false);
    }
  };

  const openCreateModal = () => {
    setEditingTool(null);
    setToolForm({
      name: "",
      description: "",
      tool_type: "webhook",
      url: "",
      tool_target: "",
      method: "POST",
      timeout_seconds: 5,
      json_schema: SCHEMA_TEMPLATE
    });
    setShowToolModal(true);
  };

  const openEditModal = (tool) => {
    setEditingTool(tool);
    setToolForm({
      name: tool.name,
      description: tool.description,
      tool_type: tool.tool_type || "webhook",
      url: tool.url || "",
      tool_target: tool.tool_target || "",
      method: tool.method || "POST",
      timeout_seconds: tool.timeout_seconds || 5,
      json_schema: JSON.stringify(tool.json_schema || {}, null, 2)
    });
    setShowToolModal(true);
  };

  const handleSubmitTool = async (e) => {
    e.preventDefault();
    let parsedSchema = {};
    try {
      parsedSchema = JSON.parse(toolForm.json_schema);
    } catch {
      alert("Invalid JSON schema.");
      return;
    }

    try {
      if (editingTool) {
        await api.tools.update(editingTool.id, { ...toolForm, json_schema: parsedSchema });
        addToast(`Tool '${toolForm.name}' updated`);
      } else {
        await api.tools.create({ ...toolForm, json_schema: parsedSchema, agent_id: params.id });
        addToast(`New tool integrated: ${toolForm.name}`);
      }
      setShowToolModal(false);
      fetchAgent();
    } catch (err) {
      console.error(err);
      addToast("Failed to save tool", "error");
    }
  };

  const handleDeleteTool = async (toolId) => {
    if(!confirm("are you sure?")) return;
    try {
      await api.tools.delete(toolId);
      addToast("Tool removed");
      fetchAgent();
    } catch (err) {
      addToast("Failed to remove tool", "error");
    }
  };

  if (loading) return <div className="min-h-screen bg-[#09090b] flex items-center justify-center text-slate-500 font-mono text-xs uppercase tracking-[0.3em]">Loading...</div>;

  const AccordionItem = ({ id, icon: Icon, title, children }) => (
    <div className={`border-b border-white/5 overflow-hidden transition-all ${activeAccordion === id ? 'bg-white/[0.02]' : ''}`}>
      <button 
        onClick={() => setActiveAccordion(activeAccordion === id ? null : id)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/[0.03] transition-colors"
      >
        <div className="flex items-center space-x-3 text-slate-300">
          <Icon size={16} className={activeAccordion === id ? 'text-blue-500' : 'text-slate-500'} />
          <span className={`text-xs font-bold uppercase tracking-widest ${activeAccordion === id ? 'text-white' : ''}`}>{title}</span>
        </div>
        {activeAccordion === id ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </button>
      {activeAccordion === id && (
        <div className="px-6 pb-6 pt-2 animate-in slide-in-from-top-2 duration-200">
          {children}
        </div>
      )}
    </div>
  );

  return (
    <div className="min-h-screen bg-[#09090b] text-slate-100 flex flex-col font-sans">
      
      {/* Header Studio Bar */}
      <div className="h-16 border-b border-white/5 flex items-center justify-between px-6 bg-[#09090b]/80 backdrop-blur-md sticky top-0 z-40">
        <div className="flex items-center space-x-6">
          <Link href="/">
            <div className="w-8 h-8 bg-white/5 rounded-lg flex items-center justify-center hover:bg-white/10 transition-colors text-slate-400">
              <ArrowLeft size={18} />
            </div>
          </Link>
          <div className="h-6 w-px bg-white/10" />
          <div className="flex flex-col">
            <div className="flex items-center space-x-2">
               <input 
                 value={agent.name}
                 onChange={e => setAgent({...agent, name: e.target.value})}
                 className="bg-transparent border-none focus:ring-0 font-black text-lg p-0 text-white w-auto min-w-[50px] tracking-tight"
               />
               <Pencil size={12} className="text-slate-600" />
            </div>
            <div className="flex items-center space-x-4 text-[10px] font-mono text-slate-500 tracking-tighter uppercase mt-0.5">
               <span className="flex items-center"><Activity size={10} className="mr-1" /> ID: {String(params.id).slice(0,8)}...</span>
               <span className="flex items-center text-blue-500"><Zap size={10} className="mr-1" /> Realtime API</span>
               <span className="flex items-center text-emerald-500"><Clock size={10} className="mr-1" /> 850-1200ms Latency</span>
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          <Button 
            variant="ghost" 
            className="text-slate-500 hover:text-red-500 hover:bg-red-500/10 h-9 px-4 text-xs font-bold uppercase tracking-widest"
            onClick={handleDeleteAgent}
          >
            {deleting ? "Removing..." : "Delete"}
          </Button>
          <div className="h-6 w-px bg-white/10" />
          <Button 
            onClick={handleUpdate}
            disabled={saving}
            className="bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-500/20 h-9 px-6 rounded-lg text-xs font-black uppercase tracking-[0.2em] transition-all active:scale-95"
          >
            {saving ? "Saving..." : "Save Agent"}
          </Button>
        </div>
      </div>

      {/* Main Studio Content */}
      <div className="flex flex-1 overflow-hidden">
        
        {/* Left Side: Prompt Editor */}
        <div className="flex-1 flex flex-col border-r border-white/5 bg-[#0c0c0e]">
          <div className="p-4 border-b border-white/5 flex items-center space-x-4 bg-white/[0.02]">
            <div className="flex items-center space-x-2 bg-white/5 px-3 py-1.5 rounded-lg border border-white/5">
              <Sparkles size={14} className="text-blue-400" />
              <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">GPT Realtime</span>
            </div>
            <div className="flex items-center space-x-2 bg-white/5 px-3 py-1.5 rounded-lg border border-white/5">
              <Mic2 size={14} className="text-purple-400" />
              <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest capitalize">{agent.voice}</span>
            </div>
            <div className="flex items-center space-x-2 bg-white/5 px-3 py-1.5 rounded-lg border border-white/5">
              <Globe size={14} className="text-emerald-400" />
              <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">English</span>
            </div>
          </div>
          
          <div className="flex-1 p-8 flex flex-col space-y-4">
            <h3 className="text-[11px] font-black text-slate-500 uppercase tracking-[0.3em] flex items-center">
              <MessageSquare size={14} className="mr-2" />
              Instructions for the Agent
            </h3>
            <textarea 
              value={agent.system_prompt}
              onChange={e => setAgent({...agent, system_prompt: e.target.value})}
              placeholder="### Persona of AI Voice Agent..."
              className="flex-1 bg-transparent border-none focus:ring-0 text-slate-300 font-mono text-sm leading-relaxed resize-none p-0 selection:bg-blue-500/30"
            />
          </div>
          
      
        </div>

        {/* Middle: Configuration Accordion */}
        <div className="w-[320px] lg:w-[400px] flex flex-col border-r border-white/5 bg-[#09090b]">
           <div className="p-4 border-b border-white/5 bg-white/[0.02]">
              <h3 className="text-[11px] font-black text-slate-500 uppercase tracking-[0.3em]">Agent Settings</h3>
           </div>
           
           <div className="flex-1 overflow-y-auto custom-scrollbar">
              <AccordionItem id="functions" icon={Boxes} title="Tools">
                 <div className="space-y-3">
                    <Button 
                      variant="ghost" 
                      className="w-full border border-dashed border-white/10 hover:bg-white/5 text-slate-400 h-10 text-[10px] font-bold uppercase tracking-widest"
                      onClick={openCreateModal}
                    >
                      <Plus size={14} className="mr-2" /> Add Tool
                    </Button>
                    
                    {agent.tools?.map(t => (
                      <div key={t.id} className="p-4 bg-white/5 border border-white/5 rounded-xl group relative">
                         <div className="flex items-center justify-between mb-2">
                            <span className="font-bold text-xs text-blue-400">{t.name}</span>
                            <div className="flex items-center space-x-1 opacity-0 group-hover:opacity-100 transition-opacity">
                               <button onClick={() => openEditModal(t)} className="p-1 hover:text-blue-500 transition-colors"><Pencil size={12} /></button>
                               <button onClick={() => handleDeleteTool(t.id)} className="p-1 hover:text-red-500 transition-colors"><Trash2 size={12} /></button>
                            </div>
                         </div>
                         <p className="text-[10px] text-slate-500 line-clamp-2 leading-relaxed">{t.description}</p>
                         <div className="mt-3 text-[9px] font-mono text-slate-600 uppercase tracking-tighter">
                            {t.tool_type === 'call_transfer' ? (
                              <span className="text-emerald-500/50 italic">→ {t.tool_target}</span>
                            ) : t.tool_type === 'call_end' ? (
                              <span className="text-red-500/50 italic">Hangs up call</span>
                            ) : (
                              <span>{t.method} {String(t.url || "").slice(0, 30)}...</span>
                            )}
                         </div>
                      </div>
                    ))}
                 </div>
              </AccordionItem>

               <AccordionItem id="voice" icon={Mic2} title="Voice & Speech Settings">
                  <div className="space-y-6">
                    <VoiceSelection 
                      value={agent.voice}
                      onChange={v => setAgent({...agent, voice: v})}
                    />
                    
                    <div className="pt-4 border-t border-white/5 space-y-6">
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] flex items-center justify-between">
                          <span>Initial Greeting Message</span>
                          <span className="text-blue-500/50 italic lowercase font-medium">agent speaks first</span>
                        </label>
                        <textarea 
                          value={agent.greeting_message || ""}
                          onChange={e => setAgent({...agent, greeting_message: e.target.value})}
                          placeholder="e.g. Hello, how can I help you today?"
                          className="w-full bg-white/5 border border-white/5 rounded-xl p-4 text-xs focus:ring-1 focus:ring-blue-500/50 outline-none min-h-[80px]"
                        />
                      </div>

                      <div className="grid grid-cols-2 gap-6">
                        <div className="space-y-3">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] flex items-center justify-between">
                            <span>Intelligence Style</span>
                            <span className="text-blue-400 font-bold">{agent.temperature}</span>
                          </label>
                          <input 
                            type="range" min="0.1" max="1.2" step="0.1"
                            value={agent.temperature || 0.8}
                            onChange={e => setAgent({...agent, temperature: parseFloat(e.target.value)})}
                            className="w-full h-1.5 bg-white/5 rounded-lg appearance-none cursor-pointer accent-blue-600"
                          />
                          <div className="flex justify-between text-[8px] font-bold text-slate-600 uppercase tracking-tighter">
                            <span>Precise</span>
                            <span>Creative</span>
                          </div>
                        </div>

                        <div className="space-y-3">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] flex items-center justify-between">
                            <span>Response Delay</span>
                            <span className="text-blue-400 font-bold">{agent.silence_duration_ms}ms</span>
                          </label>
                          <input 
                            type="range" min="400" max="2500" step="100"
                            value={agent.silence_duration_ms || 1000}
                            onChange={e => setAgent({...agent, silence_duration_ms: parseInt(e.target.value)})}
                            className="w-full h-1.5 bg-white/5 rounded-lg appearance-none cursor-pointer accent-blue-600"
                          />
                          <div className="flex justify-between text-[8px] font-bold text-slate-600 uppercase tracking-tighter">
                            <span>Snappy</span>
                            <span>Patient</span>
                          </div>
                        </div>
                      </div>

                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] flex items-center justify-between">
                          <span>Interruption Sensitivity</span>
                          <span className="text-blue-400 font-bold">{(agent.vad_threshold || 0.5).toFixed(1)}</span>
                        </label>
                        <input 
                          type="range" min="0.1" max="0.9" step="0.1"
                          value={agent.vad_threshold || 0.5}
                          onChange={e => setAgent({...agent, vad_threshold: parseFloat(e.target.value)})}
                          className="w-full h-1.5 bg-white/5 rounded-lg appearance-none cursor-pointer accent-blue-600"
                        />
                        <div className="flex justify-between text-[8px] font-bold text-slate-600 uppercase tracking-tighter">
                          <span>Easy to interrupt</span>
                          <span>Ignore Background</span>
                        </div>
                      </div>
                    </div>
                  </div>
               </AccordionItem>

           </div>
        </div>

        {/* Right: Simulation Panel */}
        <div className="w-[380px] lg:w-[460px] flex flex-col bg-[#0c0c0e]">
           <div className="p-4 border-b border-white/5 bg-white/[0.02] flex items-center justify-between">
              <h3 className="text-[11px] font-black text-slate-500 uppercase tracking-[0.3em]">Test Your Agent</h3>
              <div className="flex items-center space-x-2">
                 <div className="px-2 py-1 bg-white/5 rounded text-[10px] font-bold text-slate-400 border border-white/5 cursor-pointer">Test Audio</div>
                 <div className="px-2 py-1 bg-white/5 rounded text-[10px] font-bold text-slate-400 border border-white/5 cursor-pointer">Test AI</div>
              </div>
           </div>
           
           <div className="flex-1 flex flex-col items-center justify-center p-0">
              <WebCall agentId={params.id} />
           </div>
        </div>

      </div>

      {/* Tool Modal (Same logic but dark themed) */}
      {showToolModal && (
         <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 z-[100]">
           <div className="w-full max-w-lg bg-[#18181b] border border-white/10 rounded-2xl shadow-2xl p-8 space-y-6 animate-in zoom-in-95 duration-200">
             <div className="flex items-center justify-between">
               <h2 className="text-xl font-black tracking-tight">
                 {editingTool ? "Update Tool" : "New Tool"}
               </h2>
               <div className="w-10 h-10 bg-white/5 rounded-full flex items-center justify-center text-blue-500">
                  <Boxes size={20} />
               </div>
             </div>

              <form onSubmit={handleSubmitTool} className="space-y-5">
                 <div className="grid grid-cols-2 gap-4">
                   <div className="space-y-2">
                     <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Tool Name</label>
                     <input 
                       required 
                       value={toolForm.name}
                       onChange={e => setToolForm({...toolForm, name: e.target.value.replace(/\s+/g, "_")})}
                       className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500/50 outline-none transition-all"
                     />
                   </div>
                   <div className="space-y-2">
                     <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Tool Type</label>
                     <select 
                       value={toolForm.tool_type}
                       onChange={e => setToolForm({...toolForm, tool_type: e.target.value})}
                       className="w-full bg-[#18181b] border border-white/10 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500/50 outline-none"
                     >
                       <option value="webhook">Webhook</option>
                       <option value="call_transfer">Call Transfer</option>
                       <option value="call_end">End Call</option>
                     </select>
                   </div>
                 </div>
                 
                 <div className="space-y-2">
                   <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Description</label>
                   <input 
                     required 
                     value={toolForm.description}
                     onChange={e => setToolForm({...toolForm, description: e.target.value})}
                     className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500/50 outline-none transition-all"
                   />
                 </div>

                 {toolForm.tool_type === "webhook" && (
                   <>
                    <div className="flex space-x-3">
                      <div className="flex-1 space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">URL</label>
                        <input 
                          required 
                          value={toolForm.url}
                          onChange={e => setToolForm({...toolForm, url: e.target.value})}
                          className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500/50 outline-none transition-all"
                        />
                      </div>
                      <div className="w-32 space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Method</label>
                        <select 
                          value={toolForm.method}
                          onChange={e => setToolForm({...toolForm, method: e.target.value})}
                          className="w-full bg-[#18181b] border border-white/10 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500/50 outline-none"
                        >
                          <option value="POST">POST</option>
                          <option value="GET">GET</option>
                        </select>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">JSON Schema</label>
                      <textarea 
                        required 
                        className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-xs font-mono min-h-[140px] focus:ring-2 focus:ring-blue-500/50 outline-none"
                        value={toolForm.json_schema}
                        onChange={e => setToolForm({...toolForm, json_schema: e.target.value})}
                      />
                    </div>
                   </>
                 )}

                 {toolForm.tool_type === "call_transfer" && (
                   <div className="space-y-2">
                     <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Transfer Phone Number</label>
                     <input 
                       required 
                       placeholder="+1234567890"
                       value={toolForm.tool_target}
                       onChange={e => setToolForm({...toolForm, tool_target: e.target.value})}
                       className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500/50 outline-none transition-all"
                     />
                   </div>
                 )}

                 {toolForm.tool_type === "call_end" && (
                   <div className="p-4 bg-red-500/5 border border-red-500/20 rounded-xl">
                      <p className="text-[10px] font-bold text-red-400 uppercase tracking-widest">Note: This tool will immediately terminate the conversation.</p>
                   </div>
                 )}
                 
                 <div className="flex justify-end space-x-3 pt-4">
                  <Button variant="ghost" type="button" className="text-slate-400" onClick={() => setShowToolModal(false)}>Discard</Button>
                  <Button type="submit" className="bg-blue-600 hover:bg-blue-500 px-8">Save Tool</Button>
                </div>
             </form>
           </div>
         </div>
      )}

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.05);
          border-radius: 10px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.1);
        }
      `}</style>

    </div>
  );
}

