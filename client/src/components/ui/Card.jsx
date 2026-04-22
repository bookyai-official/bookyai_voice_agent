export function Card({ children, className = "", hover = false }) {
  return (
    <div className={`bg-[#111113] border border-white/5 rounded-2xl overflow-hidden p-6 ${hover ? 'transition-all duration-300 hover:bg-white/[0.03] hover:border-white/10' : ''} ${className}`}>
      {children}
    </div>
  );
}
