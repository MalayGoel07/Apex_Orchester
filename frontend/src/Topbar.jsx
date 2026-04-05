import { Link } from "react-router-dom";

const Topbar = ({ onMenuClick }) => {
  return (
    <div className="fixed top-0 left-0 right-0 z-40 bg-black/80 backdrop-blur-xl border-b border-white/10 shadow-2xl px-6 py-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <button onClick={onMenuClick} className="md:hidden p-2 rounded-xl hover:bg-white/10 transition">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <h1 className="text-2xl font-bold bg-gradient-to-r from-emerald-400 to-green-400 bg-clip-text text-transparent">Apex Orchester</h1>
      </div>
      <div className="flex gap-3">
        <Link to="/login" className="border border-white/20 px-4 py-2 rounded-xl text-sm hover:bg-white/10 hover:-translate-y-1 transition-all duration-200" >Login</Link>
        <Link to="/signup" className="bg-gradient-to-r from-emerald-500 to-emerald-400 text-black px-4 py-2 rounded-xl text-sm font-medium hover:from-emerald-400 hover:to-emerald-300 hover:-translate-y-1 transition-all duration-200 shadow-lg" >Sign Up </Link>
      </div>
    </div>
  );
};

export default Topbar;

