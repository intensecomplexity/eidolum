import { lazy, Suspense, useState } from 'react';
import { Routes, Route, Navigate, useParams } from 'react-router-dom';

// ── Eager shell + entry routes ──────────────────────────────────────────────
// Things that ship in the initial JS download. Kept eager because:
//  - Navbar / BottomNav / SaveToast / ComparisonTray render on every route.
//  - Splash + Onboarding are pre-paint chrome.
//  - Landing / LandingPublic / Dashboard cover ~all first-visit destinations.
//  - Leaderboard is the most-trafficked route by far.
//  - Login / Register / NotFound are tiny, frequently first-visited for new
//    users / catch-all fallback.
import Navbar from './components/Navbar';
import BottomNav from './components/BottomNav';
import SaveToast from './components/SaveToast';
import ComparisonTray from './components/ComparisonTray';
import OnboardingOverlay from './components/OnboardingOverlay';
import VaultDoorSplash from './components/VaultDoorSplash';
import { ErrorBoundary } from './components/ErrorBoundary';
import LoadingSpinner from './components/LoadingSpinner';
import Landing from './pages/Landing';
import LandingPublic from './pages/LandingPublic';
import Dashboard from './pages/Dashboard';
import Leaderboard from './pages/Leaderboard';
import Login from './pages/Login';
import Register from './pages/Register';
import NotFound from './pages/NotFound';

// ── Lazy routes ─────────────────────────────────────────────────────────────
// Each route's code lives in its own chunk and downloads only when the user
// navigates there. The Recharts library (used by ~10 of these) is split into
// its own vendor chunk via vite.config.js manualChunks — pages that import
// charts pull from that shared chunk instead of duplicating chart code.
const ForecasterProfile      = lazy(() => import('./pages/ForecasterProfile'));
const AssetConsensus         = lazy(() => import('./pages/AssetConsensus'));
const Platforms              = lazy(() => import('./pages/Platforms'));
const PlatformDetail         = lazy(() => import('./pages/PlatformDetail'));
const SavedPredictions       = lazy(() => import('./pages/SavedPredictions'));
const WatchlistPage          = lazy(() => import('./pages/WatchlistPage'));
const PredictionOfTheDayPage = lazy(() => import('./pages/PredictionOfTheDayPage'));
const ReportCards            = lazy(() => import('./pages/ReportCards'));
const ContrarianSignals      = lazy(() => import('./pages/ContrarianSignals'));
const PowerRankings          = lazy(() => import('./pages/PowerRankings'));
const InversePortfolio       = lazy(() => import('./pages/InversePortfolio'));
const RecentPredictions      = lazy(() => import('./pages/RecentPredictions'));
const ForecastersList        = lazy(() => import('./pages/ForecastersList'));
const AdminPanel             = lazy(() => import('./pages/AdminPanel'));
const AdminDashboard         = lazy(() => import('./pages/AdminDashboard'));
const AdminXAccounts         = lazy(() => import('./pages/AdminXAccounts'));
const AdminYouTubeChannels   = lazy(() => import('./pages/AdminYouTubeChannels'));
const AdminSectorAliases     = lazy(() => import('./pages/AdminSectorAliases'));
const AdminMacroConcepts     = lazy(() => import('./pages/AdminMacroConcepts'));
const ForgotPassword         = lazy(() => import('./pages/ForgotPassword'));
const ResetPassword          = lazy(() => import('./pages/ResetPassword'));
const GoogleCallback         = lazy(() => import('./pages/GoogleCallback'));
const Profile                = lazy(() => import('./pages/Profile'));
const SubmitCall             = lazy(() => import('./pages/SubmitCall'));
const MyCalls                = lazy(() => import('./pages/MyCalls'));
const CommunityLeaderboard   = lazy(() => import('./pages/CommunityLeaderboard'));
const Badges                 = lazy(() => import('./pages/Badges'));
const Consensus              = lazy(() => import('./pages/Consensus'));
const Duels                  = lazy(() => import('./pages/Duels'));
const Seasons                = lazy(() => import('./pages/Seasons'));
const Friends                = lazy(() => import('./pages/Friends'));
const Notifications          = lazy(() => import('./pages/Notifications'));
const TickerDetail           = lazy(() => import('./pages/TickerDetail'));
const Activity               = lazy(() => import('./pages/Activity'));
const PredictionView         = lazy(() => import('./pages/PredictionView'));
const DailyChallengePage     = lazy(() => import('./pages/DailyChallenge'));
const ToldYouSo              = lazy(() => import('./pages/ToldYouSo'));
const SettingsPage           = lazy(() => import('./pages/Settings'));
const ControversialPage      = lazy(() => import('./pages/Controversial'));
const AnalystsPage           = lazy(() => import('./pages/Analysts'));
const AnalystProfilePage     = lazy(() => import('./pages/AnalystProfile'));
const HeatmapPage            = lazy(() => import('./pages/Heatmap'));
const EarningsPage           = lazy(() => import('./pages/Earnings'));
const ComparePage            = lazy(() => import('./pages/Compare'));
const CompareForecasters     = lazy(() => import('./pages/CompareForecasters'));
const Discover               = lazy(() => import('./pages/Discover'));
const AllSectors             = lazy(() => import('./pages/AllSectors'));
const SmartMoney             = lazy(() => import('./pages/SmartMoney'));
const Tournaments            = lazy(() => import('./pages/Tournaments'));
const HowItWorks             = lazy(() => import('./pages/HowItWorks'));
const FirmProfile            = lazy(() => import('./pages/FirmProfile'));

