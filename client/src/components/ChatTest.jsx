"use client";

import { useState, useRef, useEffect } from "react";
import { Card } from "./ui/Card";
import { Button } from "./ui/Button";
import { Send, Bot, User, Loader2, MessageSquare, Trash2, Sparkles } from "lucide-react";
import { api } from "@/lib/api";

export function ChatTest({ agentId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastResponseId, setLastResponseId] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = async (e) => {
    e?.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = { role: "user", content: input };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      // The Responses API is stateful. If we have a lastResponseId, 
      // we only send the latest user message to continue the thread.
      const messagesToSend = lastResponseId ? [userMessage] : newMessages;
      
      const response = await api.chat.send(agentId, messagesToSend, lastResponseId);
      
      setMessages([...newMessages, { role: "assistant", content: response.content }]);
      setLastResponseId(response.response_id);
    } catch (err) {
      console.error("Chat error:", err);
      setMessages([...newMessages, { role: "system", content: "Error: Could not get response from agent." }]);
    } finally {
      setLoading(false);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setLastResponseId(null);
  };

  return (
    <Card className="w-full h-full overflow-hidden bg-[#111113] border-white/5 font-sans flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 px-1">
        <h2 className="text-xl font-bold text-white flex items-center gap-3 tracking-tight">
          Test Your Agent (Chat)
        </h2>
        <Button 
          variant="ghost" 
          size="sm" 
          onClick={clearChat}
          className="text-slate-500 hover:text-red-400 h-8 px-2"
        >
          <Trash2 size={14} />
        </Button>
      </div>

      {/* Chat Messages */}
      <div className="flex-1 min-h-[400px] overflow-y-auto rounded-xl bg-white/[0.02] border border-white/5 p-4 space-y-4 custom-scrollbar mb-4">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-600 gap-4">
            <div className="w-16 h-16 bg-white/5 rounded-full flex items-center justify-center">
               <MessageSquare size={32} className="opacity-20" />
            </div>
            <p className="text-[10px] font-black uppercase tracking-[0.2em]">
              Send a message to start testing
            </p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div
              key={i}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role !== "user" && (
                <div className={`h-8 w-8 rounded-xl flex items-center justify-center flex-shrink-0 mt-1 shadow-lg border ${
                  msg.role === "system" 
                    ? "bg-red-500/10 text-red-500 border-red-500/20" 
                    : "bg-blue-500/10 text-blue-500 border-blue-500/20"
                }`}>
                  <Bot size={14} />
                </div>
              )}
              <div
                className={`max-w-[85%] px-5 py-4 rounded-2xl text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white rounded-tr-none shadow-xl shadow-blue-600/20 font-bold"
                    : msg.role === "system"
                    ? "bg-red-500/5 border border-red-500/10 text-red-400 italic rounded-tl-none"
                    : "bg-white/5 border border-white/5 text-slate-200 rounded-tl-none font-medium"
                }`}
              >
                {msg.content}
              </div>
              {msg.role === "user" && (
                <div className="h-8 w-8 rounded-xl bg-white/5 text-slate-500 border border-white/5 flex items-center justify-center flex-shrink-0 mt-1">
                  <User size={14} />
                </div>
              )}
            </div>
          ))
        )}
        {loading && (
          <div className="flex gap-3 justify-start animate-pulse">
            <div className="h-8 w-8 rounded-xl bg-blue-500/10 text-blue-500 border border-blue-500/20 flex items-center justify-center flex-shrink-0 mt-1">
              <Sparkles size={14} className="animate-spin" />
            </div>
            <div className="bg-white/5 border border-white/5 text-slate-400 px-5 py-4 rounded-2xl rounded-tl-none text-sm font-mono">
              Agent is thinking...
            </div>
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      {/* Input Area */}
      <form onSubmit={handleSend} className="relative group">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message..."
          disabled={loading}
          className="w-full bg-white/5 border border-white/10 rounded-2xl px-6 py-4 pr-16 text-sm text-white focus:ring-2 focus:ring-blue-500/50 outline-none transition-all placeholder:text-slate-600"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="absolute right-3 top-1/2 -translate-y-1/2 w-10 h-10 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-xl flex items-center justify-center transition-all active:scale-90 shadow-lg shadow-blue-500/20"
        >
          {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
        </button>
      </form>

      <div className="mt-4 flex items-center justify-center gap-4 text-[9px] font-bold text-slate-600 uppercase tracking-widest">
        <span className="flex items-center gap-1.5"><Sparkles size={10} /> GPT-4o Mini</span>
        <span className="w-1 h-1 bg-white/10 rounded-full" />
        <span className="flex items-center gap-1.5">Tool Support Active</span>
      </div>
    </Card>
  );
}
