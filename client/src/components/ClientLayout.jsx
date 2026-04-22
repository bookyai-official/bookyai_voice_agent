"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { Mic, LayoutDashboard, Settings, Phone } from "lucide-react";

export default function ClientLayout({ children }) {
  const pathname = usePathname();
  
  // Hide sidebar on Agent Detail page: /agents/[id]
  const isAgentDetailPage = pathname && pathname.startsWith('/agents/') && pathname.split('/').length === 3 && pathname !== '/agents/new';
  const showSidebar = !isAgentDetailPage;

  return (
    <>
      {/* Persistent Side Navigation */}
      {showSidebar && (
        <aside className="w-64 bg-[#111113] border-r border-white/5 flex flex-col hidden md:flex shrink-0">
          <div className="h-16 flex items-center px-6 border-b border-white/5">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center mr-3 shadow-lg shadow-blue-500/20">
              <Mic className="text-white" size={18} />
            </div>
            <span className="font-black text-sm tracking-[0.2em] uppercase text-white">Studio</span>
          </div>
          
          <nav className="flex-1 py-6 px-4 space-y-1">
            <Link href="/" className={`flex items-center px-4 py-3 font-bold text-xs uppercase tracking-widest rounded-xl transition-all group ${pathname === '/' ? 'bg-blue-600/10 text-blue-500' : 'text-slate-400 hover:bg-white/5 hover:text-white'}`}>
              <LayoutDashboard size={18} className={`mr-3 transition-colors ${pathname === '/' ? 'text-blue-500' : 'text-slate-500 group-hover:text-blue-500'}`} />
              Dashboard
            </Link>
            <Link href="/agents/new" className={`flex items-center px-4 py-3 font-bold text-xs uppercase tracking-widest rounded-xl transition-all group ${pathname === '/agents/new' ? 'bg-blue-600/10 text-blue-500' : 'text-slate-400 hover:bg-white/5 hover:text-white'}`}>
              <Settings size={18} className={`mr-3 transition-colors ${pathname === '/agents/new' ? 'text-blue-500' : 'text-slate-500 group-hover:text-blue-500'}`} />
              Create Agent
            </Link>
            <Link href="/calls" className={`flex items-center px-4 py-3 font-bold text-xs uppercase tracking-widest rounded-xl transition-all group ${pathname === '/calls' ? 'bg-blue-600/10 text-blue-500' : 'text-slate-400 hover:bg-white/5 hover:text-white'}`}>
              <Phone size={18} className={`mr-3 transition-colors ${pathname === '/calls' ? 'text-blue-500' : 'text-slate-500 group-hover:text-blue-500'}`} />
              Call Records
            </Link>
          </nav>

          <div className="p-4">
             <div className="bg-gradient-to-br from-blue-600/10 to-purple-600/10 border border-white/5 p-4 rounded-2xl">
                <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-2">Usage Plan</p>
                <div className="flex items-center justify-between">
                   <span className="text-xs font-bold">Pro Studio</span>
                   <span className="text-[10px] text-blue-400 font-black">ACTIVE</span>
                </div>
             </div>
          </div>
        </aside>
      )}

      {/* Main Content Area */}
      <main className={`flex-1 flex flex-col h-screen overflow-hidden ${!showSidebar ? 'w-full' : ''}`}>
        {showSidebar && (
          <div className="h-16 bg-[#09090b] border-b border-white/5 flex items-center px-8 md:hidden">
            <span className="font-black text-sm tracking-[0.2em] uppercase text-white">Studio</span>
          </div>
        )}
        <div className="flex-1 overflow-y-auto custom-scrollbar">
          <div className={`${showSidebar ? 'max-w-7xl mx-auto p-8' : 'w-full h-full p-0'}`}>
            {children}
          </div>
        </div>
      </main>
    </>
  );
}
