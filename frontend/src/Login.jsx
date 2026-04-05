import { useState } from "react";
import { useNavigate } from "react-router-dom";

function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();

  const handleLogin = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();
      console.log(data);

      if (res.ok) {
        alert("Login successful ✅");
        navigate("/dashboard");
      } else {
        alert("Invalid credentials ❌");
      }
    } catch (err) {
      console.error("Login error:", err);
    }
  };

  return (
    <div className="relative min-h-screen text-white px-6 py-10 bg-gradient-to-r from-black via-slate-900 to-black bg-[length:200%_200%] animate-gradient flex justify-center">
      <div className="absolute inset-0 bg-gradient-to-tr from-emerald-500/10 via-transparent to-purple-500/10 blur-3xl pointer-events-none"></div>
      <div className="p-8 w-[600px] h-[400px] rounded-2xl bg-white/[0.05] border border-white/10">
        <button onClick={() => navigate(-1)} className="bg-emerald-400 text-black px-5 py-2 rounded-xl font-medium hover:bg-emerald-300 hover:translate-x-[-10px] transition mb-5" >← Back</button>
        <h2 className="text-2xl font-semibold mb-1">Login</h2>
        <h3 className="text-sl mb-4">Access your dashboard!</h3>
        <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} className="border border-emerald-400 w-full mb-3 p-2 rounded-full bg-black/40 border border-white/10" />
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="border border-emerald-400 w-full mb-4 p-2 rounded-full bg-black/40 border border-white/10" />
        <button onClick={handleLogin} className="w-[200px] bg-emerald-400 text-black py-2 rounded-full hover:bg-emerald-800 hover:text-white" >Login</button>
        <p className="text-sm text-gray-300 mt-4">Don’t have an account?{" "}<span onClick={() => navigate("/signup")} className="text-emerald-400 cursor-pointer hover:text-cyan-400 no-underline">Sign up</span>
        </p>
      </div>
    </div>
  );
}

export default LoginPage;
