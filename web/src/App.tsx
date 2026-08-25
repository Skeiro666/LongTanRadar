import { NavLink, Route, Routes } from "react-router-dom";
import Agent from "./pages/Agent";
import AlphaLab from "./pages/AlphaLab";
import LeaderMonitor from "./pages/LeaderMonitor";
import EntryValidation from "./pages/EntryValidation";
import Notifications from "./pages/Notifications";
import Overview from "./pages/Overview";
import PositionDetail from "./pages/PositionDetail";
import Positions from "./pages/Positions";
import Research from "./pages/Research";
import ResearchDetail from "./pages/ResearchDetail";
import TokenDashboard from "./pages/TokenDashboard";

export default function App() {
  return (
    <div className="app-shell">
      <header className="topnav">
        <div className="brand">
          <img className="brand-logo" src="/logo.png" alt="寻龙尺" width={40} height={40} />
          <div className="brand-text">
            <span className="brand-title">寻龙尺</span>
            <span className="brand-sub">XUN LONG CHI · 大A龙头探查</span>
          </div>
        </div>
        <nav className="nav-links">
          <NavLink to="/" end>
            总览
          </NavLink>
          <NavLink to="/research">圆桌研报</NavLink>
          <NavLink to="/leader">龙头监控</NavLink>
          <NavLink to="/entry-validation">买点验证</NavLink>
          <NavLink to="/positions">持仓/退出</NavLink>
          <NavLink to="/notifications">通知</NavLink>
          <NavLink to="/alpha-lab">Alpha 实验室</NavLink>
          <NavLink to="/token">Token 成本</NavLink>
          <NavLink to="/agent">研究循环</NavLink>
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/research" element={<Research />} />
          <Route path="/leader" element={<LeaderMonitor />} />
          <Route path="/entry-validation" element={<EntryValidation />} />
          <Route path="/research/:researchId/:symbol" element={<ResearchDetail />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/positions/:symbol" element={<PositionDetail />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/alpha-lab" element={<AlphaLab />} />
          <Route path="/token" element={<TokenDashboard />} />
          <Route path="/agent" element={<Agent />} />
          <Route path="*" element={<Overview />} />
        </Routes>
      </main>
    </div>
  );
}
