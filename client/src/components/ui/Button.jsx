export function Button({ children, variant = "primary", className = "", ...props }) {
  const baseStyles = "inline-flex items-center justify-center font-montserrat transition-all duration-200 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed uppercase tracking-widest font-black";
  
  const variants = {
    primary: "bg-blue-600 text-white hover:bg-blue-500 shadow-lg shadow-blue-600/20 px-6 py-2.5 rounded-xl text-[10px]",
    secondary: "bg-white/5 text-white border border-white/5 hover:bg-white/10 px-6 py-2.5 rounded-xl text-[10px]",
    danger: "bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20 px-6 py-2.5 rounded-xl text-[10px]",
    ghost: "bg-transparent text-slate-500 hover:text-white hover:bg-white/5 rounded-lg text-[10px]",
  };

  return (
    <button className={`${baseStyles} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
}
