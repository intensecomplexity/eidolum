import { Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import BottomNav from './components/BottomNav';
import SaveToast from './components/SaveToast';
import Landing from './pages/Landing';
import LandingPublic from './pages/LandingPublic';
import Dashboard from './pages/Dashboard';
import Leaderboard from './pages/Leaderboard';
import ForecasterProfile from './pages/ForecasterProfile';
import AssetConsensus from './pages/AssetConsensus';
import Platforms from './pages/Platforms';
import PlatformDetail from './pages/PlatformDetail';
import SavedPredictions from './pages/SavedPredictions';
import Watchlist from './pages/Watchlist';
import WatchlistPage from './pages/WatchlistPage';
import PredictionOfTheDayPage from './pages/PredictionOfTheDayPage';
import ReportCards from './pages/ReportCards';
import ContrarianSignals from './pages/ContrarianSignals';
import PowerRankings from './pages/PowerRankings';
import InversePortfolio from './pages/InversePortfolio';
import RecentPredictions from './pages/RecentPredictions';
import ForecastersList from './pages/ForecastersList';
import AdminPanel from './pages/AdminPanel';
import AdminDashboard from './pages/AdminDashboard';
import Login from './pages/Login';
import Register from './pages/Register';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import GoogleCallback from './pages/GoogleCallback';
import Profile from './pages/Profile';
import SubmitCall from './pages/SubmitCall';
import MyCalls from './pages/MyCalls';
import CommunityLeaderboard from './pages/CommunityLeaderboard';
import Badges from './pages/Badges';
import Consensus from './pages/Consensus';
import { Navigate } from 'react-router-dom';
import Duels from './pages/Duels';
import Seasons from './pages/Seasons';
import Friends from './pages/Friends';
import Notifications from './pages/Notifications';
import TickerDetail from './pages/TickerDetail';
import Activity from './pages/Activity';
import PredictionView from './pages/PredictionView';
import DailyChallengePage from './pages/DailyChallenge';
import ToldYouSo from './pages/ToldYouSo';
import SettingsPage from './pages/Settings';
import ControversialPage from './pages/Controversial';
import AnalystsPage from './pages/Analysts';
import AnalystProfilePage from './pages/AnalystProfile';
import HeatmapPage from './pages/Heatmap';
import EarningsPage from './pages/Earnings';
import ComparePage from './pages/Compare';
import Discover from './pages/Discover';
import HowItWorks from './pages/HowItWorks';
import OnboardingOverlay from './components/OnboardingOverlay';
import { useAuth } from './context/AuthContext';
import { useState } from 'react';

export default function App() {
  const { isAuthenticated } = useAuth();
  const [showOnboarding, setShowOnboarding] = useState(() => {
    return !localStorage.getItem('eidolum_token') && !localStorage.getItem('eidolum_onboarding_complete');
  });

  return (
    <div className="min-h-screen bg-bg pb-bottom-nav sm:pb-0">
      <Navbar />
      {showOnboarding && !isAuthenticated && (
        <OnboardingOverlay onComplete={() => setShowOnboarding(false)} />
      )}
      <Routes>
        <Route path="/" element={isAuthenticated ? <Dashboard /> : <LandingPublic />} />
        <Route path="/home" element={<Landing />} />
        <Route path="/leaderboard" element={<Leaderboard />} />
        <Route path="/leaderboard/report-cards" element={<ReportCards />} />
        <Route path="/platforms" element={<Platforms />} />
        <Route path="/platforms/:platformId" element={<PlatformDetail />} />
        <Route path="/forecaster/:id" element={<ForecasterProfile />} />
        <Route path="/asset/:ticker" element={<TickerDetail />} />
        <Route path="/saved" element={<SavedPredictions />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/prediction-of-the-day" element={<PredictionOfTheDayPage />} />
        <Route path="/contrarian" element={<ContrarianSignals />} />
        <Route path="/power-rankings" element={<PowerRankings />} />
        <Route path="/inverse-portfolio" element={<InversePortfolio />} />
        <Route path="/predictions" element={<RecentPredictions />} />
        <Route path="/forecasters" element={<ForecastersList />} />
        <Route path="/admin" element={<AdminPanel />} />
        <Route path="/admin/dashboard" element={<AdminDashboard />} />
        {/* Phase 2 */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/join" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/auth/google/callback" element={<GoogleCallback />} />
        <Route path="/auth/callback" element={<GoogleCallback />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/profile/:userId" element={<Profile />} />
        <Route path="/submit" element={<SubmitCall />} />
        <Route path="/my-calls" element={<MyCalls />} />
        <Route path="/community" element={<CommunityLeaderboard />} />
        <Route path="/badges" element={<Badges />} />
        <Route path="/consensus" element={<Consensus />} />
        <Route path="/expiring" element={<Navigate to="/activity" replace />} />
        <Route path="/duels" element={<Duels />} />
        <Route path="/compete" element={<Seasons />} />
        <Route path="/seasons" element={<Seasons />} />
        <Route path="/friends" element={<Friends />} />
        <Route path="/notifications" element={<Notifications />} />
        <Route path="/ticker/:symbol" element={<TickerDetail />} />
        <Route path="/activity" element={<Activity />} />
        <Route path="/prediction/:predictionId" element={<PredictionView />} />
        <Route path="/daily-challenge" element={<DailyChallengePage />} />
        <Route path="/prediction/:predictionId/told-you-so" element={<ToldYouSo />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/controversial" element={<ControversialPage />} />
        <Route path="/compare/:id1/:id2" element={<ComparePage />} />
        <Route path="/analysts" element={<AnalystsPage />} />
        <Route path="/analyst/:name" element={<AnalystProfilePage />} />
        <Route path="/heatmap" element={<HeatmapPage />} />
        <Route path="/discover" element={<Discover />} />
        <Route path="/how-it-works" element={<HowItWorks />} />
        <Route path="/earnings" element={<EarningsPage />} />
      </Routes>
      <SaveToast />
      <BottomNav />
    </div>
  );
}
