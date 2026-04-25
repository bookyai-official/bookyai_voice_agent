"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Card } from "./ui/Card";
import { Button } from "./ui/Button";
import { Phone, PhoneOff, Mic, Bot, User, Wrench, Loader2, Radio } from "lucide-react";

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

// OpenAI Realtime requires 24000 Hz PCM16
const SAMPLE_RATE = 24000;
const SCRIPT_PROCESSOR_BUFFER = 4096;

// --- Audio utility helpers ---

function float32ToInt16(float32) {
  const int16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32[i]));
    int16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return int16;
}

function int16ToFloat32(int16) {
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768.0;
  }
  return float32;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const buffer = new ArrayBuffer(binary.length);
  const view = new Uint8Array(buffer);
  for (let i = 0; i < binary.length; i++) {
    view[i] = binary.charCodeAt(i);
  }
  return buffer;
}

// ---

export function WebCall({ agentId }) {
  const [status, setStatus] = useState("idle"); // idle | connecting | connected | ending
  const [transcript, setTranscript] = useState([]);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isAgentSpeaking, setIsAgentSpeaking] = useState(false);
  const [activeTool, setActiveTool] = useState(null);

  const wsRef = useRef(null);
  const audioCtxRef = useRef(null);
  const micSourceRef = useRef(null);
  const processorRef = useRef(null);
  const micStreamRef = useRef(null);
  const nextPlayTimeRef = useRef(0);
  const activeAudioSourcesRef = useRef([]); // Track all scheduled nodes for instant cancellation
  const transcriptEndRef = useRef(null);

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  /**
   * Immediately stops all scheduled/playing AI audio nodes.
   * Called on user interruption (speech_start) and on cleanup.
   */
  const stopPlayback = useCallback(() => {
    activeAudioSourcesRef.current.forEach((src) => {
      try { src.onended = null; src.stop(); src.disconnect(); } catch (_) {}
    });
    activeAudioSourcesRef.current = [];
    nextPlayTimeRef.current = 0;
    setIsAgentSpeaking(false);
  }, []);

  const cleanup = useCallback(() => {
    stopPlayback();
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (micSourceRef.current) {
      micSourceRef.current.disconnect();
      micSourceRef.current = null;
    }
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    nextPlayTimeRef.current = 0;
  }, [stopPlayback]);

  useEffect(() => {
    return cleanup;
  }, [cleanup]);

  const playAudioChunk = useCallback((base64Audio) => {
    if (!audioCtxRef.current) return;
    const ctx = audioCtxRef.current;

    const arrayBuffer = base64ToArrayBuffer(base64Audio);
    const int16Data = new Int16Array(arrayBuffer);
    const float32Data = int16ToFloat32(int16Data);

    if (float32Data.length === 0) return;

    const audioBuffer = ctx.createBuffer(1, float32Data.length, SAMPLE_RATE);
    audioBuffer.copyToChannel(float32Data, 0);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    // Track source so it can be stopped instantly on interruption
    activeAudioSourcesRef.current.push(source);

    // Schedule for smooth gapless playback
    const startAt = Math.max(ctx.currentTime + 0.02, nextPlayTimeRef.current);
    source.start(startAt);
    nextPlayTimeRef.current = startAt + audioBuffer.duration;

    source.onended = () => {
      // Remove from tracking list when naturally finished
      activeAudioSourcesRef.current = activeAudioSourcesRef.current.filter((s) => s !== source);
      // If nothing left scheduled, mark agent as done speaking
      if (ctx.currentTime >= nextPlayTimeRef.current - 0.1) {
        setIsAgentSpeaking(false);
      }
    };
  }, []);

  const startCall = async () => {
    setStatus("connecting");
    setTranscript([]);
    setActiveTool(null);

    try {
      // 1. Request microphone
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: SAMPLE_RATE },
        video: false,
      });
      micStreamRef.current = stream;

      // 2. Set up AudioContext at 24kHz
      const ctx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: SAMPLE_RATE,
      });
      audioCtxRef.current = ctx;
      nextPlayTimeRef.current = ctx.currentTime;

      // 3. Mic → ScriptProcessor → WebSocket
      const micSource = ctx.createMediaStreamSource(stream);
      micSourceRef.current = micSource;

      // ScriptProcessor is deprecated but universally supported in browsers
      const processor = ctx.createScriptProcessor(SCRIPT_PROCESSOR_BUFFER, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
        const float32 = e.inputBuffer.getChannelData(0);
        const int16 = float32ToInt16(float32);
        const base64 = arrayBufferToBase64(int16.buffer);
        wsRef.current.send(JSON.stringify({ type: "audio", audio: base64 }));
      };

      // ScriptProcessor requires connecting to destination to be active
      micSource.connect(processor);
      processor.connect(ctx.destination);

      // 4. Open WebSocket to backend
      let final_ws_url = "";
      // get
      if (WS_BASE_URL.includes("localhost")) {
        final_ws_url = WS_BASE_URL.replace("http", "ws");
      } else {
        final_ws_url = WS_BASE_URL.replace("https", "wss");
      }

      final_ws_url = final_ws_url +`/ws/webcall/${agentId}`
      console.log("Connecting to WebSocket:", final_ws_url);
      const ws = new WebSocket(final_ws_url);
      wsRef.current = ws;

      ws.onopen = () => {
        // Audio processing starts automatically via ScriptProcessor
      };

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case "status":
            if (msg.status === "connected") setStatus("connected");
            break;
          case "audio":
            setIsAgentSpeaking(true);
            playAudioChunk(msg.audio);
            break;
          case "audio_done":
            setIsAgentSpeaking(false);
            break;
          case "transcript":
            setTranscript((prev) => [...prev, { role: msg.role, text: msg.text }]);
            break;
          case "speech_start":
            setIsSpeaking(true);
            // User interrupted — immediately kill all queued/playing AI audio
            stopPlayback();
            break;
          case "speech_stop":
            setIsSpeaking(false);
            break;
          case "tool_call":
            setActiveTool(msg.tool);
            setTimeout(() => setActiveTool(null), 4000);
            break;
          case "session_end":
            console.log("[WEB CALL] Session ended by agent.");
            cleanup();
            setStatus("idle");
            setIsSpeaking(false);
            setIsAgentSpeaking(false);
            break;
          case "error":
            console.error("WebCall error:", msg.message);
            cleanup();
            setStatus("idle");
            break;
        }
      };

      ws.onerror = () => {
        cleanup();
        setStatus("idle");
        alert("WebSocket connection failed. Make sure the backend server is running.");
      };

      ws.onclose = () => {
        setStatus("idle");
        setIsSpeaking(false);
        setIsAgentSpeaking(false);
      };
    } catch (err) {
      console.error("Failed to start web call:", err);
      cleanup();
      setStatus("idle");
      alert("Could not start call. Please allow microphone access and try again.");
    }
  };

  const endCall = () => {
    setStatus("ending");
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "stop" }));
    }
    setTimeout(() => {
      cleanup();
      setStatus("idle");
      setIsSpeaking(false);
      setIsAgentSpeaking(false);
    }, 600);
  };

  return (
    <Card className="w-full h-full overflow-hidden bg-[#111113] border-white/5 font-montserrat">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-3 tracking-tight">
           
            Test Your Agent
          </h2>
        </div>

        {status === "connected" && (
          <span className="flex items-center gap-2 text-[10px] text-emerald-400 bg-emerald-500/10 px-4 py-2 rounded-xl border border-emerald-500/20 uppercase tracking-widest">
            <span className="w-2 h-2 bg-emerald-500 rounded-full animate-ping" />
            On Call
          </span>
        )}
      </div>

      {/* Active Tool Banner */}
      {activeTool && (
        <div className="mb-6 flex items-center gap-3 text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 px-4 py-3 rounded-xl uppercase tracking-widest">
          <Wrench size={14} className="animate-spin flex-shrink-0" />
          <span>
            Using Tool:{" "}
            <span className="font-mono text-blue-400">{activeTool}</span>
          </span>
        </div>
      )}

      {/* Live Transcript */}
      <div className="mb-8 h-[400px] overflow-y-auto rounded-xl bg-white/[0.02] border border-white/5 p-4 space-y-4 custom-scrollbar">
        {transcript.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-600 gap-4">
            <div className="w-16 h-16 bg-white/5 rounded-full flex items-center justify-center">
               <Mic size={32} className="opacity-20" />
            </div>
            <p className="text-[10px] font-black uppercase tracking-[0.2em]">
              {status === "idle"
                ? "Start a call to begin"
                : "Connecting..."}
            </p>
          </div>
        ) : (
          transcript.map((msg, i) => (
            <div
              key={i}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role === "assistant" && (
                <div className="h-8 w-8 rounded-xl bg-blue-500/10 text-blue-500 border border-blue-500/20 flex items-center justify-center flex-shrink-0 mt-1 shadow-lg shadow-blue-500/5">
                  <Bot size={14} />
                </div>
              )}
              <div
                className={`max-w-[80%] px-5 py-4 rounded-2xl text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white rounded-tr-none shadow-xl shadow-blue-600/20 font-bold"
                    : "bg-white/5 border border-white/5 text-slate-200 rounded-tl-none font-medium"
                }`}
              >
                {msg.text}
              </div>
              {msg.role === "user" && (
                <div className="h-8 w-8 rounded-xl bg-white/5 text-slate-500 border border-white/5 flex items-center justify-center flex-shrink-0 mt-1">
                  <User size={14} />
                </div>
              )}
            </div>
          ))
        )}
        <div ref={transcriptEndRef} />
      </div>

      {/* Speaking Indicators + Controls */}
      <div className="flex flex-col items-center gap-6">
        {status === "connected" && (
          <div className="flex items-center gap-4 w-full">
            <div
              className={`flex-1 flex items-center justify-center gap-3 text-[10px] font-black uppercase tracking-widest py-3 rounded-xl border transition-all ${
                isSpeaking
                  ? "bg-blue-500/10 text-blue-400 border-blue-500/20 shadow-lg shadow-blue-500/10"
                  : "bg-white/2 border-white/5 text-slate-600"
              }`}
            >
              <Mic size={14} className={isSpeaking ? "animate-pulse" : ""} />
              {isSpeaking ? "You are speaking" : "Mic is on"}
            </div>
            <div
              className={`flex-1 flex items-center justify-center gap-3 text-[10px] font-black uppercase tracking-widest py-3 rounded-xl border transition-all ${
                isAgentSpeaking
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 shadow-lg shadow-emerald-500/10"
                  : "bg-white/2 border-white/5 text-slate-600"
              }`}
            >
              <Bot size={14} className={isAgentSpeaking ? "animate-pulse" : ""} />
              {isAgentSpeaking ? "Agent is speaking" : "Agent is listening"}
            </div>
          </div>
        )}

        <div className="w-full">
          {status === "idle" && (
            <Button onClick={startCall} className="w-full gap-3 h-14 text-xs font-black uppercase tracking-[0.2em] bg-blue-600 hover:bg-blue-500 shadow-xl shadow-blue-600/20 rounded-2xl">
              <Phone size={18} />
              Start Call
            </Button>
          )}

          {status === "connecting" && (
            <Button disabled className="w-full gap-3 h-14 text-xs font-black uppercase tracking-[0.2em] bg-white/5 text-slate-500 border border-white/5 rounded-2xl opacity-70 cursor-not-allowed">
              <Loader2 size={18} className="animate-spin" />
              Connecting...
            </Button>
          )}

          {status === "connected" && (
            <Button
              variant="danger"
              onClick={endCall}
              className="w-full gap-3 h-14 text-xs font-black uppercase tracking-[0.2em] shadow-xl shadow-red-500/20 rounded-2xl"
            >
              <PhoneOff size={18} />
              End Call
            </Button>
          )}

          {status === "ending" && (
            <Button disabled className="w-full gap-3 h-14 text-xs font-black uppercase tracking-[0.2em] bg-white/5 text-slate-500 border border-white/5 rounded-2xl opacity-70 cursor-not-allowed">
              <Loader2 size={18} className="animate-spin" />
              Ending...
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
