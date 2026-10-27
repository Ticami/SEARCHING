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
import LinkHistory from "./pages/LinkHistory";
import { Conta, Login, Usuarios, useAuth } from "./auth.jsx";
import { BotaoSidebar, useSidebarRecolhida } from "./sidebar.jsx";
import "./styles/global.css";

// Item do menu: o ícone só aparece com a barra recolhida (o texto continua lido por leitores de tela e vira dica ao passar o mouse).
function Item({ to, end, icone, selo, children, ...resto }) {
  const texto = typeof children === "string" ? children : Array.isArray(children) ? children.join("") : "";
  return (
    <NavLink to={to} end={end} title={texto} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`} {...resto}>
      <span className="nav-icone" aria-hidden="true">{icone}</span>
      <span className="nav-texto">{children}</span>
      {selo > 0 && <span className="nav-selo" aria-hidden="true">{selo}</span>}
    </NavLink>
  );
}

export default function App() {
  const { carregando, usuario, modo, pode, sair, precisa2fa } = useAuth();
  const [pendentes, setPendentes] = useState(0);
  const [recolhida, alternarSidebar] = useSidebarRecolhida();

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
  // administrador sem 2FA: só a tela Minha conta, onde ele ativa (o servidor também bloqueia o resto)
  if (precisa2fa) return <div className="layout"><main className="content"><Conta /></main></div>;

  return (
    <Router>
      <div className={`layout${recolhida ? " sidebar-recolhida" : ""}`}>
        <aside className="sidebar">
          <div className="sidebar-header">
            <h2 className="logo">SEARCHING</h2>
            <span className="chip chip-active sidebar-versao" style={{ padding: "6px 10px", fontSize: 12 }}>v1.2.0</span>
            <BotaoSidebar recolhida={recolhida} onAlternar={alternarSidebar} controla="menu-principal" />
          </div>

          <nav id="menu-principal" aria-label="Menu principal">
            <Item to="/" end icone="🏠">Início</Item>
            <Item to="/reports" icone="📊">Relatórios</Item>
            <Item to="/curves" icone="📈">Curvas</Item>
            <Item to="/prints" icone="🖼️">Prints</Item>
            <Item to="/links" icone="🔗">Links</Item>
            {pode("coletor") && <Item to="/assisted" icone="🧭">Coleta assistida</Item>}
            <Item to="/alerts" icone="🔔">Alertas</Item>
            <Item to="/review" icone="✅" selo={pendentes}>
              Revisão{pendentes > 0 ? ` (${pendentes})` : ""}
            </Item>

            {modo === "hospedado" && <Item to="/conta" icone="👤">Minha conta</Item>}
            {modo === "hospedado" && pode("admin") && <Item to="/usuarios" icone="👥">Usuários</Item>}
            {modo === "hospedado" && (
              <button className="btn ghost" onClick={sair} title={`Sair (${usuario.papel})`}>
                <span className="nav-icone" aria-hidden="true">🚪</span>
                <span className="nav-texto">Sair ({usuario.papel})</span>
              </button>
            )}
          </nav>

          <footer className="sidebar-rodape">by Mateus Ticami</footer>
        </aside>

        <main className="content">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/curves" element={<Curves />} />
            <Route path="/prints" element={<Prints />} />
            <Route path="/links" element={<Links />} />
            <Route path="/links/historico" element={<LinkHistory />} />
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
