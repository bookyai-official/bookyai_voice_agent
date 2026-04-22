"use client";

import { useState, useRef } from "react";
import { Play, Pause, Check } from "lucide-react";
import { Button } from "./ui/Button";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "admin";

const VOICES = [
  { id: "alloy", name: "Alloy", desc: "Neutral & Versatile", gender: "Neutral" },
  { id: "echo", name: "Echo", desc: "Warm & Deep", gender: "Male" },
  { id: "shimmer", name: "Shimmer", desc: "Clear & Bright", gender: "Female" },
  { id: "fable", name: "Fable", desc: "British & Narrative", gender: "Neutral" },
  { id: "onyx", name: "Onyx", desc: "Deep & Professional", gender: "Male" },
  { id: "nova", name: "Nova", desc: "Professional & Sharp", gender: "Female" },
  { id: "ash", name: "Ash", desc: "Soft & Gentle", gender: "Neutral" },
  { id: "coral", name: "Coral", desc: "Expressive & Lively", gender: "Female" },
  { id: "sage", name: "Sage", desc: "Calm & Wise", gender: "Neutral" },
  { id: "ballad", name: "Ballad", desc: "Melodic & Rhythmic", gender: "Male" },
  { id: "verse", name: "Verse", desc: "Poetic & Articulate", gender: "Male" },
];

export function VoiceSelection({ value, onChange }) {
  const [playing, setPlaying] = useState(null);
  const [loadingVoice, setLoadingVoice] = useState(null);
  const audioRef = useRef(null);

  const togglePlay = async (voice) => {
    if (playing === voice.id) {
      audioRef.current.pause();
      setPlaying(null);
      return;
    }

    if (audioRef.current) {
      audioRef.current.pause();
    }
    
    setLoadingVoice(voice.id);
    try {
      const res = await fetch(`${API_URL}/agents/voice-preview/${voice.id}`, {
        headers: { "x-token": TOKEN }
      });
      
      if (!res.ok) {
        throw new Error("Voice preview not available for this model");
      }
      
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      
      audioRef.current = new Audio(url);
      setPlaying(voice.id);
      setLoadingVoice(null);
      
      await audioRef.current.play();
      
      audioRef.current.onended = () => {
        setPlaying(null);
        URL.revokeObjectURL(url);
      };
    } catch (err) {
      console.error("Preview failed:", err);
      setLoadingVoice(null);
      setPlaying(null);
      alert(err.message || "Preview failed");
    }
  };

  return (
    <div className="space-y-4 font-sans">
      <div className="flex items-center justify-between">
        <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Select Agent Voice</label>
        <span className="text-[10px] font-bold text-blue-400 bg-blue-500/10 px-2.5 py-1 rounded-lg border border-blue-500/20 uppercase tracking-tighter">Realtime Ready</span>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3">
        {VOICES.map((v) => (
          <div 
            key={v.id}
            onClick={() => onChange(v.id)}
            className={`relative flex flex-col p-4 rounded-2xl border transition-all cursor-pointer group h-full ${
              value === v.id 
                ? 'border-blue-500 bg-blue-500/10 shadow-lg shadow-blue-500/10' 
                : 'border-white/5 bg-white/5 hover:border-white/10 hover:bg-white/[0.08]'
            }`}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="min-w-0 pr-2">
                <span className={`font-black block truncate text-xs uppercase tracking-tight ${value === v.id ? 'text-blue-400' : 'text-white'}`}>
                  {v.name}
                </span>
                <span className="inline-block text-[8px] font-black uppercase text-slate-500 tracking-tighter bg-white/5 px-1.5 py-0.5 rounded mt-1">
                  {v.gender}
                </span>
              </div>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  togglePlay(v);
                }}
                disabled={loadingVoice === v.id}
                className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                  playing === v.id 
                    ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/20' 
                    : 'bg-white/5 border border-white/5 text-slate-400 hover:text-white hover:bg-white/10'
                } ${loadingVoice === v.id ? 'opacity-50 cursor-wait' : ''}`}
              >
                {loadingVoice === v.id ? (
                  <div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
                ) : playing === v.id ? (
                  <Pause size={12} fill="currentColor" />
                ) : (
                  <Play size={12} className="ml-0.5" fill="currentColor" />
                )}
              </button>
            </div>

            <p className="text-[10px] text-slate-500 line-clamp-2 font-medium leading-snug">
              {v.desc}
            </p>

            {value === v.id && (
              <div className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-blue-600 text-white rounded-full flex items-center justify-center shadow-lg border-2 border-[#09090b]">
                <Check size={10} strokeWidth={4} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
