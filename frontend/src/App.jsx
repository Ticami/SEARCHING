import React, { useEffect, useState } from "react";
import { BrowserRouter as Router, Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home";
import Reports from "./pages/Reports";
import Links from "./pages/Links";
import Prints from "./pages/Prints";
import Curves from "./pages/Curves"; // nova rota
import "./styles/global.css";

export default function App() {
  const ACCESS_KEY = "searching_auth";
  const PASSCODE = "***REMOVED***";
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [isAuthorized, setIsAuthorized] = useState(
    () => localStorage.getItem(ACCESS_KEY) === PASSCODE
  );

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() === PASSCODE) {
      localStorage.setItem(ACCESS_KEY, PASSCODE);
      setIsAuthorized(true);
      setError("");
      setInput("");
    } else {
      setError("Senha incorreta. Tente novamente.");
    }
  };

  useEffect(() => {
    if (isAuthorized) {
      localStorage.setItem(ACCESS_KEY, PASSCODE);
    }
  }, [isAuthorized]);

  if (!isAuthorized) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>SEARCHING</h1>
          <p>Digite a senha para continuar.</p>
          <form className="auth-form" onSubmit={handleSubmit}>
            <input
              type="password"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Senha"
              autoFocus
            />
            {error && <span className="auth-error">{error}</span>}
            <button className="btn primary" type="submit">Entrar</button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <Router>
      <div className="layout">
        <aside className="sidebar">
          <div className="sidebar-header">
            <h2 className="logo">SEARCHING</h2>
            <span className="chip chip-active" style={{ padding: "6px 10px", fontSize: 12 }}>v1.2.0</span>
          </div>

          <nav>
            <NavLink
              to="/"
              end
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              Início
            </NavLink>

            <NavLink
              to="/reports"
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              Relatórios
            </NavLink>

            <NavLink
              to="/curves"
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              Curvas
            </NavLink>

            <NavLink
              to="/prints"
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              Prints
            </NavLink>

            <NavLink
              to="/links"
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              Links
            </NavLink>
          </nav>

          <footer>by Mateus Ticami</footer>
        </aside>

        <main className="content">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/curves" element={<Curves />} />
            <Route path="/prints" element={<Prints />} />
            <Route path="/links" element={<Links />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}
