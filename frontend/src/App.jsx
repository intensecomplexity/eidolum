import { Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import BottomNav from './components/BottomNav';
import SaveToast from './components/SaveToast';
import Landing from './pages/Landing';
import Leaderboard from './pages/Leaderboard';
import ForecasterProfile from './pages/ForecasterProfile';
import AssetConsensus from './pages/AssetConsensus';
import Platforms from './pages/Platforms';
import PlatformDetail from './pages/PlatformDetail';
import SavedPredictions from './pages/SavedPredictions';
import Watchlist from './pages/Watchlist';
import PredictionOfTheDayPage from './pages/PredictionOfTheDayPage';
import ReportCards from './pages/ReportCards';
import ContrarianSignals from './pages/ContrarianSignals';
import PowerRankings from './pages/PowerRankings';
import InversePortfolio from './pages/InversePortfolio';
import RecentPredictions from './pages/RecentPredictions';
import ForecastersList from './pages/ForecastersList';
import AdminPanel from './pages/AdminPanel';

export default function App() {
  return (
    <div className="min-h-screen bg-bg pb-bottom-nav sm:pb-0">
      <Navbar />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/leaderboard" element={<Leaderboard />} />
        <Route path="/leaderboard/report-cards" element={<ReportCards />} />
        <Route path="/platforms" element={<Platforms />} />
        <Route path="/platforms/:platformId" element={<PlatformDetail />} />
        <Route path="/forecaster/:id" element={<ForecasterProfile />} />
        <Route path="/asset/:ticker" element={<AssetConsensus />} />
        <Route path="/saved" element={<SavedPredictions />} />
        <Route path="/watchlist" element={<Watchlist />} />
        <Route path="/prediction-of-the-day" element={<PredictionOfTheDayPage />} />
        <Route path="/contrarian" element={<ContrarianSignals />} />
        <Route path="/power-rankings" element={<PowerRankings />} />
        <Route path="/inverse-portfolio" element={<InversePortfolio />} />
        <Route path="/predictions" element={<RecentPredictions />} />
        <Route path="/forecasters" element={<ForecastersList />} />
        <Route path="/admin" element={<AdminPanel />} />
      </Routes>
      <SaveToast />
      <BottomNav />
    </div>
  );
}