import { useAuth } from './context/AuthContext';
import { useFeatures } from './context/FeatureContext';
import { CompareProvider } from './context/CompareContext';
import { SubscriptionsProvider } from './context/SubscriptionsContext';

// Ship #13 Bug B: /ticker/:symbol is a legacy alias. Redirect to the
// canonical /asset/:ticker URL so TickerDetail only ever receives one
// param name and there is a single source of truth for price/SEO.
function LegacyTickerRedirect() {
  const { symbol } = useParams();
  return <Navigate to={`/asset/${symbol}`} replace />;
}

function ComingSoon({ feature }) {
  return (
    <div className="max-w-lg mx-auto px-4 py-20 text-center">
      <div className="text-4xl mb-4">🚧</div>
      <h1 className="text-xl font-bold mb-2">{feature} — Coming Soon</h1>
      <p className="text-text-secondary text-sm">This feature is being built. Check back soon.</p>
    </div>
  );
}

// Suspense fallback rendered while a lazy route chunk is downloading.
// Centered subtle spinner — matches LoadingSpinner used elsewhere on
// data-fetch waits. Visible for ~100-300ms on first navigation to a
// previously-uncached route, then vanishes when the chunk lands.
function RouteFallback() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <LoadingSpinner size="lg" />
    </div>
  );
}

export default function App() {
  const { isAuthenticated } = useAuth();
  const features = useFeatures();
  const [showOnboarding, setShowOnboarding] = useState(() => {
    return !localStorage.getItem('eidolum_token') && !localStorage.getItem('eidolum_onboarding_complete');
  });
  const [splashDone, setSplashDone] = useState(() =>
    !!sessionStorage.getItem('eidolum_splash_seen') ||
    !!localStorage.getItem('eidolum_visited')
  );

  return (
    <CompareProvider>
    <SubscriptionsProvider>
    <div className="min-h-screen bg-bg pb-bottom-nav sm:pb-0">
      {!splashDone && <VaultDoorSplash onComplete={() => setSplashDone(true)} />}
      <Navbar />
      {showOnboarding && !isAuthenticated && (
        <OnboardingOverlay onComplete={() => setShowOnboarding(false)} />
      )}
      <ErrorBoundary>
      <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/" element={isAuthenticated ? <Dashboard /> : <LandingPublic />} />
        <Route path="/home" element={<Landing />} />
        <Route path="/leaderboard" element={<Leaderboard />} />
        <Route path="/leaderboard/report-cards" element={<ReportCards />} />
        <Route path="/platforms" element={<Platforms />} />
        <Route path="/platforms/:platformId" element={<PlatformDetail />} />
        <Route path="/forecaster/:id" element={<ForecasterProfile />} />
        <Route path="/analyst/:slug" element={<ForecasterProfile />} />
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
        <Route path="/admin/x-accounts" element={<AdminXAccounts />} />
        <Route path="/admin/youtube-channels" element={<AdminYouTubeChannels />} />
        <Route path="/admin/sector-aliases" element={<AdminSectorAliases />} />
        <Route path="/admin/macro-concepts" element={<AdminMacroConcepts />} />
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
        <Route path="/duels" element={features.duels ? <Duels /> : <ComingSoon feature="Duels" />} />
        <Route path="/compete" element={features.compete ? <Seasons /> : <ComingSoon feature="Compete" />} />
        <Route path="/seasons" element={features.compete ? <Seasons /> : <ComingSoon feature="Compete" />} />
        <Route path="/friends" element={<Friends />} />
        <Route path="/notifications" element={<Notifications />} />
        <Route path="/ticker/:symbol" element={<LegacyTickerRedirect />} />
        <Route path="/activity" element={<Activity />} />
        <Route path="/prediction/:predictionId" element={<PredictionView />} />
        <Route path="/daily-challenge" element={<DailyChallengePage />} />
        <Route path="/prediction/:predictionId/told-you-so" element={<ToldYouSo />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/controversial" element={<ControversialPage />} />
        <Route path="/compare/:id1/:id2" element={features.compare_analysts ? <ComparePage /> : <ComingSoon feature="Compare Analysts" />} />
        <Route path="/compare" element={features.compare_analysts ? <CompareForecasters /> : <ComingSoon feature="Compare Analysts" />} />
        <Route path="/analysts" element={<AnalystsPage />} />
        <Route path="/analyst/:name" element={<AnalystProfilePage />} />
        <Route path="/heatmap" element={<HeatmapPage />} />
        <Route path="/discover" element={<Discover />} />
        <Route path="/sectors" element={<AllSectors />} />
        <Route path="/smart-money" element={<SmartMoney />} />
        <Route path="/how-it-works" element={<HowItWorks />} />
        <Route path="/firm/:slug" element={<FirmProfile />} />
        <Route path="/earnings" element={<EarningsPage />} />
        <Route path="/compete/tournaments" element={<Tournaments />} />
        {/* Ship #13B Bug 11: catch-all 404. Must stay at the bottom so
            every explicit route above wins first. Route-specific not-
            found states still fire (e.g. /forecaster/99999999 renders
            ForecasterProfile's own "not found"), and only truly
            unmatched paths fall through to this component. */}
        <Route path="*" element={<NotFound />} />
      </Routes>
      </Suspense>
      </ErrorBoundary>
      <SaveToast />
      <ComparisonTray />
      <BottomNav />
    </div>
    </SubscriptionsProvider>
    </CompareProvider>
  );
}
