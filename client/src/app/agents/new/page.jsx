"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Save } from "lucide-react";
import { VoiceSelection } from "@/components/VoiceSelection";
import { useToast } from "@/lib/toast";

export default function NewAgent() {
  const router = useRouter();
  const { addToast } = useToast();
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    name: "",
    voice: "alloy",
    system_prompt: "",
    active: true
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const newAgent = await api.agents.create(formData);
      addToast("New agent created successfully");
      router.push(`/agents/${newAgent.id}`);
    } catch (err) {
      console.error(err);
      addToast("Failed to create agent", "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-10 pb-20 font-sans">
      <div className="flex items-center space-x-6">
        <Link href="/">
          <div className="w-10 h-10 bg-white/5 rounded-xl flex items-center justify-center hover:bg-white/10 transition-colors text-slate-400">
            <ArrowLeft size={20} />
          </div>
        </Link>
        <div>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase">New Agent</h1>
          <p className="text-slate-500 mt-1 font-bold tracking-widest uppercase text-xs opacity-60">Create your new voice assistant here</p>
        </div>
      </div>

      <Card className="bg-[#111113] border-white/5 shadow-2xl rounded-3xl p-10">
        <form onSubmit={handleSubmit} className="space-y-10">
          <Input 
            label="Agent Name" 
            placeholder="e.g. Sarah - Office Assistant" 
            required 
            value={formData.name}
            onChange={e => setFormData({...formData, name: e.target.value})}
          />
          
          <VoiceSelection 
            value={formData.voice}
            onChange={v => setFormData({...formData, voice: v})}
          />

          <div className="space-y-4">
            <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.3em]">Instructions</h3>
            <Textarea 
              placeholder="You are a professional office assistant. Your goal is to help customers..." 
              required 
              className="min-h-[250px] font-mono text-sm leading-relaxed"
              value={formData.system_prompt}
              onChange={e => setFormData({...formData, system_prompt: e.target.value})}
            />
          </div>

          <div className="pt-8 border-t border-white/5 flex justify-end items-center space-x-6">
             <Link href="/" className="text-[10px] font-black text-slate-500 hover:text-white uppercase tracking-widest transition-colors">Cancel</Link>
             <Button type="submit" disabled={loading} className="h-12 px-10 rounded-xl bg-blue-600 hover:bg-blue-500 shadow-xl shadow-blue-500/20">
               <Save size={18} className="mr-3" />
               {loading ? "Creating..." : "Create Agent"}
             </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
