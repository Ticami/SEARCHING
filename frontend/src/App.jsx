import React, { useEffect, useState } from "react";
import { BrowserRouter as Router, Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home";
import Reports from "./pages/Reports";
import Links from "./pages/Links";
import Prints from "./pages/Prints";
import Curves from "./pages/Curves"; // nova rota
import Review from "./pages/Review";
import Alerts from "./pages/Alerts";
import Assisted from "./pages/Assisted";
import { Conta, Login, Usuarios, useAuth } from "./auth.jsx";
import "./styles/global.css";

export default function App() {
  const { carregando, usuario, modo, pode, sair } = useAuth();
  const [pendentes, setPendentes] = useState(0);

  // Contador de links aguardando revisão, mostrado no menu.
  useEffect(() => {
    if (!usuario) return undefined;
    const contar = () =>
      fetch("/api/revisoes")
        .then((r) => r.json())
        .then((j) => setPendentes(Array.isArray(j) ? j.length : 0))
        .catch(() => {});
    contar();
    const t = setInterval(contar, 60000);
    window.addEventListener("revisoes-changed", contar);
    return () => {
      clearInterval(t);
      window.removeEventListener("revisoes-changed", contar);
    };
  }, [usuario]);

  useEffect(() => {
    // remove a chave da antiga tela de senha, se existir no navegador
    try {
      localStorage.removeItem("searching_auth");
    } catch {}
  }, []);

  if (carregando) return null;
  if (!usuario) return <Login />;

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

            {pode("coletor") && (
              <NavLink
                to="/assisted"
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              >
                Coleta assistida
              </NavLink>
            )}

            <NavLink
              to="/alerts"
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              Alertas
            </NavLink>

            <NavLink
              to="/review"
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              Revisão{pendentes > 0 ? ` (${pendentes})` : ""}
            </NavLink>

            {modo === "hospedado" && (
              <NavLink to="/conta" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
                Minha conta
              </NavLink>
            )}
            {modo === "hospedado" && pode("admin") && (
              <NavLink to="/usuarios" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
                Usuários
              </NavLink>
            )}
            {modo === "hospedado" && (
              <button className="btn ghost" onClick={sair}>Sair ({usuario.papel})</button>
            )}
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
            <Route path="/review" element={<Review />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/assisted" element={pode("coletor") ? <Assisted /> : <Home />} />
            <Route path="/conta" element={<Conta />} />
            <Route path="/usuarios" element={pode("admin") ? <Usuarios /> : <Home />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}
