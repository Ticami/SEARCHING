import React from "react";
import { BrowserRouter as Router, Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home";
import Reports from "./pages/Reports";
import Links from "./pages/Links";
import Prints from "./pages/Prints";
import Curves from "./pages/Curves";   // ⬅️ NOVA ABA
import "./styles/global.css";

export default function App() {
  return (
    <Router>
      <div className="layout">
        <aside className="sidebar">
          <h2 className="logo">SEARCHING</h2>

          <nav>
            <NavLink
              to="/"
              end
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              Início
            </NavLink>

            <NavLink
              to="/reports"
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              Relatórios
            </NavLink>

            <NavLink
              to="/curves"
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              Curvas
            </NavLink>

            <NavLink
              to="/prints"
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              Prints
            </NavLink>

            <NavLink
              to="/links"
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              Links
            </NavLink>
          </nav>

          <footer>by Mateus Ticami · v1.2.0</footer>
        </aside>

        <main className="content">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/curves" element={<Curves />} /> {/* ⬅️ NOVA ROTA */}
            <Route path="/prints" element={<Prints />} />
            <Route path="/links" element={<Links />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}
