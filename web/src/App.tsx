import { NavLink, Route, Routes } from "react-router-dom";
import Agent from "./pages/Agent";
import Notifications from "./pages/Notifications";
import Overview from "./pages/Overview";
import Research from "./pages/Research";

export default function App() {
  return (
    <div className="app-shell">
      <header className="topnav">
        <div className="brand">
          <span className="brand-title">LONGTAN RADAR</span>
          <span className="brand-sub">龙探雷达 · STRIKE BACK</span>
        </div>
        <nav className="nav-links">
          <NavLink to="/" end>
            总览
          </NavLink>
          <NavLink to="/research">圆桌研报</NavLink>
          <NavLink to="/notifications">通知</NavLink>
          <NavLink to="/agent">研究循环</NavLink>
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/research" element={<Research />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/agent" element={<Agent />} />
          <Route path="*" element={<Overview />} />
        </Routes>
      </main>
    </div>
  );
}
