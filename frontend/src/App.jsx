import React, { useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home";
import Reports from "./pages/Reports";
import Links from "./pages/Links";
import Prints from "./pages/Prints";
import Curves from "./pages/Curves"; // nova rota
import "./styles/global.css";

export default function App() {
  useEffect(() => {
    // remove a chave da antiga tela de senha, se existir no navegador
    try {
      localStorage.removeItem("searching_auth");
    } catch {}
  }, []);

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
