export function Input({ label, error, ...props }) {
  return (
    <div className="flex flex-col space-y-2 w-full font-montserrat">
      {label && <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">{label}</label>}
      <input 
        className="w-full px-4 py-3 bg-white/5 border border-white/5 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500/50 transition-all placeholder:text-slate-600 text-sm"
        {...props} 
      />
      {error && <span className="text-[10px] font-bold text-red-500 uppercase tracking-tighter">{error}</span>}
    </div>
  );
}

export function Textarea({ label, error, ...props }) {
  return (
    <div className="flex flex-col space-y-2 w-full font-montserrat">
      {label && <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">{label}</label>}
      <textarea 
        className="w-full px-4 py-3 bg-white/5 border border-white/5 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500/50 transition-all placeholder:text-slate-600 text-sm min-h-[120px]"
        {...props} 
      />
      {error && <span className="text-[10px] font-bold text-red-500 uppercase tracking-tighter">{error}</span>}
    </div>
  );
}
